#!/usr/bin/env python3
"""
Генератор requirements.lock и CycloneDX SBOM из ФАКТИЧЕСКОГО окружения.

Источник: Roadmap §4 «Все зависимости фиксируются lock-файлом и SBOM»,
§20.1 «Config snapshot, dependency lock, migrations, release manifest».

Главное правило: состав берётся из установленного окружения, на котором
прошли тесты, а НЕ из свежего разрешения зависимостей.

Почему это важно. Прямые зависимости закреплены точно, но у транзитивных
верхние границы открыты. Проверено на этом проекте: `pip install
pydantic==2.11.1 pytest==8.3.5` в режиме свежего разрешения выбрал
`typing-inspection==0.4.3`, тогда как окружение с зелёными тестами
содержит `0.4.2`. Записать в lock результат нового разрешения означало бы
зафиксировать состав, на котором ничего не проверялось.

Поэтому генератор:
  1. читает установленные дистрибутивы;
  2. передаёт pip ВСЕ версии как точные пины;
  3. падает, если pip вернул хоть одно расхождение.

Обновление зависимости — отдельная осознанная операция:
  поднять версию в requirements.in → pip install → pytest → этот генератор.

Сеть. Генератор обращается к PyPI за хешами дистрибутивов, поэтому
запускается локально, а результат коммитится. В release-контуре сетевая
операция как побочный эффект деплоя недопустима — на целевом хосте
работает только offline `verify_dependencies.py`.

Платформа и роль (ADR-012). Набор колёс платформенно-зависим, поэтому
артефакты раскладываются по платформам:

    deploy/dependencies/darwin-arm64/    РОЛЬ: development
    deploy/dependencies/linux-<arch>/    РОЛЬ: production

Каждый lock несёт в шапке РОЛЬ и ПЛАТФОРМУ. Генератор отказывается
выпускать production-артефакт на Darwin: production-lock снимается только
в чистом Linux-окружении. Ручная правка чужого платформенного lock
запрещена — он перегенерируется на своей платформе.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_IN = REPO_ROOT / "requirements.in"
ARTIFACTS_ROOT = REPO_ROOT / "deploy" / "dependencies"
LOCK_FILENAME = "requirements.lock"
SBOM_FILENAME = "sbom.cyclonedx.json"

# ADR-012: development host — macOS/Darwin arm64; production host — Linux+systemd.
ROLE_DEVELOPMENT = "development"
ROLE_PRODUCTION = "production"
ROLES = (ROLE_DEVELOPMENT, ROLE_PRODUCTION)

# Роль по умолчанию для платформы. Darwin не может выпускать production:
# macOS-lock никогда не является Linux release artifact (ADR-012).
DEFAULT_ROLE_BY_SYSTEM = {"Darwin": ROLE_DEVELOPMENT, "Linux": ROLE_PRODUCTION}

# Bootstrap-инструменты самого venv. Не являются зависимостями проекта
# и не входят в lock: их версия определяется способом создания окружения.
BOOTSTRAP = frozenset({"pip", "setuptools", "wheel", "pkg-resources"})

SBOM_SPEC_VERSION = "1.5"
GENERATOR_NAME = "bybit-platform-dependency-locker"
GENERATOR_VERSION = "1.0"


class GeneratorError(RuntimeError):
    """Генерация невозможна без нарушения гарантий воспроизводимости."""


def normalize(name: str) -> str:
    """PEP 503: имена пакетов сравниваются в нормализованной форме."""
    return re.sub(r"[-_.]+", "-", name).lower()


# ---------------------------------------------------------------------------
# Сбор фактического состояния
# ---------------------------------------------------------------------------

def installed_distributions() -> dict[str, str]:
    """Установленные дистрибутивы: нормализованное имя → версия."""
    result: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name:
            continue
        key = normalize(name)
        if key in BOOTSTRAP:
            continue
        result[key] = dist.version
    return dict(sorted(result.items()))


def installed_metadata(name: str) -> dict[str, str]:
    """Лицензия и summary из установленного дистрибутива."""
    try:
        meta = metadata.metadata(name)
    except metadata.PackageNotFoundError:
        return {"license": "", "summary": ""}

    license_value = meta.get("License-Expression") or meta.get("License") or ""
    if not license_value or len(license_value) > 80:
        # Некоторые пакеты кладут в License полный текст лицензии.
        # Тогда берём классификатор — он короткий и машиночитаемый.
        classifiers = meta.get_all("Classifier") or []
        for item in classifiers:
            if item.startswith("License :: "):
                license_value = item.rsplit(" :: ", 1)[-1]
                break
    return {
        "license": (license_value or "UNKNOWN").strip(),
        "summary": (meta.get("Summary") or "").strip(),
    }


def direct_requirements() -> dict[str, str]:
    """Прямые зависимости из requirements.in: имя → версия."""
    if not REQUIREMENTS_IN.exists():
        raise GeneratorError(f"{REQUIREMENTS_IN} отсутствует")

    result: dict[str, str] = {}
    for lineno, raw in enumerate(
        REQUIREMENTS_IN.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" not in line:
            raise GeneratorError(
                f"{REQUIREMENTS_IN}:{lineno}: требуется точный пин `==`, "
                f"получено {line!r}. Открытая граница ломает воспроизводимость."
            )
        name, _, version = line.partition("==")
        result[normalize(name.strip())] = version.strip()
    if not result:
        raise GeneratorError(f"{REQUIREMENTS_IN}: не найдено ни одной зависимости")
    return dict(sorted(result.items()))


def dependency_graph(names: frozenset[str]) -> dict[str, list[str]]:
    """Кто от кого зависит, в пределах зафиксированного набора."""
    graph: dict[str, list[str]] = {name: [] for name in names}
    for dist in metadata.distributions():
        raw_name = dist.metadata["Name"]
        if not raw_name:
            continue
        owner = normalize(raw_name)
        if owner not in names:
            continue
        edges: set[str] = set()
        for requirement in dist.requires or []:
            # `foo>=1 ; extra == "test"` — extras не входят в базовый набор
            base, _, marker = requirement.partition(";")
            if "extra" in marker:
                continue
            dep = re.split(r"[<>=!~\[\s(]", base.strip(), maxsplit=1)[0]
            dep_key = normalize(dep)
            if dep_key in names and dep_key != owner:
                edges.add(dep_key)
        graph[owner] = sorted(edges)
    return graph


# ---------------------------------------------------------------------------
# Хеши дистрибутивов
# ---------------------------------------------------------------------------

def fetch_hashes(pins: dict[str, str]) -> dict[str, dict[str, str]]:
    """SHA-256 дистрибутивов ровно для переданных версий.

    Все пакеты передаются pip как точные пины, поэтому resolver не имеет
    свободы выбора. Любое расхождение — ошибка, а не повод обновить lock.
    """
    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "report.json"
        command = [
            sys.executable, "-m", "pip", "install",
            "--dry-run",
            "--ignore-installed",
            "--quiet",
            "--report", str(report_path),
            *[f"{name}=={version}" for name, version in pins.items()],
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=600
        )
        if completed.returncode != 0:
            raise GeneratorError(
                "pip не смог разрешить закреплённый набор.\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        report = json.loads(report_path.read_text(encoding="utf-8"))

    resolved: dict[str, dict[str, str]] = {}
    for item in report.get("install", []):
        meta = item.get("metadata", {}) or {}
        name = normalize(meta.get("name", ""))
        version = meta.get("version", "")
        download = item.get("download_info", {}) or {}
        archive = download.get("archive_info", {}) or {}
        hashes = archive.get("hashes", {}) or {}
        sha256 = hashes.get("sha256") or (
            archive.get("hash", "") or ""
        ).removeprefix("sha256=")
        url = download.get("url", "")

        if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
            raise GeneratorError(
                f"{name}=={version}: некорректный SHA-256 {sha256!r}. "
                "Lock без проверяемого хеша не защищает от подмены артефакта."
            )
        resolved[name] = {
            "version": version,
            "sha256": sha256,
            "filename": url.rsplit("/", 1)[-1],
            "url": url,
        }

    assert_matches_environment(pins, resolved)
    return dict(sorted(resolved.items()))


def assert_matches_environment(
    pins: dict[str, str], resolved: dict[str, dict[str, str]]
) -> None:
    """Разрешённый состав обязан совпасть с протестированным окружением."""
    problems: list[str] = []

    for name, version in pins.items():
        if name not in resolved:
            problems.append(f"  {name}=={version}: pip не вернул этот пакет")
        elif resolved[name]["version"] != version:
            problems.append(
                f"  {name}: окружение {version}, pip разрешил "
                f"{resolved[name]['version']}"
            )
    for name, info in resolved.items():
        if name not in pins:
            problems.append(
                f"  {name}=={info['version']}: pip добавил пакет, "
                "которого нет в окружении"
            )

    if problems:
        raise GeneratorError(
            "Разрешённый состав не совпал с установленным окружением:\n"
            + "\n".join(problems)
            + "\n\nLock снимается только с окружения, на котором прошли тесты. "
            "Если обновление намеренно — сначала установите новые версии, "
            "прогоните pytest, затем перегенерируйте артефакты."
        )


# ---------------------------------------------------------------------------
# Платформа
# ---------------------------------------------------------------------------

def platform_info() -> dict[str, str]:
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
    }


def platform_tag(info: dict[str, str] | None = None) -> str:
    """Каталог артефактов: `darwin-arm64`, `linux-x86_64`, `linux-aarch64`."""
    info = info or platform_info()
    return f"{info['system'].lower()}-{info['machine'].lower()}"


# ---------------------------------------------------------------------------
# Сравнение артефактов с окружением (--check)
# ---------------------------------------------------------------------------

# Волатильные поля: меняются при каждом запуске и не несут смысла состава.
# Всё остальное в артефакте детерминировано и обязано совпадать.
_LOCK_TIMESTAMP_RE = re.compile(r"^# Сгенерирован:.*$", flags=re.MULTILINE)
_IGNORED = "<volatile>"


def display_path(path: Path) -> str:
    """Путь для сообщения: относительный внутри репозитория, иначе полный.

    `relative_to` бросает ValueError на пути вне REPO_ROOT, из-за чего
    диагностика падала бы вместо того, чтобы сообщить о проблеме.
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def lock_fingerprint(text: str) -> str:
    """Смысловое содержимое lock без времени генерации."""
    return _LOCK_TIMESTAMP_RE.sub(f"# Сгенерирован: {_IGNORED}", text)


