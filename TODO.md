# TODO — Backlog

- Обновлён: 2026-08-10T18:20:00+0700
- Stage: 1 (в работе)

---

## Правила

- Одновременно ровно одна задача имеет статус `IN_PROGRESS`.
- `DONE` — только после всех acceptance criteria.
- Обнаруженная работа сначала получает ID, затем выполняется.
- Не расширять текущую задачу новым scope.
- Завершённые задачи не удаляются.

---

## Stage 0 — Greenfield bootstrap и design lock

### P0-S0-001 | P0 | Stage 0 | DONE

**Тема:** Проверить входные документы и создать greenfield-репозиторий

**Owner:** Claude Code  
**Зависимости:** нет  
**Scope:**
- Найти и хешировать все 6 нормативных документов
- Подтвердить непустой целевой каталог с пользователем
- `git init -b main` в `/Users/vs/Desktop/bybit-chart`
- Создать `.gitignore` по стеку roadmap
- Скопировать спецификации в `docs/specifications/source/`
- Создать `docs/specifications/SOURCE_MANIFEST.md`
- Верифицировать SHA-256 исходников и копий

**Do-not-touch:** existing spec files, `.claude/`, `.DS_Store`

**Acceptance criteria:**
- [x] Все 6 документов найдены и хешированы
- [x] SHA-256 исходника = SHA-256 копии для всех файлов
- [x] `git init -b main` выполнен успешно
- [x] `.gitignore` создан по стеку (Python, Node, secrets, data, macOS)
- [x] `docs/specifications/source/` содержит 6 файлов
- [x] `SOURCE_MANIFEST.md` создан с хешами и mtime

**Evidence:** `git status`, `shasum -a 256` audit

---

### P0-S0-002 | P0 | Stage 0 | DONE

**Тема:** Создать архитектурный baseline и трассировку требований

**Owner:** Claude Code  
**Зависимости:** P0-S0-001  
**Scope:**
- `docs/architecture/CURRENT.md` — только `NO IMPLEMENTATION`
- `docs/architecture/TARGET.md` — целевая архитектура по roadmap
- `docs/architecture/DECISIONS_PENDING.md` — конфликты и открытые ADR
- `docs/adr/README.md` — правила ADR без выдуманных решений
- `docs/REQUIREMENTS_TRACEABILITY.md` — 63 требования из roadmap

**Do-not-touch:** spec source files

**Acceptance criteria:**
- [x] CURRENT.md честно сообщает `GREENFIELD / NO IMPLEMENTATION`
- [x] TARGET.md основан только на нормативных документах
- [x] Конфликты CONFLICT-001…005 зафиксированы с evidence
- [x] ADR-001…011 зафиксированы как OPEN
- [x] 63 требования с ID, разделом, компонентом, acceptance и stage

**Evidence:** просмотр файлов

---

### P0-S0-003 | P0 | Stage 0 | DONE

**Тема:** Создать структуру каталогов и файлы журнала

**Owner:** Claude Code  
**Зависимости:** P0-S0-001  
**Scope:**
- Создать каталоги по §3.5 Roadmap
- Создать `NEXT.md`, `TODO.md`, `README.md`

**Do-not-touch:** spec source files

**Acceptance criteria:**
- [x] Все каталоги из §3.5 существуют
- [x] Каждый каталог содержит `.gitkeep`
- [x] `NEXT.md` заполнен и содержит action log, проверки и handoff
- [x] `TODO.md` заполнен, все задачи S0 имеют ID
- [x] `README.md` честно сообщает NO IMPLEMENTATION

**Evidence:** `find . -type d` audit

---

### P0-S0-004 | P0 | Stage 0 | DONE

**Тема:** Выполнить проверки Stage 0 и подготовить review gate

