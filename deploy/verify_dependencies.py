#!/usr/bin/env python3
"""
Offline-проверка соответствия окружения requirements.lock и SBOM.

Источник: Roadmap §4 (lock и SBOM обязательны), §20.1 (release artifact),
§18.4 (release gates), §22 DoD («backward compatibility проверена»).

Запускается в CI и на целевом хосте перед стартом сервисов. Сети не
требует и ничего не устанавливает: только сравнивает три источника
истины между собой.

    requirements.lock  ←→  установленное окружение
    requirements.lock  ←→  deploy/sbom.cyclonedx.json

Обнаруживает:
    - расхождение версии (в т.ч. подмену транзитивной зависимости);
    - пакет из lock отсутствует в окружении;
    - лишний пакет в окружении, которого нет в lock;
    - запись lock без хеша;
    - неточный пин (>=, ~=, *);
    - расхождение SBOM с lock по составу, версии или хешу;
    - несовпадение платформы с той, на которой снят lock.

Код возврата: 0 — согласовано, 1 — есть расхождения.

Платформа и роль (ADR-012). Артефакты раскладываются по платформам, и
верификатор выбирает lock текущей платформы:

    deploy/dependencies/darwin-arm64/    РОЛЬ: development
    deploy/dependencies/linux-<arch>/    РОЛЬ: production

Режимы:
    (без флагов)     development: проверка состава, расхождение платформы —
                     предупреждение;
    --strict-platform  расхождение платформы — ошибка;
    --release        release gate: требует РОЛЬ production, точное совпадение
                     платформы и python_version. Development-lock как release
                     artifact отвергается — macOS-lock не может выкатиться
                     на Linux;
    --pending-ok     отсутствие lock для текущей платформы — не ошибка, а
                     явный PENDING. Для dev-CI на платформе, для которой lock
                     ещё не снят; production release этим флагом не
                     пользуется.

Ограничение: проверяется состав и метаданные, а не байты установленных
файлов. Хеши из lock относятся к дистрибутивам с PyPI; проверка их
фактического совпадения выполняется на этапе установки командой
`pip install --require-hashes -r <lock>`.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_ROOT = REPO_ROOT / "deploy" / "dependencies"
LOCK_FILENAME = "requirements.lock"
SBOM_FILENAME = "sbom.cyclonedx.json"

ROLE_DEVELOPMENT = "development"
ROLE_PRODUCTION = "production"

BOOTSTRAP = frozenset({"pip", "setuptools", "wheel", "pkg-resources"})
SUPPORTED_SBOM_SPECS = frozenset({"1.4", "1.5", "1.6"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def normalize(name: str) -> str:
    """PEP 503."""
    return re.sub(r"[-_.]+", "-", name).lower()


def platform_info() -> dict[str, str]:
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
    }


def platform_tag(info: dict[str, str] | None = None) -> str:
    info = info or platform_info()
    return f"{info['system'].lower()}-{info['machine'].lower()}"


def artifact_paths(tag: str) -> tuple[Path, Path]:
    directory = ARTIFACTS_ROOT / tag
    return (directory / LOCK_FILENAME, directory / SBOM_FILENAME)


def known_platform_tags() -> list[str]:
    """Платформы, для которых артефакты уже сняты."""
    if not ARTIFACTS_ROOT.exists():
        return []
    return sorted(
        item.name for item in ARTIFACTS_ROOT.iterdir()
        if (item / LOCK_FILENAME).exists()
    )


# ---------------------------------------------------------------------------
# Чтение lock
# ---------------------------------------------------------------------------

def parse_lock(path: Path) -> dict[str, dict]:
    """Разобрать lock: имя → {version, hashes}."""
    if not path.exists():
        raise SystemExit(
            f"ОШИБКА: {path} отсутствует. "
            "Release artifact без dependency lock запрещён (Roadmap §20.1)."
        )

    result: dict[str, dict] = {}
    current: str | None = None

    for lineno, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("--hash="):
            if current is None:
                raise SystemExit(
                    f"ОШИБКА: {path}:{lineno}: хеш без пакета"
                )
            algorithm, _, digest = line.removeprefix("--hash=").partition(":")
            if algorithm != "sha256":
                raise SystemExit(
                    f"ОШИБКА: {path}:{lineno}: алгоритм {algorithm!r} "
                    "не поддерживается; требуется sha256"
                )
            if not SHA256_RE.match(digest.strip()):
                raise SystemExit(
                    f"ОШИБКА: {path}:{lineno}: некорректный SHA-256 "
                    f"{digest.strip()!r}"
                )
            result[current]["hashes"].append(digest.strip())
            continue

        spec = line.rstrip("\\").strip()
        if "==" not in spec:
            raise SystemExit(
                f"ОШИБКА: {path}:{lineno}: неточный пин {spec!r}. "
                "Открытая граница версии ломает воспроизводимость."
            )
        name, _, version = spec.partition("==")
        key = normalize(name.strip())
        if key in result:
            raise SystemExit(
                f"ОШИБКА: {path}:{lineno}: пакет {key} указан повторно"
            )
        result[key] = {"version": version.strip(), "hashes": []}
        current = key

    if not result:
        raise SystemExit(f"ОШИБКА: {path}: пустой lock")

    without_hash = sorted(k for k, v in result.items() if not v["hashes"])
    if without_hash:
        raise SystemExit(
            "ОШИБКА: записи без хеша: " + ", ".join(without_hash)
            + "\nLock без хеша не защищает от подмены артефакта."
        )
    return dict(sorted(result.items()))


def lock_platform(path: Path) -> dict[str, str]:
    """Платформа генерации из шапки lock."""
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"^# Платформа генерации:\s*\n"
        r"#\s+(?P<impl>\S+)\s+(?P<pyver>\S+)\s*\n"
        r"#\s+(?P<system>\S+)\s+(?P<machine>\S+)\s*$",
        text,
        flags=re.MULTILINE,
    )
    if match is None:
        return {}
    return {
        "python_implementation": match.group("impl"),
        "python_version": match.group("pyver"),
        "system": match.group("system"),
        "machine": match.group("machine"),
    }


def lock_role(path: Path) -> str:
    """РОЛЬ из шапки lock: development | production.

    Отсутствие роли трактуется как development: артефакт без явного
    объявления production не может быть release artifact (ADR-012).
    """
    match = re.search(
        r"^#\s*РОЛЬ:\s*(\S+)\s*$",
        path.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    return match.group(1) if match else ROLE_DEVELOPMENT


def display_path(path: Path) -> str:
    """Путь для сообщения: относительный внутри репозитория, иначе полный."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def check_release_role(path: Path, role: str) -> list[str]:
    """Release gate: development-артефакт не может быть выкачен."""
    if role == ROLE_PRODUCTION:
        return []
    return [
        f"РОЛЬ: {display_path(path)} помечен как {role!r} и не "
        "является release artifact (Roadmap §20.1, ADR-012). "
        "Production-lock снимается в чистом Linux-окружении: "
        "python3 deploy/gen_dependency_artifacts.py --role production"
    ]


