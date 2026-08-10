"""
Тесты dependency lock и SBOM.
Источник: Roadmap §4 (lock-файл и SBOM обязательны), §20.1 (release artifact),
§18.4 (release gates).

Позитивные тесты проверяют согласованность зафиксированных артефактов
с окружением. Негативные — что верификатор действительно ловит drift:
верификатор, который всегда возвращает 0, не является проверкой.
"""

from __future__ import annotations

import importlib.util
import json
import platform
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ARTIFACTS_ROOT = REPO_ROOT / "deploy" / "dependencies"
REQUIREMENTS_IN = REPO_ROOT / "requirements.in"
VERIFIER_PATH = REPO_ROOT / "deploy" / "verify_dependencies.py"
GENERATOR_PATH = REPO_ROOT / "deploy" / "gen_dependency_artifacts.py"

# Development-артефакт зафиксирован в git и проверяется на любой платформе:
# он читается как файл, а не сверяется с окружением (ADR-012).
DARWIN_TAG = "darwin-arm64"
DARWIN_LOCK = ARTIFACTS_ROOT / DARWIN_TAG / "requirements.lock"
DARWIN_SBOM = ARTIFACTS_ROOT / DARWIN_TAG / "sbom.cyclonedx.json"

BOOTSTRAP = frozenset({"pip", "setuptools", "wheel", "pkg-resources"})


def current_tag() -> str:
    return f"{platform.system().lower()}-{platform.machine().lower()}"


CURRENT_LOCK = ARTIFACTS_ROOT / current_tag() / "requirements.lock"
CURRENT_SBOM = ARTIFACTS_ROOT / current_tag() / "sbom.cyclonedx.json"