**Owner:** Claude Code  
**Зависимости:** P0-S0-001, P0-S0-002, P0-S0-003  
**Scope:**
- Проверить дерево файлов
- Проверить SHA-256 копий
- Проверить отсутствие пустых нормативных файлов
- Проверить отсутствие заявлений о реализованных функциях
- Проверить согласованность ссылок между README / NEXT / TODO / architecture docs
- `git status --short`
- Проверить отсутствие remote
- Проверить отсутствие ключей, секретов, production data
- Синхронизировать NEXT.md с результатами

**Do-not-touch:** spec source files; никаких commits до подтверждения пользователя

**Acceptance criteria:**
- [x] `git status --short` показывает только новые неотслеживаемые файлы
- [x] Нет git remote
- [x] Нет API-ключей, паролей, production data
- [x] Все нормативные файлы ненулевые
- [x] Ни один файл не заявляет о реализованных функциях
- [x] NEXT.md, TODO.md, README.md согласованы по Stage, версии, дате
- [x] SHA-256 повторно проверены

**Evidence:** точные команды и вывод в NEXT.md; commit `6edc666`

**Примечание:** статус оставался `IN_PROGRESS` из-за несинхронизированного файла — фактически задача закрыта 2026-08-10T02:42 вместе с первым commit. Исправлено 2026-08-10 при закрытии P1-S1-003.

---

## Stage 1 — Shared schemas и storage core (IN_PROGRESS)

Закрыто: P1-S1-001, P1-S1-002, P1-S1-003. Открыто: P1-S1-004 (блок ADR-004, OPEN-005), P1-S1-005, P1-S1-006 (блок OPEN-005), P1-S1-007.

### P1-S1-001 | P0 | Stage 1 | DONE

**Тема:** Реализовать package `contracts`: Protobuf/Pydantic schemas, integer/Decimal model

**Owner:** не назначен  
**Зависимости:** утверждены ADR-001, ADR-002, ADR-004  
**Scope:** (только первая атомарная задача Stage 1, согласно промту)
- Создать `contracts/` с Pydantic-моделями `RawTrade`, `RawBookEvent`, `RawLiquidation`, `RawEventEnvelope`, `GapMarker`
- Реализовать integer/Decimal модель в `packages/numeric`
- Schema compatibility tests

**Do-not-touch:** до подтверждения commit Stage 0 не начинать

**Acceptance criteria:**
- Round-trip test: int64/Decimal → JSON → int64/Decimal без потери точности
- Все поля `RawEventEnvelope` из §5.2 Roadmap присутствуют
- `tradeTurnoverQuote` отсутствует как хранимое поле (только вычисляемое)
- Backward-compatibility fixture
- Нет `float` в persistent schemas

**Evidence:** `pytest tests/contracts/test_contracts_and_numeric.py` → 55 passed

---

### P1-S1-002 | P0 | Stage 1 | DONE

**Тема:** `packages/storage`: WAL, offsets, state machine сегментов, atomic commit, manifest

**Owner:** Claude Code
**Зависимости:** P1-S1-001
**Scope:**
- `offsets.py` — accepted/durable/closed/published/consumer + инварианты (§6.2)
- `frames.py` — формат фрейма length+CRC32, torn/corrupt detection (§6.2)
- `wal.py` — append, bounded group commit, recovery, read_range (§5.1, §6.2)
- `segment_state.py` — ACTIVE→CLOSED_PENDING→PUBLISHING→COMMITTED→FAILED, lease, quarantine (§6.3)
- `manifest.py` — atomic replace, published_offset, партиционирование (§6.4, §6.5)
- `atomic_commit.py` — tmp→validate→fsync→rename→fsync(dir)→manifest→checkpoint (§6.4)

**Do-not-touch:** source specs; удаление сегментов не реализуется в этой задаче

**Acceptance criteria:**
- [x] Инварианты offsets: durable≤accepted, closed≤durable, published≤closed
- [x] live publish ceiling = durableOffset (speculative tail запрещён)
- [x] torn frame отбрасывается до последнего валидного boundary
- [x] durable_violation репортится как incident
- [x] crash-matrix: 4 точки аварии не публикуют историю и не двигают checkpoint
- [x] orphan после rename не усыновляется автоматически
- [x] lease: только holder коммитит; просроченный не перезахватывает старым generation
- [x] quarantine: corrupt/incomplete/legacy/schemaMismatch — разные состояния
- [x] удаление только COMMITTED + retention_ok
- [x] gap в манифесте останавливает published_offset
- [x] duplicate replay не удваивает записи