# ---------------------------------------------------------------------------
# Окружение
# ---------------------------------------------------------------------------

def installed_distributions() -> dict[str, str]:
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


def check_environment(
    locked: dict[str, dict], installed: dict[str, str]
) -> list[str]:
    problems: list[str] = []

    for name, entry in locked.items():
        if name not in installed:
            problems.append(
                f"ОТСУТСТВУЕТ: {name}=={entry['version']} есть в lock, "
                "но не установлен"
            )
        elif installed[name] != entry["version"]:
            problems.append(
                f"ВЕРСИЯ:      {name}: lock {entry['version']}, "
                f"установлено {installed[name]}"
            )

    for name, version in installed.items():
        if name not in locked:
            problems.append(
                f"ЛИШНИЙ:      {name}=={version} установлен, но отсутствует "
                "в lock — состав окружения не зафиксирован"
            )
    return problems


# ---------------------------------------------------------------------------
# SBOM
# ---------------------------------------------------------------------------

def check_sbom(path: Path, locked: dict[str, dict]) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    notes: list[str] = []

    if not path.exists():
        return ([f"ОТСУТСТВУЕТ: {path} — SBOM обязателен (Roadmap §4)"], notes)

    try:
        sbom = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ([f"SBOM: повреждённый JSON: {exc}"], notes)

    if sbom.get("bomFormat") != "CycloneDX":
        problems.append(
            f"SBOM: формат {sbom.get('bomFormat')!r}, ожидался CycloneDX"
        )
    spec = sbom.get("specVersion")
    if spec not in SUPPORTED_SBOM_SPECS:
        problems.append(
            f"SBOM: specVersion {spec!r} не поддерживается "
            f"(ожидалась одна из {sorted(SUPPORTED_SBOM_SPECS)})"
        )

    components = {c["name"]: c for c in sbom.get("components", [])}

    for name in sorted(set(locked) - set(components)):
        problems.append(f"SBOM: {name} есть в lock, но отсутствует в SBOM")
    for name in sorted(set(components) - set(locked)):
        problems.append(f"SBOM: {name} есть в SBOM, но отсутствует в lock")

    for name in sorted(set(locked) & set(components)):
        component = components[name]
        expected = locked[name]["version"]
        if component.get("version") != expected:
            problems.append(
                f"SBOM: {name}: lock {expected}, SBOM {component.get('version')}"
            )

        digests = {
            h.get("content")
            for h in component.get("hashes", [])
            if h.get("alg") == "SHA-256"
        }
        if not digests:
            problems.append(f"SBOM: {name} без SHA-256")
        elif not digests & set(locked[name]["hashes"]):
            problems.append(
                f"SBOM: {name}: хеш не совпадает с lock"
            )

    notes.append(f"SBOM: {len(components)} компонентов, spec {spec}")
    return (problems, notes)