def parse_workflow_triggers(text: str) -> dict[str, dict[str, str]]:
    """Разобрать блок `on:` workflow.

    PyYAML не входит в зафиксированные зависимости, поэтому разбор
    минимальный — но именно структуры, а не подстрок: закомментированное
    объявление `tags` не должно считаться заданным.
    """
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines) if re.fullmatch(r"on:\s*", ln)), None)
    if start is None:
        return {}

    block: list[str] = []
    for line in lines[start + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            break
        block.append(line)

    triggers: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in block:
        indent = len(line) - len(line.lstrip())
        key, _, value = line.strip().partition(":")
        if indent == 2:
            current = key
            triggers[current] = {}
        elif indent >= 4 and current is not None:
            triggers[current][key] = value.strip()
    return triggers


def load_module(path: Path, name: str):
    """Загрузить скрипт из deploy/ как модуль: он не является пакетом."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier():
    return load_module(VERIFIER_PATH, "bybit_verify_dependencies")


@pytest.fixture(scope="module")
def current_lock() -> Path:
    """Lock текущей платформы.

    Отсутствие — не провал: на Linux артефакт ещё не снят (P1-S1-006), и
    dev-CI обязан оставаться зелёным. Production release блокируется
    отдельно, режимом `--release` верификатора.
    """
    if not CURRENT_LOCK.exists():
        pytest.skip(
            f"lock для платформы {current_tag()} не снят: "
            f"{CURRENT_LOCK.relative_to(REPO_ROOT)} (P1-S1-006)"
        )
    return CURRENT_LOCK


@pytest.fixture(scope="module")
def locked(verifier, current_lock):
    return verifier.parse_lock(current_lock)


@pytest.fixture(scope="module")
def installed(verifier):
    return verifier.installed_distributions()


@pytest.fixture(scope="module")
def sbom(current_lock):
    return json.loads(CURRENT_SBOM.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def darwin_lock_text() -> str:
    if not DARWIN_LOCK.exists():
        pytest.skip(f"{DARWIN_LOCK.relative_to(REPO_ROOT)} отсутствует")
    return DARWIN_LOCK.read_text(encoding="utf-8")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def direct_requirement_names() -> frozenset[str]:
    """Прямые зависимости из requirements.in — единственный их источник.

    Хардкод списка ломает тест при каждом штатном добавлении зависимости:
    это ложное срабатывание, а не защита. Проверять надо соответствие
    артефактов объявленным прямым зависимостям.
    """
    names = set()
    for raw in REQUIREMENTS_IN.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            names.add(normalize(line.partition("==")[0].strip()))
    return frozenset(names)


# ===========================================================================
# Артефакты существуют
# ===========================================================================

class TestArtifactsExist:
    def test_requirements_in_exists(self):
        assert REQUIREMENTS_IN.exists(), "requirements.in обязателен (Roadmap §4)"

    def test_development_lock_exists(self):
        assert DARWIN_LOCK.exists(), (
            "development-lock (darwin-arm64) обязателен: на нём идёт разработка"
        )

    def test_development_sbom_exists(self):
        assert DARWIN_SBOM.exists(), "SBOM обязателен (Roadmap §4)"

    def test_generator_exists(self):
        assert GENERATOR_PATH.exists()

    def test_verifier_exists(self):
        assert VERIFIER_PATH.exists()

    def test_lock_is_tracked_by_git(self):
        """Lock, скрытый .gitignore, не попадёт в release artifact (§20.1).

        Исторический дефект: шаблон `*.lock` в секции «Системные»
        исключал requirements.lock из git.
        """
        completed = subprocess.run(
            ["git", "check-ignore", str(DARWIN_LOCK.relative_to(REPO_ROOT))],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert completed.returncode != 0, (
            f"lock игнорируется git: {completed.stdout.strip()}"
        )

    def test_no_lock_in_repo_root(self):
        """Артефакты живут по платформам: безымянный lock в корне двусмыслен."""
        assert not (REPO_ROOT / "requirements.lock").exists(), (
            "requirements.lock в корне не показывает платформу и роль"
        )


# ===========================================================================
# Lock согласован с окружением
# ===========================================================================

class TestLockMatchesEnvironment:
    def test_no_problems_reported(self, verifier, locked, installed):
        problems = verifier.check_environment(locked, installed)
        assert problems == [], "\n".join(problems)

    def test_every_package_has_hash(self, locked):
        without = [name for name, entry in locked.items() if not entry["hashes"]]
        assert without == [], f"без хеша: {without}"

    def test_all_hashes_are_sha256(self, locked):
        for name, entry in locked.items():
            for digest in entry["hashes"]:
                assert re.fullmatch(r"[0-9a-f]{64}", digest), name

    def test_all_versions_exactly_pinned(self, current_lock):
        text = current_lock.read_text(encoding="utf-8")
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("--hash="):
                continue
            assert "==" in line, f"{lineno}: неточный пин {line!r}"

    def test_direct_requirements_present_in_lock(self, locked):
        direct = {}
        for raw in REQUIREMENTS_IN.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            name, _, version = line.partition("==")
            direct[normalize(name.strip())] = version.strip()
        assert direct, "requirements.in не содержит зависимостей"
        for name, version in direct.items():
            assert name in locked, f"{name} отсутствует в lock"
            assert locked[name]["version"] == version, name

    def test_locked_version_equals_installed_metadata(self, locked):
        """Lock снят с окружения: версия совпадает с метаданными дистрибутива."""
        for name, entry in locked.items():
            installed_version = metadata.version(name)
            assert installed_version == entry["version"], (
                f"{name}: lock {entry['version']}, установлено {installed_version}"
            )

    def test_transitive_pin_is_tested_version_not_latest(self, locked):
        """Ключевая проверка задачи.

        Свежее разрешение `pydantic==2.11.1 pytest==8.3.5` выбирает
        typing-inspection 0.4.3, а окружение с зелёными тестами содержит
        0.4.2. Lock обязан зафиксировать протестированную версию.
        """
        name = "typing-inspection"
        if name not in locked:
            pytest.skip(f"{name} отсутствует в текущем наборе зависимостей")
        assert locked[name]["version"] == metadata.version(name)

    def test_no_bootstrap_tools_in_lock(self, locked):
        """pip/setuptools/wheel определяются способом создания venv."""
        assert not (set(locked) & BOOTSTRAP)


# ===========================================================================
# Верификатор ловит drift окружения
# ===========================================================================

class TestVerifierDetectsEnvironmentDrift:
    def test_version_substitution_detected(self, verifier, locked, installed):
        name = next(iter(locked))
        drifted = dict(installed)
        drifted[name] = "0.0.0-substituted"
        problems = verifier.check_environment(locked, drifted)
        assert any("ВЕРСИЯ" in p and name in p for p in problems), problems

    def test_missing_package_detected(self, verifier, locked, installed):
        name = next(iter(locked))
        drifted = {k: v for k, v in installed.items() if k != name}
        problems = verifier.check_environment(locked, drifted)
        assert any("ОТСУТСТВУЕТ" in p and name in p for p in problems), problems

    def test_extra_package_detected(self, verifier, locked, installed):
        drifted = dict(installed)
        drifted["unlocked-package"] = "1.2.3"
        problems = verifier.check_environment(locked, drifted)
        assert any("ЛИШНИЙ" in p and "unlocked-package" in p for p in problems), problems

    def test_transitive_substitution_detected(self, verifier, locked, installed):
        """Подмена транзитивной зависимости обнаруживается так же, как прямой."""
        transitive = sorted(set(locked) - direct_requirement_names())
        assert transitive, "в наборе нет транзитивных зависимостей"
        name = transitive[0]
        drifted = dict(installed)
        drifted[name] = "9.9.9"
        problems = verifier.check_environment(locked, drifted)
        assert any(name in p for p in problems), problems

    def test_empty_environment_reports_every_package(self, verifier, locked):
        problems = verifier.check_environment(locked, {})
        assert len(problems) == len(locked)


# ===========================================================================
# Верификатор ловит некорректный lock
# ===========================================================================

class TestVerifierRejectsBadLock:
    def _write(self, tmp_path: Path, text: str) -> Path:
        path = tmp_path / "requirements.lock"
        path.write_text(text, encoding="utf-8")
        return path

    def test_missing_lock_rejected(self, verifier, tmp_path):
        with pytest.raises(SystemExit, match="отсутствует"):
            verifier.parse_lock(tmp_path / "absent.lock")

    def test_entry_without_hash_rejected(self, verifier, tmp_path):
        path = self._write(tmp_path, "pydantic==2.11.1\n")
        with pytest.raises(SystemExit, match="без хеша"):
            verifier.parse_lock(path)

    def test_imprecise_pin_rejected(self, verifier, tmp_path):
        path = self._write(tmp_path, "pydantic>=2.11.1 \\\n    --hash=sha256:" + "a" * 64 + "\n")
        with pytest.raises(SystemExit, match="неточный пин"):
            verifier.parse_lock(path)

    def test_corrupt_sha256_rejected(self, verifier, tmp_path):
        path = self._write(tmp_path, "pydantic==2.11.1 \\\n    --hash=sha256:deadbeef\n")
        with pytest.raises(SystemExit, match="некорректный SHA-256"):
            verifier.parse_lock(path)

    def test_wrong_hash_algorithm_rejected(self, verifier, tmp_path):
        path = self._write(tmp_path, "pydantic==2.11.1 \\\n    --hash=md5:" + "a" * 32 + "\n")
        with pytest.raises(SystemExit, match="не поддерживается"):
            verifier.parse_lock(path)

    def test_duplicate_package_rejected(self, verifier, tmp_path):
        digest = "a" * 64
        path = self._write(
            tmp_path,
            f"pydantic==2.11.1 \\\n    --hash=sha256:{digest}\n"
            f"pydantic==2.11.2 \\\n    --hash=sha256:{digest}\n",
        )
        with pytest.raises(SystemExit, match="повторно"):
            verifier.parse_lock(path)

    def test_empty_lock_rejected(self, verifier, tmp_path):
        path = self._write(tmp_path, "# только комментарии\n")
        with pytest.raises(SystemExit, match="пустой lock"):
            verifier.parse_lock(path)

    def test_hash_before_package_rejected(self, verifier, tmp_path):
        path = self._write(tmp_path, "    --hash=sha256:" + "a" * 64 + "\n")
        with pytest.raises(SystemExit, match="хеш без пакета"):
            verifier.parse_lock(path)


# ===========================================================================
# SBOM
# ===========================================================================

class TestSbom:
    def test_is_cyclonedx(self, sbom):
        assert sbom["bomFormat"] == "CycloneDX"
        assert sbom["specVersion"] in {"1.4", "1.5", "1.6"}

    def test_has_serial_number(self, sbom):
        assert sbom["serialNumber"].startswith("urn:uuid:")

    def test_consistent_with_lock(self, verifier, locked):
        problems, _ = verifier.check_sbom(CURRENT_SBOM, locked)
        assert problems == [], "\n".join(problems)

    def test_components_match_lock(self, sbom, locked):
        assert {c["name"] for c in sbom["components"]} == set(locked)

    def test_versions_and_hashes_match_lock(self, sbom, locked):
        for component in sbom["components"]:
            name = component["name"]
            assert component["version"] == locked[name]["version"], name
            digests = {
                h["content"] for h in component["hashes"] if h["alg"] == "SHA-256"
            }
            assert digests & set(locked[name]["hashes"]), name

    def test_purls_well_formed(self, sbom):
        for component in sbom["components"]:
            expected = f"pkg:pypi/{component['name']}@{component['version']}"
            assert component["purl"] == expected

    def test_every_component_has_license(self, sbom):
        for component in sbom["components"]:
            assert component.get("licenses"), f"{component['name']} без лицензии"

    def test_no_duplicate_components(self, sbom):
        names = [c["name"] for c in sbom["components"]]
        assert len(names) == len(set(names))

    def test_dependency_graph_present(self, sbom):
        assert sbom["dependencies"], "граф связей обязателен для аудита"

    def test_dependency_refs_resolve(self, sbom):
        known = {c["bom-ref"] for c in sbom["components"]}
        known.add(sbom["metadata"]["component"]["bom-ref"])
        for dep in sbom["dependencies"]:
            assert dep["ref"] in known, dep["ref"]
            for target in dep.get("dependsOn", []):
                assert target in known, f"неизвестная ссылка: {target}"

    def test_root_depends_on_direct_only(self, sbom):
        root_ref = sbom["metadata"]["component"]["bom-ref"]
        entry = next(d for d in sbom["dependencies"] if d["ref"] == root_ref)
        names = {ref.removeprefix("pkg:pypi/").split("@")[0] for ref in entry["dependsOn"]}
        assert names == set(direct_requirement_names())

    def test_direct_dependencies_are_read_from_requirements_in(self):
        """Гард против хардкода: список прямых зависимостей берётся из файла.

        Исторический дефект: тесты сравнивали состав с литералом
        {pydantic, pytest} и падали при штатном добавлении hypothesis.
        """
        names = direct_requirement_names()
        assert names, "requirements.in не содержит прямых зависимостей"
        assert "pydantic" in names and "pytest" in names

    def test_records_platform(self, sbom):
        """Набор содержит бинарные колёса — платформа обязана быть зафиксирована."""
        props = {p["name"] for p in sbom["metadata"]["properties"]}
        assert {
            "bybit:platform_system",
            "bybit:platform_machine",
            "bybit:python_version",
        } <= props

    def test_declares_source_of_truth(self, sbom):
        props = {p["name"]: p["value"] for p in sbom["metadata"]["properties"]}
        assert "installed environment" in props["bybit:source_of_truth"]

    def test_no_false_implementation_claims(self, sbom):
        description = sbom["metadata"]["component"]["description"]
        assert "не реализован" in description

    def test_dependency_kind_marked(self, sbom):
        for component in sbom["components"]:
            kinds = {
                p["value"]
                for p in component["properties"]
                if p["name"] == "bybit:dependency_kind"
            }
            assert kinds <= {"direct", "transitive"} and kinds, component["name"]


# ===========================================================================
# Верификатор ловит drift SBOM
# ===========================================================================

class TestVerifierDetectsSbomDrift:
    def _write(self, tmp_path: Path, sbom: dict) -> Path:
        path = tmp_path / "sbom.cyclonedx.json"
        path.write_text(json.dumps(sbom), encoding="utf-8")
        return path

    def test_missing_sbom_detected(self, verifier, locked, tmp_path):
        problems, _ = verifier.check_sbom(tmp_path / "absent.json", locked)
        assert any("ОТСУТСТВУЕТ" in p for p in problems), problems

    def test_corrupt_json_detected(self, verifier, locked, tmp_path):
        path = tmp_path / "sbom.cyclonedx.json"
        path.write_text("{ not json", encoding="utf-8")
        problems, _ = verifier.check_sbom(path, locked)
        assert any("повреждённый JSON" in p for p in problems), problems

    def test_wrong_format_detected(self, verifier, locked, sbom, tmp_path):
        broken = dict(sbom)
        broken["bomFormat"] = "SPDX"
        problems, _ = verifier.check_sbom(self._write(tmp_path, broken), locked)
        assert any("формат" in p for p in problems), problems

    def test_unsupported_spec_version_detected(self, verifier, locked, sbom, tmp_path):
        broken = dict(sbom)
        broken["specVersion"] = "0.9"
        problems, _ = verifier.check_sbom(self._write(tmp_path, broken), locked)
        assert any("specVersion" in p for p in problems), problems

    def test_version_mismatch_detected(self, verifier, locked, sbom, tmp_path):
        broken = json.loads(json.dumps(sbom))
        broken["components"][0]["version"] = "0.0.0-drift"
        problems, _ = verifier.check_sbom(self._write(tmp_path, broken), locked)
        assert any("lock" in p and "SBOM" in p for p in problems), problems

    def test_hash_mismatch_detected(self, verifier, locked, sbom, tmp_path):
        broken = json.loads(json.dumps(sbom))
        broken["components"][0]["hashes"][0]["content"] = "0" * 64
        problems, _ = verifier.check_sbom(self._write(tmp_path, broken), locked)
        assert any("хеш не совпадает" in p for p in problems), problems

    def test_missing_component_detected(self, verifier, locked, sbom, tmp_path):
        broken = json.loads(json.dumps(sbom))
        removed = broken["components"].pop(0)["name"]
        problems, _ = verifier.check_sbom(self._write(tmp_path, broken), locked)
        assert any(removed in p and "отсутствует в SBOM" in p for p in problems), problems

    def test_extra_component_detected(self, verifier, locked, sbom, tmp_path):
        broken = json.loads(json.dumps(sbom))
        broken["components"].append({
            "type": "library",
            "bom-ref": "pkg:pypi/ghost@1.0.0",
            "name": "ghost",
            "version": "1.0.0",
            "purl": "pkg:pypi/ghost@1.0.0",
            "hashes": [{"alg": "SHA-256", "content": "b" * 64}],
        })
        problems, _ = verifier.check_sbom(self._write(tmp_path, broken), locked)
        assert any("ghost" in p and "отсутствует в lock" in p for p in problems), problems

    def test_component_without_sha256_detected(self, verifier, locked, sbom, tmp_path):
        broken = json.loads(json.dumps(sbom))
        broken["components"][0]["hashes"] = [{"alg": "MD5", "content": "c" * 32}]
        problems, _ = verifier.check_sbom(self._write(tmp_path, broken), locked)
        assert any("без SHA-256" in p for p in problems), problems


# ===========================================================================
# Платформенная привязка
# ===========================================================================

class TestPlatformBinding:
    def test_lock_header_records_platform(self, verifier, current_lock):
        info = verifier.lock_platform(current_lock)
        assert info, "шапка lock обязана содержать платформу генерации"
        assert info["system"] and info["machine"] and info["python_version"]

    def test_current_platform_matches(self, verifier, current_lock):
        problems, _ = verifier.check_platform(
            verifier.lock_platform(current_lock), strict=True
        )
        assert problems == [], "\n".join(problems)

    def test_lock_lives_in_platform_directory(self, verifier, current_lock):
        """Каталог артефакта обязан соответствовать шапке, иначе выбор lock врёт."""
        info = verifier.lock_platform(current_lock)
        assert current_lock.parent.name == verifier.platform_tag(info)

    def test_platform_drift_is_warning_by_default(self, verifier):
        drifted = {"python_implementation": "CPython", "python_version": "3.99.0",
                   "system": "Linux", "machine": "x86_64"}
        problems, notes = verifier.check_platform(drifted, strict=False)
        assert problems == []
        assert any("расходится" in n for n in notes), notes

    def test_platform_drift_is_error_when_strict(self, verifier):
        drifted = {"python_implementation": "CPython", "python_version": "3.99.0",
                   "system": "Linux", "machine": "x86_64"}
        problems, _ = verifier.check_platform(drifted, strict=True)
        assert any("расходится" in p for p in problems), problems

    def test_binary_wheel_limitation_documented(self, current_lock):
        """Если lock содержит платформенное колесо, ограничение должно быть названо."""
        text = current_lock.read_text(encoding="utf-8")
        wheels = re.findall(r"^#\s+(\S+\.whl)$", text, flags=re.MULTILINE)
        platform_specific = [
            w for w in wheels if not re.search(r"-(py3|py2\.py3)-none-any\.whl$", w)
        ]
        if not platform_specific:
            pytest.skip("в наборе нет платформенно-зависимых колёс")
        assert "ОГРАНИЧЕНИЕ" in text, "платформенная привязка не задокументирована"
        assert "ADR-012" in text, "не названо решение о разделении хостов"


# ===========================================================================
# Роль артефакта: development vs production (ADR-012)
# ===========================================================================

class TestArtifactRole:
    def test_darwin_lock_declares_development_role(self, verifier, darwin_lock_text):
        assert re.search(r"^#\s*РОЛЬ:\s*development\s*$", darwin_lock_text,
                         flags=re.MULTILINE), "macOS-lock обязан объявить роль"
        assert verifier.lock_role(DARWIN_LOCK) == "development"

    def test_darwin_lock_declares_platform_tag(self, darwin_lock_text):
        assert re.search(rf"^#\s*ПЛАТФОРМА:\s*{DARWIN_TAG}\s*$", darwin_lock_text,
                         flags=re.MULTILINE)

    def test_darwin_lock_states_it_is_not_release_artifact(self, darwin_lock_text):
        assert "НЕ release artifact" in darwin_lock_text.replace("не является", "НЕ")

    def test_darwin_lock_points_to_linux_lock(self, darwin_lock_text):
        """Читатель обязан узнать, где взять production-артефакт."""
        assert "linux-" in darwin_lock_text
        assert "Linux" in darwin_lock_text

    def test_missing_role_treated_as_development(self, verifier, tmp_path):
        """Артефакт без явной роли не может молча стать production."""
        path = tmp_path / "requirements.lock"
        path.write_text("pydantic==2.11.1 \\\n    --hash=sha256:" + "a" * 64 + "\n",
                        encoding="utf-8")
        assert verifier.lock_role(path) == "development"

    def test_release_gate_rejects_development_lock(self, verifier):
        problems = verifier.check_release_role(DARWIN_LOCK, "development")
        assert problems, "development-lock обязан быть отвергнут release gate"
        assert any("release artifact" in p for p in problems)

    def test_release_gate_accepts_production_lock(self, verifier):
        assert verifier.check_release_role(DARWIN_LOCK, "production") == []

    def test_sbom_records_role_and_release_flag(self, verifier):
        if not DARWIN_SBOM.exists():
            pytest.skip("SBOM darwin-arm64 отсутствует")
        props = {
            p["name"]: p["value"]
            for p in json.loads(DARWIN_SBOM.read_text(encoding="utf-8"))
            ["metadata"]["properties"]
        }
        assert props["bybit:artifact_role"] == "development"
        assert props["bybit:platform_tag"] == DARWIN_TAG
        assert props["bybit:release_artifact"] == "false"


# ===========================================================================
# macOS-артефакт никогда не становится Linux release artifact (ADR-012)
# ===========================================================================

class TestProductionArtifactCannotComeFromDarwin:
    @pytest.fixture(scope="class")
    def generator(self):
        return load_module(GENERATOR_PATH, "bybit_gen_dependency_artifacts_role")

    def test_production_role_refused_on_darwin(self, generator):
        darwin = {"python_implementation": "CPython", "python_version": "3.13.7",
                  "system": "Darwin", "machine": "arm64"}
        with pytest.raises(generator.GeneratorError, match="Linux"):
            generator.resolve_role("production", darwin)

    def test_development_role_allowed_on_darwin(self, generator):
        darwin = {"python_implementation": "CPython", "python_version": "3.13.7",
                  "system": "Darwin", "machine": "arm64"}
        assert generator.resolve_role(None, darwin) == "development"
        assert generator.resolve_role("development", darwin) == "development"

    def test_linux_defaults_to_production(self, generator):
        linux = {"python_implementation": "CPython", "python_version": "3.13.7",
                 "system": "Linux", "machine": "x86_64"}
        assert generator.resolve_role(None, linux) == "production"

    def test_unknown_role_refused(self, generator):
        with pytest.raises(generator.GeneratorError, match="неизвестная роль"):
            generator.resolve_role("staging")

    def test_platform_tag_separates_darwin_and_linux(self, generator):
        darwin = {"python_implementation": "CPython", "python_version": "3.13.7",
                  "system": "Darwin", "machine": "arm64"}
        linux = {"python_implementation": "CPython", "python_version": "3.13.7",
                 "system": "Linux", "machine": "x86_64"}
        assert generator.platform_tag(darwin) == "darwin-arm64"
        assert generator.platform_tag(linux) == "linux-x86_64"
        assert generator.artifact_paths("darwin-arm64")[0] != \
            generator.artifact_paths("linux-x86_64")[0]

    def test_linux_lock_absent_so_production_release_is_blocked(self, verifier):
        """Пока Linux-lock не снят, release gate обязан падать, а не «проходить»."""
        linux_tags = [t for t in verifier.known_platform_tags()
                      if t.startswith("linux-")]
        if linux_tags:
            pytest.skip(f"Linux-артефакты уже сняты: {linux_tags}")
        assert not any(
            (ARTIFACTS_ROOT / t / "requirements.lock").exists()
            for t in ("linux-x86_64", "linux-aarch64")
        ), "Linux-lock появился — обновите P1-S1-006 и снимите этот тест"


# ===========================================================================
# Release gate как процесс: отсутствие lock не должно «проходить»
# ===========================================================================

class TestReleaseGateBehaviour:
    """Проверка через main(), а не только через отдельные функции.

    Верификатор, который при отсутствии lock возвращает 0, не является
    release gate. Здесь фиксируется именно код возврата.
    """

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        """Запуск ТЕМ ЖЕ интерпретатором, что и тесты.

        `python3` из PATH — не то же самое, что интерпретатор тестов:
        без активации venv он берёт системный Python с другим
        site-packages, и верификатор честно сообщает о расхождении
        состава. Проверять нужно окружение под тестом, поэтому
        sys.executable, а не PATH.
        """
        return subprocess.run(
            [sys.executable, str(VERIFIER_PATH), *args],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def test_default_mode_passes_on_development_host(self):
        if not CURRENT_LOCK.exists():
            pytest.skip(f"lock для {current_tag()} не снят")
        result = self._run([])
        assert result.returncode == 0, result.stdout + result.stderr

    def test_release_mode_fails_on_development_lock(self):
        """Главный гарант ADR-012: dev-артефакт не выкатывается."""
        if not CURRENT_LOCK.exists():
            pytest.skip(f"lock для {current_tag()} не снят")
        result = self._run(["--release"])
        assert result.returncode == 1, result.stdout
        assert "release artifact" in result.stdout

    def test_pending_ok_does_not_mask_release_gate(self):
        """--pending-ok смягчает только dev-CI; с --release он не спасает."""
        result = self._run(["--release", "--pending-ok"])
        if CURRENT_LOCK.exists():
            assert result.returncode == 1, result.stdout
        else:
            assert result.returncode == 1, (
                "отсутствие lock при --release обязано быть ошибкой"
            )

    def test_release_mode_implies_strict_platform(self, verifier):
        """В release-режиме расхождение платформы — ошибка, а не заметка."""
        drifted = {"python_implementation": "CPython", "python_version": "3.99.0",
                   "system": "Linux", "machine": "x86_64"}
        problems, _ = verifier.check_platform(drifted, strict=True)
        assert problems

    def test_lock_without_platform_header_rejected_in_strict_mode(self, verifier):
        """Lock без платформы в шапке не может пройти строгую проверку."""
        problems, _ = verifier.check_platform({}, strict=True)
        assert problems, "неизвестная платформа в строгом режиме — ошибка"

    def test_lock_without_platform_header_is_note_by_default(self, verifier):
        problems, notes = verifier.check_platform({}, strict=False)
        assert problems == [] and notes


# ===========================================================================
# CI: платформенно-зависимые гарантии обязаны повторяться на Linux (ADR-012)
# ===========================================================================

class TestContinuousIntegrationContract:
    WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

    @pytest.fixture(scope="class")
    def workflow_text(self) -> str:
        if not self.WORKFLOW.exists():
            pytest.fail(
                "CI-конфигурация обязательна: acceptance criterion P1-S1-003 "
                "требует автоматическую проверку lock-файла"
            )
        return self.WORKFLOW.read_text(encoding="utf-8")

    def test_runs_on_linux(self, workflow_text):
        assert "ubuntu-" in workflow_text, "production-хост Linux не проверяется"

    def test_runs_fault_tests_on_linux(self, workflow_text):
        """WAL, fsync, atomic rename и crash recovery обязаны повторяться на Linux."""
        assert "tests/fault" in workflow_text

    def test_invokes_dependency_verifier(self, workflow_text):
        assert "verify_dependencies.py" in workflow_text

    def test_has_release_gate_with_release_flag(self, workflow_text):
        assert "--release" in workflow_text, "release gate не подключён"

    def test_installs_macos_environment_from_lock_with_hashes(self, workflow_text):
        assert "--require-hashes" in workflow_text

    def test_release_gate_not_triggered_by_plain_push(self, workflow_text):
        """Release gate падает до появления Linux-lock — он не должен красить push."""
        assert "refs/tags/" in workflow_text or "workflow_dispatch" in workflow_text

    def test_release_gate_installs_environment_before_verifying(self, workflow_text):
        """Верификатор сравнивает lock с окружением.

        Если release gate не поставит пакеты из lock, все они будут
        отсутствовать, и gate останется красным даже с валидным
        Linux-lock — то есть перестанет что-либо проверять.
        """
        gate = workflow_text.split("release-gate:", 1)[1]
        assert "--require-hashes" in gate, (
            "release gate не ставит окружение из lock перед проверкой"
        )
        install = gate.index("--require-hashes")
        verify = gate.index("--release", install)
        assert install < verify, "установка обязана идти до верификации"

    def test_linux_job_switches_to_lock_when_it_appears(self, workflow_text):
        """Пока Linux-lock нет — установка по requirements.in; появится — по хешам."""
        linux = workflow_text.split("linux-tests:", 1)[1].split("macos-tests:", 1)[0]
        assert "requirements.in" in linux
        assert "--require-hashes" in linux

    def test_push_trigger_includes_tags(self, workflow_text):
        """Только `branches` не запускает workflow на tag push.

        Release gate условен по `refs/tags/`, поэтому без `tags` в триггере
        он не выполнился бы ни разу — гейт существовал бы лишь на бумаге.
        """
        triggers = parse_workflow_triggers(workflow_text)
        assert "push" in triggers, "триггер push не разобран"
        assert "tags" in triggers["push"], (
            "в push задан только branches: GitHub не запустит workflow по тегу"
        )

    def test_push_trigger_still_covers_branches(self, workflow_text):
        assert "branches" in parse_workflow_triggers(workflow_text)["push"]

    def test_release_gate_reachable_by_tag(self, workflow_text):
        """Условие по тегу имеет смысл только если tag push запускает workflow."""
        triggers = parse_workflow_triggers(workflow_text)
        gate = workflow_text.split("release-gate:", 1)[1]
        assert "refs/tags/" in gate
        assert "tags" in triggers.get("push", {}), (
            "release gate достижим только вручную — тег не сработает"
        )

    def test_manual_dispatch_available(self, workflow_text):
        assert "workflow_dispatch" in parse_workflow_triggers(workflow_text)

    def test_trigger_parser_ignores_comments(self):
        """Гард на сам парсер: закомментированный tags не считается заданным."""
        commented = 'on:\n  push:\n    branches: ["**"]\n    # tags: ["**"]\njobs:\n'
        declared = 'on:\n  push:\n    branches: ["**"]\n    tags: ["**"]\njobs:\n'
        assert "tags" not in parse_workflow_triggers(commented)["push"]
        assert "tags" in parse_workflow_triggers(declared)["push"]

    def test_trigger_parser_stops_at_next_top_level_key(self):
        """Блок `on:` не должен захватывать ключи следующих секций."""
        text = 'on:\n  push:\n    tags: ["**"]\nconcurrency:\n  group: x\n'
        triggers = parse_workflow_triggers(text)
        assert set(triggers) == {"push"}


# ===========================================================================
# Генератор: защита от фиксации непротестированного состава
# ===========================================================================

class TestGeneratorGuards:
    @pytest.fixture(scope="class")
    def generator(self):
        return load_module(GENERATOR_PATH, "bybit_gen_dependency_artifacts")

    def test_rejects_resolution_differing_from_environment(self, generator):
        """Главная защита: pip разрешил не ту версию, что установлена."""
        pins = {"typing-inspection": "0.4.2"}
        resolved = {
            "typing-inspection": {
                "version": "0.4.3", "sha256": "a" * 64,
                "filename": "x.whl", "url": "https://example.invalid/x.whl",
            }
        }
        with pytest.raises(generator.GeneratorError, match="не совпал"):
            generator.assert_matches_environment(pins, resolved)

    def test_rejects_package_added_by_resolver(self, generator):
        with pytest.raises(generator.GeneratorError, match="pip добавил пакет"):
            generator.assert_matches_environment(
                {},
                {"ghost": {"version": "1.0.0", "sha256": "a" * 64,
                           "filename": "g.whl", "url": ""}},
            )

    def test_rejects_package_not_returned_by_resolver(self, generator):
        with pytest.raises(generator.GeneratorError, match="не вернул"):
            generator.assert_matches_environment({"pydantic": "2.11.1"}, {})

    def test_accepts_exact_match(self, generator):
        generator.assert_matches_environment(
            {"pydantic": "2.11.1"},
            {"pydantic": {"version": "2.11.1", "sha256": "a" * 64,
                          "filename": "p.whl", "url": ""}},
        )

    def test_requirements_in_must_be_exactly_pinned(self, generator):
        """Открытая граница в requirements.in ломает воспроизводимость."""
        direct = generator.direct_requirements()
        assert direct, "requirements.in не содержит зависимостей"
        for name, version in direct.items():
            assert re.fullmatch(r"[0-9][0-9A-Za-z.\-+]*", version), (name, version)

    def test_normalize_follows_pep503(self, generator):
        assert generator.normalize("Typing_Extensions") == "typing-extensions"
        assert generator.normalize("pydantic.core") == "pydantic-core"

    def test_check_mode_detects_stale_lock(self, generator, tmp_path):
        """Проверка существования файла не является проверкой актуальности.

        Устаревший lock существует, но фиксирует состав, на котором тесты
        не проходили.
        """
        lock = tmp_path / "requirements.lock"
        sbom = tmp_path / "sbom.cyclonedx.json"
        fresh = "# Сгенерирован: 2026-01-01T00:00:00+00:00\npytest==8.3.5 \\\n"
        lock.write_text(fresh.replace("8.3.5", "8.3.4"), encoding="utf-8")
        sbom.write_text(json.dumps({"serialNumber": "urn:uuid:x",
                                    "metadata": {"timestamp": "t"}}),
                        encoding="utf-8")
        problems = generator.compare_artifacts(
            lock_path=lock, sbom_path=sbom, lock_text=fresh,
            sbom={"serialNumber": "urn:uuid:y", "metadata": {"timestamp": "u"}},
        )
        assert any("УСТАРЕЛ" in p for p in problems), problems

    def test_check_mode_detects_stale_sbom(self, generator, tmp_path):
        lock = tmp_path / "requirements.lock"
        sbom = tmp_path / "sbom.cyclonedx.json"
        text = "pytest==8.3.5 \\\n"
        lock.write_text(text, encoding="utf-8")
        sbom.write_text(json.dumps({"components": [{"name": "pytest"}]}),
                        encoding="utf-8")
        problems = generator.compare_artifacts(
            lock_path=lock, sbom_path=sbom, lock_text=text,
            sbom={"components": [{"name": "pytest"}, {"name": "ghost"}]},
        )
        assert any("УСТАРЕЛ" in p and "sbom" in p for p in problems), problems

    def test_check_mode_accepts_matching_artifacts(self, generator, tmp_path):
        lock = tmp_path / "requirements.lock"
        sbom = tmp_path / "sbom.cyclonedx.json"
        text = "# Сгенерирован: 2026-01-01T00:00:00+00:00\npytest==8.3.5 \\\n"
        payload = {"serialNumber": "urn:uuid:a", "metadata": {"timestamp": "t"},
                   "components": [{"name": "pytest"}]}
        lock.write_text(text, encoding="utf-8")
        sbom.write_text(json.dumps(payload), encoding="utf-8")
        assert generator.compare_artifacts(
            lock_path=lock, sbom_path=sbom, lock_text=text, sbom=payload
        ) == []

    def test_check_mode_reports_missing_artifacts(self, generator, tmp_path):
        problems = generator.compare_artifacts(
            lock_path=tmp_path / "absent.lock",
            sbom_path=tmp_path / "absent.json",
            lock_text="pytest==8.3.5\n", sbom={},
        )
        assert len(problems) == 2
        assert all("отсутствует" in p for p in problems), problems

    def test_check_mode_reports_corrupt_sbom(self, generator, tmp_path):
        lock = tmp_path / "requirements.lock"
        sbom = tmp_path / "sbom.cyclonedx.json"
        lock.write_text("pytest==8.3.5\n", encoding="utf-8")
        sbom.write_text("{ not json", encoding="utf-8")
        problems = generator.compare_artifacts(
            lock_path=lock, sbom_path=sbom,
            lock_text="pytest==8.3.5\n", sbom={},
        )
        assert any("повреждённый JSON" in p for p in problems), problems

    def test_fingerprint_ignores_generation_timestamp(self, generator):
        """Иначе любой повторный запуск давал бы ложное расхождение."""
        a = "# Сгенерирован:      2026-01-01T00:00:00+00:00\npytest==8.3.5\n"
        b = "# Сгенерирован:      2026-08-10T17:00:00+00:00\npytest==8.3.5\n"
        assert generator.lock_fingerprint(a) == generator.lock_fingerprint(b)

    def test_fingerprint_keeps_role_and_platform(self, generator):
        """Роль и платформа — часть смысла артефакта, а не шум."""
        a = "# РОЛЬ:      development\npytest==8.3.5\n"
        b = "# РОЛЬ:      production\npytest==8.3.5\n"
        assert generator.lock_fingerprint(a) != generator.lock_fingerprint(b)

    def test_sbom_fingerprint_ignores_serial_and_timestamp(self, generator):
        base = {"components": [{"name": "pytest"}]}
        a = {**base, "serialNumber": "urn:uuid:1", "metadata": {"timestamp": "t1"}}
        b = {**base, "serialNumber": "urn:uuid:2", "metadata": {"timestamp": "t2"}}
        assert generator.sbom_fingerprint(a) == generator.sbom_fingerprint(b)

    def test_sbom_fingerprint_keeps_components(self, generator):
        a = {"serialNumber": "u", "metadata": {"timestamp": "t"},
             "components": [{"name": "pytest", "version": "8.3.5"}]}
        b = {"serialNumber": "u", "metadata": {"timestamp": "t"},
             "components": [{"name": "pytest", "version": "8.3.4"}]}
        assert generator.sbom_fingerprint(a) != generator.sbom_fingerprint(b)

    def test_detects_platform_specific_wheel(self, generator):
        resolved = {
            "pure": {"version": "1.0", "sha256": "a" * 64,
                     "filename": "pure-1.0-py3-none-any.whl", "url": ""},
            "binary": {"version": "1.0", "sha256": "b" * 64,
                       "filename": "binary-1.0-cp313-cp313-macosx_11_0_arm64.whl",
                       "url": ""},
        }
        found = generator.has_platform_specific_wheel(resolved)
        assert len(found) == 1 and "binary" in found[0]


# ===========================================================================
# Гигиена suite: каждый тест размечен маркером
# ===========================================================================

class TestSuiteHygiene:
    def test_every_test_module_declares_pytestmark(self) -> None:
        """Механическая проверка вместо интерпретации exit 5 shell-команды.

        Контракт: модуль `tests/**/test_*.py` обязан объявлять `pytestmark`.
        Без этого `-m contract` молча пропустит тесты, а мы узнаем об этом
        только через shell exit code — что не является проверкой, а является
        интерпретацией поведения pytest. Этот тест проверяет требование
        механически.
        """
        import ast
        from pathlib import Path

        root = Path(__file__).parent.parent
        missing = []

        for path in root.rglob("test_*.py"):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            has_marker = any(
                isinstance(node, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "pytestmark"
                    for t in node.targets
                )
                for node in tree.body
            )
            if not has_marker:
                missing.append(path.relative_to(root))

        assert not missing, (
            f"модули без pytestmark (игнорируются `-m contract/fault/property`): "
            f"{', '.join(str(p) for p in missing)}"
        )
