# Bybit Order Flow Platform

- **Статус:** `STAGE 1 IN PROGRESS` — реализованы схемы, storage core и dependency-контур; ни один сервис не работает
- **Stage:** 1 — Shared schemas и storage core
- **Дата создания:** 2026-08-10
- **Обновлён:** 2026-08-10

---

## ⚠️ ВАЖНО

В репозитории есть библиотечный код (схемы событий, числовая модель, storage core, dependency-контур), но **нет ни одного запускаемого сервиса и ни одного подключения к Bybit**.

Отсутствует:
- работающий collector, API, UI, trading engine и AI — `services/*` пусты;
- любые подключения к Bybit, API-ключи, production-хранилище;
- Parquet writer, PostgreSQL, frontend, simulator, стратегии.

Есть и покрыто тестами: `contracts/`, `packages/numeric`, `packages/storage`, `deploy/` (lock, SBOM, верификатор). Запуск: `.venv/bin/python -m pytest -q`.

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
| `deploy/` | dependency lock и CycloneDX SBOM по платформам, генератор и offline-верификатор, release gate |
| `.github/workflows` | CI-конфигурация: тесты на Linux и macOS, dependency gate, release gate. Ни разу не запускалась — remote отсутствует (P1-S1-007) |

**Не реализовано:** ни один из шести сервисов (`services/*` пусты), Parquet writer, PostgreSQL, frontend, simulator, execution, стратегии, AI. Подключений к Bybit нет.

---

## Платформы

Источник: `docs/adr/ADR-012-development-and-production-hosts.md` (закрывает CONFLICT-004).

| Роль | Платформа | Статус |
|---|---|---|
| Development host | macOS / Darwin arm64 | DECIDED |
| Production host | Linux + `systemd` | DECIDED |
| Production architecture (x86_64 / arm64) | — | OPEN-005 |
| Production Python version | — | OPEN-005 |

Dependency artifacts раскладываются по платформам, у каждого объявлена роль:

```
deploy/dependencies/darwin-arm64/    РОЛЬ development   ← снят
deploy/dependencies/linux-<arch>/    РОЛЬ production    ← НЕ снят (P1-S1-006)
```

macOS-lock не является Linux release artifact: генератор не выпускает
`--role production` на Darwin, а `verify_dependencies.py --release`
отвергает роль `development`. Правила и команды —
`deploy/dependencies/README.md`.

Платформенно-зависимые гарантии storage core (`fsync`, atomic `rename`,
crash recovery) повторяются на Linux в CI. Оставшийся parity-объём
(crash-matrix на ext4/XFS, `systemd`, performance, soak) — задача P1-S1-007.

---

## Запуск тестов

```bash
source .venv/bin/activate
python3 -m pytest -q
```

Текущий результат: **294 passed, 0 failed, 0 skipped** (macOS / Darwin arm64, CPython 3.13.7).

Только property-тесты (Hypothesis): `python3 -m pytest -m property` → 29 passed.

Воспроизвести зафиксированное окружение и проверить его согласованность:

```bash
pip install --require-hashes -r deploy/dependencies/darwin-arm64/requirements.lock
python3 deploy/verify_dependencies.py
```

Только backend unit/contract/fault тесты. Frontend (Vitest/Playwright), integration, soak, performance и demo/testnet тесты появятся на соответствующих этапах. На Linux те же тесты прогоняются в CI; окружение там пока ставится по `requirements.in`, потому что Linux-lock не снят.

---

## Известные ограничения и открытые решения

1. ADR-001…011 открыты — требуется утверждение тимлидом.
2. Linux dependency artifacts не сняты — **production release заблокирован** (P1-S1-006). Разработка на macOS не блокируется.
3. Архитектура production-хоста и точная версия Python не утверждены — OPEN-005. Блокирует Linux production lock (P1-S1-006) и PostgreSQL-драйвера (ADR-005). Разработка Parquet writer на macOS идёт без ожидания, блокер P1-S1-004 — ADR-004.
4. Формат файла сегмента не зафиксирован: `atomic_commit` принимает writer как callback, реальный Parquet writer — задача P1-S1-004 (блокируется ADR-004 — precision/scale, overflow policy, schema evolution).
5. Property-тесты (Hypothesis) не написаны — задача P1-S1-005.
6. Linux parity не завершён: crash-matrix на ext4/XFS, `systemd`, performance и soak — P1-S1-007.
7. Bybit client library не выбрана — OPEN-001.
8. Full Orderbook: DEFERRED — availability mainnet не проверена.
9. Все BTC-absolute thresholds — `UNCALIBRATED` до замеров.

Снято: CONFLICT-004 (целевой хост) — решение в ADR-012. Нарушение Roadmap §4 об отсутствии lock и SBOM закрыто для development-платформы (P1-S1-003).

Подробно: `docs/architecture/DECISIONS_PENDING.md`.
