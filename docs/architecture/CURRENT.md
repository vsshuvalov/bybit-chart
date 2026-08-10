# Текущее состояние архитектуры

- **Версия:** Stage 1 (в работе)
- **Дата:** 2026-08-10
- **Статус:** `LIBRARY CODE ONLY / NO RUNNING SERVICE`

Библиотечный код есть и покрыт тестами. Ни один долгоживущий процесс не
реализован и не запускался, подключений к Bybit нет.

---

## Фактически реализовано

| Компонент | Каталог | Содержание |
|---|---|---|
| Числовая модель | `packages/numeric` | PriceTicks/QtySteps/Decimal128; binary float запрещён в persistent данных (§6.6) |
| Схемы событий | `contracts` | RawTrade, RawBookEvent, RawRpiBookEvent, BookCheckpoint, RawLiquidation, GapMarker, RawEventEnvelope (§5.2) |
| Storage core | `packages/storage` | WAL с bounded group commit и torn-frame recovery; offsets и их инварианты; state machine сегментов с lease/fencing; manifest; atomic commit protocol (§6.2–6.5) |
| Dependency-контур | `deploy` | lock и CycloneDX SBOM по платформам, генератор, offline-верификатор, release gate (§4, §20.1) |
| CI-конфигурация | `.github/workflows` | описаны Linux parity, macOS dev-контур, dependency gate, release gate |

Документация: `CURRENT.md`, `TARGET.md`, `DECISIONS_PENDING.md`,
`docs/adr/README.md`, ADR-012, `REQUIREMENTS_TRACEABILITY.md` (67 требований).

Тесты: 264 passed на macOS / Darwin arm64 / CPython 3.13.7. Только backend
unit/contract/fault.

## Что отсутствует

- `market-collector` — не реализован;
- `orderflow-worker` — не реализован;
- `api-gateway` — не реализован;
- `maintenance-worker` — не реализован;
- `execution-risk` — не реализован;
- `strategy-worker` — не реализован;
- Parquet writer поверх `atomic_commit` — не реализован (формат файла сегмента
  намеренно не зафиксирован, writer передаётся callback'ом);
- PostgreSQL-схема и миграции — не реализованы;
- Frontend (React/TypeScript) — не реализован;
- Pine-compatible runtime — не реализован;
- Simulator/replay — не реализован;
- AI-ассистент — не реализован;
- Production-подключения, API-ключи, торговые операции — **не
  инициализированы и не запускались**.

## Ограничения проверенного

- Storage core проверен **только на macOS/APFS**. Гарантии `fsync`,
  `fsync` каталога и атомарности `rename` на ext4/XFS замером не
  подтверждены — production-хост Linux (ADR-012), объём переноса в
  P1-S1-007.
- **CI ни разу не выполнялся**: remote отсутствует. Проверены синтаксис
  workflow и его контракт тестами разобранной конфигурации, но не
  исполнение на runner.
- Dependency artifacts сняты только для `darwin-arm64` с ролью
  `development`. Production-набор для Linux отсутствует — release
  заблокирован (P1-S1-006, блокируется OPEN-005).
- Property-тесты (Hypothesis) не написаны — P1-S1-005.

## Git-статус

Репозиторий инициализирован `git init -b main`. Commits:

```
6edc666  Stage 0: greenfield bootstrap and design lock
ea25af6  Stage 1 / P1-S1-001: contracts и packages/numeric
c6e0d83  Sync NEXT.md: Stage 1 / P1-S1-001 DONE
d479e04  Stage 1 / P1-S1-002: storage core (WAL, offsets, atomic commit, manifest)
```

Нет remote, нет тегов, нет веток кроме `main`.
