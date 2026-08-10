# Bybit Order Flow Platform

**Статус:** `GREENFIELD / NO IMPLEMENTATION`  
**Stage:** 0 — Greenfield bootstrap и design lock  
**Дата создания:** 2026-08-10

---

## ⚠️ ВАЖНО

Этот репозиторий создаётся с нуля. В нём **нет** рабочего кода, запускаемых сервисов или production-данных.

Отсутствует:
- работающий collector, API, UI, trading engine и AI;
- любые подключения к Bybit;
- production-хранилище и API-ключи.

---

## Назначение проекта

Серверная 24/7-платформа на одном хосте для:

1. Сбора невосполнимых публичных данных Bybit (BTCUSDT, ETHUSDT, XRPUSDT).
2. Lossless-хранения и воспроизводимого построения Order Flow-модулей.
3. Раздачи истории и live-данных браузеру без потерь.
4. Ручного анализа, разметки и Pine-compatible индикаторов.
5. Детерминированного replay и event-driven backtest.
6. Ручной и автоматической торговли через единый Risk Engine.
7. AI-ассистента (read-only, без доступа к API-ключам).

---

## Целевая многопроцессная архитектура

Источник: `docs/specifications/source/BYBIT_MULTIPROCESS_PLATFORM_ROADMAP.md` §3.

```
market-collector     → WAL / Parquet (raw)
orderflow-worker     ← WAL | derives Order Flow modules
api-gateway          ← derived state | serves browser
maintenance-worker   ← WAL/Parquet | compaction/tiles/retention
execution-risk       ↔ Bybit private | intent ledger | risk
strategy-worker      → OrderIntentProposal (без доступа к Bybit)
research jobs        ← raw/derived (read-only) | backtest/optimizer/ML
```

Подробная схема: `docs/architecture/TARGET.md`.

---

## Структура репозитория

```
contracts/              Protobuf/Pydantic схемы и compatibility fixtures
services/
  market_collector/     Bybit public adapters, WAL, SourceQuality
  orderflow_worker/     aggregators, features, events, checkpoints
  api_gateway/          REST/WS, auth, workspaces, browser streams
  maintenance_worker/   publication, compaction, retention, manifest
  execution_risk/       private adapter, ledger, risk, reconciliation
  strategy_worker/      deterministic strategies and signals
packages/
  numeric/              tick/qty/Decimal primitives
  storage/              WAL/Parquet/manifest readers and contracts
  orderflow/            pure reusable algorithms
  execution_domain/     state machine and adapter interfaces
  simulator/            clocks, fills, reports
web/                    React/TypeScript application
research/               dataset builders, optimizer, ML jobs
deploy/                 systemd units, release/canary/rollback scripts
tests/
  fixtures/ contracts/ replay/ fault/ performance/ browser/ demo/
docs/
  specifications/source/   неизменяемые копии входных документов
  architecture/            CURRENT.md, TARGET.md, DECISIONS_PENDING.md
  adr/                     Architecture Decision Records
  REQUIREMENTS_TRACEABILITY.md
```

---

## Нормативные документы

Все source artifacts хранятся в `docs/specifications/source/` и не изменяются.

| Документ | Приоритет |
|---|---|
| `BYBIT_MULTIPROCESS_PLATFORM_ROADMAP.md` | P1 — главный |
| `multi-process-architecture.md` | P2 |
| `all-modules-data-persistence-architecture.md` | P3 |
| `all-modules-data-persistence-architecture-changes.md` | P4 |
| `Bybit_Order_Flow_Heatmap_Specification.docx` | P5 |
| `BTCUSDT_Bybit_Intraday_Strategies.md` | P6 |

Хеши и mtime: `docs/specifications/SOURCE_MANIFEST.md`.

---

## Файлы журнала

| Файл | Назначение |
|---|---|
| `NEXT.md` | Оперативное состояние и точка продолжения |
| `TODO.md` | Единый backlog с acceptance criteria |
| `README.md` | Стабильное описание фактически реализованного |

Правила обновления: `NEXT.md` содержит action log и handoff. `TODO.md` — единственный источник статуса задач. `README.md` обновляется только при фактической реализации новых компонентов.

---

## Data Safety

- Production-данные и API-ключи **никогда** не помещаются в репозиторий.
- `.gitignore` исключает `*.wal`, `*.parquet`, `data/`, `secrets/`, `*.key`.
- Тесты используют только fixtures и synthetic data — никаких реальных ключей или production WS.

---

## Текущий этап реализации

**Stage 1 — Shared schemas и storage core** (в работе)

Stage 0 завершён: структура репозитория, source artifacts, архитектурный baseline, трассировка 63 требований, реестр 11 открытых ADR.

Реализовано в Stage 1:

| Модуль | Что есть |
|---|---|
| `packages/numeric` | PriceTicks/QtySteps/Decimal128; binary float запрещён в persistent данных |
| `contracts` | RawTrade, RawBookEvent, RawRpiBookEvent, BookCheckpoint, RawLiquidation, GapMarker, RawEventEnvelope |
| `packages/storage` | WAL с group commit и torn-frame recovery, offsets и их инварианты, state machine сегментов с lease/fencing, manifest, atomic commit protocol |

**Не реализовано:** ни один из шести сервисов (`services/*` пусты), Parquet writer, PostgreSQL, frontend, simulator, execution, стратегии, AI. Подключений к Bybit нет.

---

## Запуск тестов

```bash
source .venv/bin/activate
python3 -m pytest -q
```

Текущий результат: **156 passed, 0 failed, 0 skipped**.

Только backend unit/contract/fault тесты. Frontend (Vitest/Playwright), integration, soak, performance и demo/testnet тесты появятся на соответствующих этапах.

---

## Известные ограничения и открытые решения

1. ADR-001…011 открыты — требуется утверждение тимлидом.
2. Нет lock-файла и SBOM — нарушение Roadmap §4, задача P1-S1-003.
3. Формат файла сегмента не зафиксирован: `atomic_commit` принимает writer как callback, реальный Parquet writer — задача P1-S1-004 (блокируется ADR-004).
4. Property-тесты (Hypothesis) не написаны — задача P1-S1-005.
5. Целевой хост (macOS vs Linux) не подтверждён — CONFLICT-004.
6. Bybit client library не выбрана — OPEN-001.
7. Full Orderbook: DEFERRED — availability mainnet не проверена.
8. Все BTC-absolute thresholds — `UNCALIBRATED` до замеров.

Подробно: `docs/architecture/DECISIONS_PENDING.md`.
