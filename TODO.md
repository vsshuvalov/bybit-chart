# TODO — Backlog

Обновлён: 2026-08-10T02:30:00+0700

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

### P0-S0-004 | P0 | Stage 0 | IN_PROGRESS

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
- [ ] `git status --short` показывает только новые неотслеживаемые файлы
- [ ] Нет git remote
- [ ] Нет API-ключей, паролей, production data
- [ ] Все нормативные файлы ненулевые
- [ ] Ни один файл не заявляет о реализованных функциях
- [ ] NEXT.md, TODO.md, README.md согласованы по Stage, версии, дате
- [ ] SHA-256 повторно проверены

**Evidence:** точные команды и вывод в NEXT.md

---

## Stage 1 — Shared schemas и storage core (NOT_STARTED)

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

### P1-S1-003 | P0 | Stage 1 | TODO

**Тема:** Dependency lock и SBOM

**Owner:** не назначен
**Зависимости:** P1-S1-001
**Scope:** Roadmap §4 требует фиксацию всех зависимостей lock-файлом и SBOM. Сейчас в `pyproject.toml` версии не залочены, lock-файла нет.

**Acceptance criteria:**
- Lock-файл с точными версиями и хешами
- SBOM в согласованном формате
- CI проверяет соответствие lock-файла окружению

**Evidence:** —

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