def sbom_fingerprint(sbom: dict) -> dict:
    """Смысловое содержимое SBOM без serialNumber и timestamp."""
    clone = json.loads(json.dumps(sbom))
    clone["serialNumber"] = _IGNORED
    clone.get("metadata", {})["timestamp"] = _IGNORED
    return clone


def compare_artifacts(
    *,
    lock_path: Path,
    sbom_path: Path,
    lock_text: str,
    sbom: dict,
) -> list[str]:
    """Расхождения между артефактами на диске и составом окружения.

    Проверка существования файлов недостаточна: устаревший lock существует,
    но фиксирует не тот состав, на котором прошли тесты. Поэтому сравнивается
    содержимое, а волатильные поля (время, serialNumber) исключаются — иначе
    любой запуск давал бы ложное расхождение.
    """
    problems: list[str] = []

    if not lock_path.exists():
        problems.append(f"{display_path(lock_path)} отсутствует")
    elif lock_fingerprint(
        lock_path.read_text(encoding="utf-8")
    ) != lock_fingerprint(lock_text):
        problems.append(
            f"{display_path(lock_path)} УСТАРЕЛ: состав на диске не "
            "совпадает с окружением"
        )

    if not sbom_path.exists():
        problems.append(f"{display_path(sbom_path)} отсутствует")
    else:
        try:
            on_disk = json.loads(sbom_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(
                f"{display_path(sbom_path)}: повреждённый JSON: {exc}"
            )
        else:
            if sbom_fingerprint(on_disk) != sbom_fingerprint(sbom):
                problems.append(
                    f"{display_path(sbom_path)} УСТАРЕЛ: состав на "
                    "диске не совпадает с окружением"
                )
    return problems


def artifact_paths(tag: str) -> tuple[Path, Path]:
    directory = ARTIFACTS_ROOT / tag
    return (directory / LOCK_FILENAME, directory / SBOM_FILENAME)


def resolve_role(requested: str | None, info: dict[str, str] | None = None) -> str:
    """Роль артефакта для текущей платформы (ADR-012).

    Darwin выпускает только development-артефакты. Это не стилистика:
    production-lock, снятый на macOS, содержит macOS-колёса и на Linux
    невоспроизводим, а его наличие в release-контуре означало бы выкат
    непроверенного состава.
    """
    info = info or platform_info()
    system = info["system"]
    role = requested or DEFAULT_ROLE_BY_SYSTEM.get(system, ROLE_DEVELOPMENT)

    if role not in ROLES:
        raise GeneratorError(
            f"неизвестная роль {role!r}; допустимо: {', '.join(ROLES)}"
        )
    if role == ROLE_PRODUCTION and system != "Linux":
        raise GeneratorError(
            f"production-артефакт нельзя выпустить на {system}: "
            "reference production environment — Linux + systemd (Roadmap §4, "
            "ADR-012). Снимите production-lock в чистом Linux-окружении; "
            "macOS-lock никогда не используется как Linux release artifact."
        )
    return role


def has_platform_specific_wheel(resolved: dict[str, dict[str, str]]) -> list[str]:
    """Пакеты с бинарными колёсами: lock для них платформенно-зависим."""
    generic = re.compile(r"-(py3|py2\.py3)-none-any\.whl$")
    result = []
    for name, info in sorted(resolved.items()):
        filename = info["filename"]
        if filename.endswith(".whl") and not generic.search(filename):
            result.append(f"{name} ({filename})")
    return result


# ---------------------------------------------------------------------------
# Рендеринг lock
# ---------------------------------------------------------------------------

def render_lock(
    *,
    resolved: dict[str, dict[str, str]],
    direct: dict[str, str],
    timestamp: str,
    role: str,
) -> str:
    info = platform_info()
    tag = platform_tag(info)
    binary = has_platform_specific_wheel(resolved)
    direct_list = ", ".join(sorted(direct)) if direct else "—"

    lines: list[str] = [
        "# requirements.lock — полный граф зависимостей с точными версиями и SHA-256.",
        "#",
        "# Источник: Roadmap §4 (lock-файл и SBOM обязательны), §20.1 (release artifact).",
        "# СГЕНЕРИРОВАН АВТОМАТИЧЕСКИ. Не редактировать вручную.",
        "#",
        f"# РОЛЬ:      {role}",
        f"# ПЛАТФОРМА: {tag}",
        "#",
        "#   регенерация: python3 deploy/gen_dependency_artifacts.py",
        "#   проверка:    python3 deploy/verify_dependencies.py",
        "#",
        f"# Сгенерирован:      {timestamp}",
        f"# Прямые зависимости: {direct_list}",
        f"# Всего пакетов:      {len(resolved)}",
        "#",
        "# Платформа генерации:",
        f"#   {info['python_implementation']} {info['python_version']}",
        f"#   {info['system']} {info['machine']}",
        "#",
        "# Состав снят с установленного окружения, на котором прошли тесты,",
        "# а не с нового разрешения зависимостей: у транзитивных пакетов",
        "# верхние границы открыты, и свежее разрешение даёт другой состав.",
    ]

    if role == ROLE_DEVELOPMENT:
        lines += [
            "#",
            "# ЭТО DEVELOPMENT-АРТЕФАКТ. Он не является release artifact.",
            "# Production-хост — Linux + systemd (ADR-012), для него нужен",
            "# отдельный lock, снятый в чистом Linux-окружении:",
            "#   deploy/dependencies/linux-<arch>/requirements.lock",
            "# Ручная правка этого файла под Linux запрещена — состав",
            "# зависит от платформы и должен быть проверен тестами на ней.",
        ]

    if binary:
        lines += [
            "#",
            "# ОГРАНИЧЕНИЕ: набор содержит платформенно-зависимые колёса и",
            f"# действителен только для {info['system']} {info['machine']} /",
            f"# {info['python_implementation']} {info['python_version']}:",
        ]
        lines += [f"#   {item}" for item in binary]
        lines += [
            "# Для другого целевого хоста нужен отдельный lock той платформы.",
            "# Разделение хостов зафиксировано в ADR-012 (закрывает CONFLICT-004);",
            "# архитектура production-хоста и точная версия Python — OPEN.",
        ]

    lines += ["", "# --- Прямые зависимости ---"]
    for name in sorted(direct):
        entry = resolved[name]
        lines += [
            "",
            f"#   {entry['filename']}",
            f"{name}=={entry['version']} \\",
            f"    --hash=sha256:{entry['sha256']}",
        ]

    transitive = sorted(set(resolved) - set(direct))
    if transitive:
        lines += ["", "# --- Транзитивные зависимости ---"]
        for name in transitive:
            entry = resolved[name]
            lines += [
                "",
                f"#   {entry['filename']}",
                f"{name}=={entry['version']} \\",
                f"    --hash=sha256:{entry['sha256']}",
            ]

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Рендеринг SBOM (CycloneDX)
# ---------------------------------------------------------------------------

def render_sbom(
    *,
    resolved: dict[str, dict[str, str]],
    direct: dict[str, str],
    graph: dict[str, list[str]],
    timestamp: str,
    role: str,
) -> dict:
    info = platform_info()
    root_ref = "bybit-orderflow-platform"

    components = []
    for name, entry in resolved.items():
        meta = installed_metadata(name)
        purl = f"pkg:pypi/{name}@{entry['version']}"
        component = {
            "type": "library",
            "bom-ref": purl,
            "name": name,
            "version": entry["version"],
            "purl": purl,
            "scope": "required",
            "hashes": [{"alg": "SHA-256", "content": entry["sha256"]}],
            "licenses": [{"license": {"name": meta["license"]}}],
            "properties": [
                {"name": "bybit:dependency_kind",
                 "value": "direct" if name in direct else "transitive"},
                {"name": "bybit:distribution_filename",
                 "value": entry["filename"]},
            ],
        }
        if meta["summary"]:
            component["description"] = meta["summary"]
        if entry["url"]:
            component["externalReferences"] = [
                {"type": "distribution", "url": entry["url"]}
            ]
        components.append(component)

    dependencies = [
        {
            "ref": root_ref,
            "dependsOn": [f"pkg:pypi/{n}@{resolved[n]['version']}"
                          for n in sorted(direct)],
        }
    ]
    for name in sorted(resolved):
        dependencies.append({
            "ref": f"pkg:pypi/{name}@{resolved[name]['version']}",
            "dependsOn": [f"pkg:pypi/{d}@{resolved[d]['version']}"
                          for d in graph.get(name, [])],
        })

    return {
        "bomFormat": "CycloneDX",
        "specVersion": SBOM_SPEC_VERSION,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "tools": [{
                "vendor": "bybit-orderflow-platform",
                "name": GENERATOR_NAME,
                "version": GENERATOR_VERSION,
            }],
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": "bybit-orderflow-platform",
                "version": "0.0.0",
                "description": (
                    "Bybit Order Flow platform. Stage 1: schemas и storage core. "
                    "Ни один из шести сервисов не реализован, подключений "
                    "к Bybit нет."
                ),
                "licenses": [{"license": {"name": "UNLICENSED"}}],
            },
            "properties": [
                {"name": "bybit:artifact_role", "value": role},
                {"name": "bybit:platform_tag", "value": platform_tag(info)},
                {"name": "bybit:python_implementation",
                 "value": info["python_implementation"]},
                {"name": "bybit:python_version", "value": info["python_version"]},
                {"name": "bybit:platform_system", "value": info["system"]},
                {"name": "bybit:platform_machine", "value": info["machine"]},
                {"name": "bybit:source_of_truth",
                 "value": "installed environment (tests green), "
                          "not fresh dependency resolution"},
                {"name": "bybit:stage", "value": "1"},
                {"name": "bybit:release_artifact",
                 "value": "true" if role == ROLE_PRODUCTION else "false"},
            ],
        },
        "components": components,
        "dependencies": dependencies,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Сгенерировать requirements.lock и CycloneDX SBOM"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="не писать файлы; упасть, если артефакты расходятся с окружением",
    )
    parser.add_argument(
        "--role", choices=ROLES, default=None,
        help="роль артефакта; по умолчанию development на Darwin, "
             "production на Linux (ADR-012)",
    )
    args = parser.parse_args(argv)

    info = platform_info()
    tag = platform_tag(info)
    role = resolve_role(args.role, info)
    lock_path, sbom_path = artifact_paths(tag)

    env = installed_distributions()
    direct = direct_requirements()

    missing = sorted(set(direct) - set(env))
    if missing:
        raise GeneratorError(
            "Прямые зависимости из requirements.in не установлены: "
            + ", ".join(missing)
        )
    mismatched = [
        f"  {name}: requirements.in {version}, установлено {env[name]}"
        for name, version in direct.items()
        if env[name] != version
    ]
    if mismatched:
        raise GeneratorError(
            "requirements.in расходится с окружением:\n" + "\n".join(mismatched)
        )

    print(f"Платформа: {tag}, роль: {role}")
    print(f"Окружение: {len(env)} пакетов ({len(direct)} прямых)")
    print("Запрос хешей у PyPI для закреплённых версий...")
    resolved = fetch_hashes(env)
    print(f"Получено хешей: {len(resolved)}")

    graph = dependency_graph(frozenset(resolved))
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    lock_text = render_lock(
        resolved=resolved, direct=direct, timestamp=timestamp, role=role
    )
    sbom = render_sbom(
        resolved=resolved, direct=direct, graph=graph, timestamp=timestamp, role=role
    )
    sbom_text = json.dumps(sbom, indent=2, ensure_ascii=False, sort_keys=False) + "\n"

    if args.check:
        problems = compare_artifacts(
            lock_path=lock_path, sbom_path=sbom_path,
            lock_text=lock_text, sbom=sbom,
        )
        if problems:
            raise GeneratorError(
                "артефакты расходятся с окружением:\n"
                + "\n".join(f"  {item}" for item in problems)
                + "\n\nПерегенерируйте после зелёного прогона тестов:\n"
                "  python3 deploy/gen_dependency_artifacts.py"
            )
        print("--check: артефакты совпадают с составом окружения "
              "(время генерации не сравнивается)")
        return 0

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(lock_text, encoding="utf-8")
    sbom_path.write_text(sbom_text, encoding="utf-8")

    print(f"Записан {display_path(lock_path)}")
    print(f"Записан {display_path(sbom_path)}")

    binary = has_platform_specific_wheel(resolved)
    if binary:
        print()
        print(f"ВНИМАНИЕ: набор платформенно-зависим ({tag}):")
        for item in binary:
            print(f"  {item}")
        print("Для другого целевого хоста нужен отдельный lock (ADR-012).")
    if role == ROLE_DEVELOPMENT:
        print()
        print("РОЛЬ development: это НЕ release artifact. Production-хост — "
              "Linux + systemd; его lock снимается отдельно в Linux-окружении.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GeneratorError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(1)