# ---------------------------------------------------------------------------
# Платформа
# ---------------------------------------------------------------------------

def check_platform(locked_info: dict[str, str], strict: bool) -> tuple[list[str], list[str]]:
    if not locked_info:
        message = "Платформа: шапка lock не содержит сведений о платформе"
        return (([message], []) if strict else ([], [message]))

    current = platform_info()
    diffs = [
        f"  {key}: lock {value}, текущая {current[key]}"
        for key, value in locked_info.items()
        if current.get(key) != value
    ]
    if not diffs:
        return ([], [
            f"Платформа: совпадает ({current['system']} {current['machine']}, "
            f"{current['python_implementation']} {current['python_version']})"
        ])

    message = "Платформа расходится с зафиксированной в lock:\n" + "\n".join(diffs)
    if strict:
        return ([message + "\n  Набор содержит платформенно-зависимые колёса."], [])
    return ([], [message + "\n  (--strict-platform делает это ошибкой)"])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверить соответствие окружения requirements.lock и SBOM"
    )
    parser.add_argument(
        "--strict-platform", action="store_true",
        help="считать расхождение платформы ошибкой (для целевого хоста)",
    )
    parser.add_argument(
        "--release", action="store_true",
        help="release gate: требует production-роль и точное совпадение платформы",
    )
    parser.add_argument(
        "--pending-ok", action="store_true",
        help="отсутствие lock для текущей платформы — PENDING, а не ошибка "
             "(только для dev-CI; release gate этим не пользуется)",
    )
    args = parser.parse_args(argv)

    tag = platform_tag()
    lock_path, sbom_path = artifact_paths(tag)
    print(f"платформа: {tag}")

    if not lock_path.exists():
        known = known_platform_tags()
        message = (
            f"lock для платформы {tag} отсутствует: "
            f"{display_path(lock_path)}\n"
            f"  сняты артефакты для: {', '.join(known) if known else '—'}\n"
            "  ручная правка lock другой платформы запрещена; снимите свой:\n"
            "    python3 deploy/gen_dependency_artifacts.py"
        )
        if args.release:
            print(f"ОШИБКА: {message}")
            print("Release без dependency lock своей платформы запрещён "
                  "(Roadmap §20.1, ADR-012).")
            return 1
        if args.pending_ok:
            print(f"PENDING: {message}")
            print("Отмечено как известный незакрытый пункт; production release "
                  "заблокирован до появления этого lock.")
            return 0
        raise SystemExit(f"ОШИБКА: {message}")

    locked = parse_lock(lock_path)
    role = lock_role(lock_path)
    installed = installed_distributions()
    strict_platform = args.strict_platform or args.release

    problems = check_environment(locked, installed)
    sbom_problems, sbom_notes = check_sbom(sbom_path, locked)
    platform_problems, platform_notes = check_platform(
        lock_platform(lock_path), strict_platform
    )
    problems += sbom_problems + platform_problems
    if args.release:
        problems += check_release_role(lock_path, role)

    print(f"lock:      {len(locked)} пакетов ({display_path(lock_path)})")
    print(f"роль:      {role}")
    print(f"окружение: {len(installed)} пакетов")
    for note in sbom_notes + platform_notes:
        print(note)
    print()

    if problems:
        print(f"РАСХОЖДЕНИЙ: {len(problems)}")
        for item in problems:
            print(f"  {item}")
        print()
        print("Действия:")
        print("  воспроизвести зафиксированный состав:")
        print(f"    pip install --require-hashes -r {display_path(lock_path)}")
        print("  либо, если изменение намеренное:")
        print("    обновить requirements.in → pip install → pytest →")
        print("    python3 deploy/gen_dependency_artifacts.py")
        return 1

    if args.release:
        print("RELEASE GATE ПРОЙДЕН: production-lock согласован с окружением.")
    else:
        print("СОГЛАСОВАНО: окружение, lock и SBOM совпадают.")
        if role == ROLE_DEVELOPMENT:
            print("Роль development: артефакт не является release artifact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
