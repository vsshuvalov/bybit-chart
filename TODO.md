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

### P1-S1-001 | P0 | Stage 1 | TODO

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

**Evidence:** `pytest contracts/ packages/numeric/`

---