**Evidence:** `pytest -q` → 156 passed (55 contracts+numeric, 30 offsets+frames, 34 segment+manifest, 16 crash-matrix, 21 WAL recovery)

---

### P1-S1-003 | P0 | Stage 1 | DONE

**Тема:** Dependency lock и SBOM

**Owner:** Claude Code
**Зависимости:** P1-S1-001
**Scope:** Roadmap §4 требует фиксацию всех зависимостей lock-файлом и SBOM. Сейчас в `pyproject.toml` версии не залочены, lock-файла нет.

**Acceptance criteria:**
- [x] Lock-файл с точными версиями и хешами — `deploy/dependencies/darwin-arm64/requirements.lock`, 9 пакетов, SHA-256 у каждого
- [x] SBOM в согласованном формате — CycloneDX 1.5, purl, лицензии, граф связей
- [x] CI-конфигурация статически проверяет цепочку install-from-lock → verifier: `.github/workflows/ci.yml` ставит окружение из lock и только затем вызывает верификатор; порядок, триггеры и достижимость release gate закреплены тестами разобранной конфигурации

Фактический первый CI run в объём этой задачи не входит — он вынесен в P1-S1-007 как отдельный незакрытый criterion (разделение утверждено тимлидом 2026-08-10). Критерий здесь закрыт статической проверкой конфигурации, а не её исполнением.
- [x] Артефакт не скрыт `.gitignore` (дефект: шаблон `*.lock`)
- [x] Роль и платформа объявлены в шапке; production-роль недоступна на Darwin (ADR-012)
- [x] `--check` обнаруживает устаревший lock/SBOM, а не только отсутствие файлов
- [x] Тесты запускаются тем же интерпретатором (`sys.executable`), а не `python3` из PATH
- [x] Release gate ставит окружение из lock до проверки — иначе остался бы красным навсегда

**Принято как development-lock** (решение владельца 2026-08-10). Роль `development`, платформа `darwin-arm64`. Не является release artifact. Production-набор — P1-S1-006.

**Ревью тимлида 2026-08-10T17:50:** NO-GO на commit, 6 несоответствий. Все исправлены:

| № | Несоответствие | Исправление |
|---|---|---|
| 1 | `1 failed` без активации venv: тест запускал системный `python3` | `sys.executable` в `TestReleaseGateBehaviour._run` |
| 2 | `--check` проверял только наличие файлов | `compare_artifacts` сравнивает состав; волатильные поля (время, serialNumber) исключены |
| 3 | Release gate не ставил окружение из lock | `pip install --require-hashes` до верификатора; закреплено тестом |
| 4 | Ложное утверждение о закоммиченном CI | NEXT.md: workflow untracked и не запускался; прогон → P1-S1-007 |
| 5 | Trailing whitespace | Убран в NEXT.md, REQUIREMENTS_TRACEABILITY.md, ADR-012; шапки переведены в списки |
| 6 | Счёт тестов 79 против 91 | Журнал исправлен |

Побочно найден дефект при написании тестов на п.2: `relative_to(REPO_ROOT)` падал с `ValueError` на пути вне репозитория. Введён `display_path` в оба скрипта.

**Evidence:** `.venv/bin/python -m pytest -q` → 258 passed (без активации venv); `deploy/verify_dependencies.py` → exit 0; `--release` → exit 1; `gen_dependency_artifacts.py --check` → exit 0, на подложенном `pytest==8.3.4` → exit 1; `git diff --check` → чисто

---

### P1-S1-004 | P0 | Stage 1 | TODO

**Тема:** Parquet writer/validator поверх `atomic_commit`

