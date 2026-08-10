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

**Stage 0 — Greenfield bootstrap и design lock**

Что создано:
- структура репозитория;
- нормативные документы (source artifacts);
- архитектурный baseline (`TARGET.md`, `DECISIONS_PENDING.md`);
- трассировка требований (63 REQ);
- ADR реестр (11 открытых ADR);
- журналы `NEXT.md`, `TODO.md`, `README.md`.

Что не создано: никакого рабочего кода. Первый commit ожидает подтверждения.

---

## Запуск тестов

Test harness появится в Stage 1. До этого команды запуска не публикуются — здесь нечего запускать.

---

## Известные ограничения и открытые решения

1. ADR-001…011 открыты — требуется утверждение тимлидом до начала реализации.
2. Целевой хост (macOS vs Linux) не подтверждён — CONFLICT-004.
3. Bybit client library не выбрана — OPEN-001.
4. Full Orderbook: DEFERRED — availability mainnet не проверена.
5. Все BTC-absolute thresholds в конфигурациях — `UNCALIBRATED` до замеров.

Подробно: `docs/architecture/DECISIONS_PENDING.md`.