**Owner:** не назначен
**Зависимости:** P1-S1-002, ADR-004 (Decimal128 precision/scale)
**Scope:** Реальный PyArrow writer и footer-валидатор через существующий контракт `SegmentWriter` / `validator`. Сейчас формат файла не зафиксирован намеренно — PyArrow не является зависимостью Stage 1.

**Acceptance criteria:**
- Arrow schema для RawTrade/RawBookEvent/RawLiquidation с Decimal128
- Валидация footer/schemaVersion/rowCount реального Parquet
- `iter_batches` вместо `to_pylist()` (§6.4 запрещает полный to_pylist в live-процессе)
- Crash-matrix проходит с реальным writer

**Evidence:** —

---

### P1-S1-005 | P1 | Stage 1 | TODO

**Тема:** Property-based тесты на Hypothesis

**Owner:** не назначен
**Зависимости:** P1-S1-002
**Scope:** Roadmap §4 фиксирует pytest + Hypothesis. Сейчас Hypothesis не установлен, тесты только example-based.

**Acceptance criteria:**
- Property: любой набор payload → encode/scan round-trip без потерь
- Property: произвольная точка обрезки файла → recovery не даёт валидных данных за boundary
- Property: последовательность advance_* сохраняет инварианты offsets

**Evidence:** —

---

### P1-S1-006 | P0 | Stage 1 | BLOCKED

**Тема:** Linux dependency artifacts (production release artifact)

**Owner:** не назначен
**Зависимости:** P1-S1-003, OPEN-005 (архитектура production-хоста и точная версия Python)
**Блокирует:** production release. Разработку на macOS не блокирует (ADR-012).

**Scope:** Снять `deploy/dependencies/linux-<arch>/{requirements.lock,sbom.cyclonedx.json}` с ролью `production` в чистом Linux-окружении утверждённой архитектуры и версии Python. Инструменты готовы: генератор поддерживает `--role production`, верификатор — `--release`, CI-джоб `release-gate` подключён.

**Do-not-touch:** `deploy/dependencies/darwin-arm64/**` — macOS-lock не правится под Linux ни при каких условиях.

**Acceptance criteria:**
- OPEN-005 закрыт: архитектура и точная версия Python утверждены
- Linux-окружение поставлено по `requirements.in`, `pytest -q` зелёный на Linux
- `tests/fault` зелёные на Linux (WAL, fsync, atomic rename, crash recovery)
- Артефакты сняты генератором с `--role production`, не отредактированы вручную
- `verify_dependencies.py --release` → exit 0
- CI-джоб `linux-tests` переключился на `pip install --require-hashes`
- Тест `test_linux_lock_absent_so_production_release_is_blocked` снят или переписан

**Evidence:** —

---

### P1-S1-007 | P0 | Stage 1+ | TODO

**Тема:** Linux parity для платформенно-зависимых гарантий

**Owner:** не назначен
**Зависимости:** ADR-012
**Scope:** По ADR-012 зелёные тесты на macOS не являются свидетельством для production. Обязательный повтор на Linux: WAL, `fsync`, `fsync` каталога, atomic `rename`, crash recovery, `systemd`-контур, performance и soak. Часть закрыта: `linux-tests` в CI прогоняет `pytest -q` и `tests/fault` на ubuntu-24.04.

**Acceptance criteria:**
- [ ] **Первый реальный прогон CI на runner** (перенесено из P1-S1-003 решением тимлида 2026-08-10; сейчас workflow не запускался ни разу, требуется remote)
- [ ] `pytest -q` и `tests/fault` фактически зелёные на Linux — не только описаны в workflow
- [ ] Crash-matrix проверена на ext4/XFS с реальным `SIGKILL`, а не только на APFS
- [ ] `systemd` unit, health probe и graceful shutdown deadline проверены на Linux (§3, §20.1)
- [ ] Performance baseline снят на Linux (§19 Этап 1: baseline CPU/RAM/disk/lag)
- [ ] 72h soak на Linux (§18.4 hard gates)

**Evidence:** — (только конфигурация `.github/workflows/ci.yml`; ни один прогон не выполнялся)

---
