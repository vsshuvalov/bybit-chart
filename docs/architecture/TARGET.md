# Целевая архитектура

**Версия:** Stage 0 baseline  
**Дата:** 2026-08-10  
**Источник:** BYBIT_MULTIPROCESS_PLATFORM_ROADMAP.md v1.0 (§3, §4, §5, §6, §7, §8, §9–18)  
**Статус:** НЕ РЕАЛИЗОВАНА. Только проектный документ.

---

## Назначение системы

Серверная платформа, работающая 24/7 на одном хосте:

1. Сбор невосполнимых публичных данных Bybit по трём инструментам (BTCUSDT, ETHUSDT, XRPUSDT).
2. Lossless-хранение и воспроизводимое построение Order Flow-модулей.
3. Раздача истории и live-данных браузеру без потерь при reload/смене ТФ.
4. Поддержка ручного анализа, разметки и написания индикаторов.
5. Детерминированный replay и event-driven backtest.
6. Ручная, подтверждаемая и автоматическая торговля через единый Risk Engine.
7. AI-ассистент с read-only доступом (без прямого доступа к API-ключам).

Источник: §2.1 ROADMAP.

---

## Процессная архитектура

### Эволюция числа процессов (REQUIRED, §3.2 ROADMAP)

| Стадия | Долгоживущие процессы |
|---|---|
| 3 процесса | collector; analytics+API (временный); maintenance |
| 4 процесса | collector; orderflow-worker; api-gateway; maintenance |
| 5 процессов | + execution-risk |
| 6 процессов | + strategy-worker |
| Research jobs | simulator/optimizer/trainer (запускаются по требованию) |

### Ответственность процессов (REQUIRED, §3.3 ROADMAP)

#### `market-collector`
- Подключение к Bybit public WS/REST; heartbeat, reconnect, resubscribe.
- Raw payload, нормализация, дедупликация.
- Feed-specific sequence/gap controller.
- Materialized L50/L1000 только для проверки и checkpoint.
- WAL, закрытие raw-сегментов и book checkpoints.
- Trades, standard book, RPI (raw-only), liquidations, ticker.
- Scheduled REST ingestion: OI/funding/kline validation.
- Собственное `SourceQuality` по symbol/feed/depth.

**Запрещено:** Footprint, Heatmap tiles, Walls, Sweep, Absorption, стратегии, frontend API, compaction.

#### `orderflow-worker`
- Чтение live envelopes и догон из WAL.
- Canonical candles, Footprint, Delta/CVD, VWAP/Profile.
- Replay книг, Heatmap, DOM/OBI/OFI/MLOFI/microprice.
- Единый `AttributionSnapshot` на feature-frame.
- Absorption, Sweep, Walls, Pulling/Stacking, liquidations.
- Regime, levels, Feature API.
- Revisions, snapshots, patches и derived checkpoints.

**Запрещено:** прямые Bybit-соединения, отправка ордеров, тяжёлая compaction в live-потоке.

#### `api-gateway`
- REST history и browser WebSocket.
- `ViewSession`, snapshot + ordered patches.
- `streamEpoch`, `streamSequence`, cursor.
- Workspaces, настройки, scripts, drawings, templates.
- Auth/RBAC.
- Приём `OrderIntent` от UI (без прямого вызова Bybit).

**Запрещено:** тяжёлая аналитика, PyArrow full scans в event loop, private keys.

#### `maintenance-worker`
- Claim закрытых сегментов по lease.
- Parquet publication, footer/checksum validation.
- Compaction, tiles, retention, manifest/index.
- Recovery `.tmp`, FAILED и orphan-файлов.
- Disk budget и low-priority обслуживание.

**Запрещено:** подписка Bybit, торговые команды, одновременный запуск нескольких тяжёлых операций.

#### `execution-risk`
- Private WS `order/execution/position`.
- Bybit REST create/amend/cancel/reconciliation.
- Durable intent/order/execution ledger.
- Risk limits, idempotency, server-side SL/TP.
- Trusted Source/AnalyticsQuality subscriptions и composite entry gate.
- Защита открытой позиции при отказе UI/analytics/strategy.

**Запрещено:** вычисление тяжёлых рыночных признаков, обучение моделей, приём свободного текста ИИ как торговой команды.

#### `strategy-worker`
- Детерминированные автоматы стратегий.
- Сохранение `featureSnapshot`.
- `expiresAtMs`, regime, conflict resolution, score.
- Выпуск `OrderIntentProposal`, а не сетевой вызов Bybit.

**Запрещено:** API keys, обход Risk Engine, использование PROVISIONAL/DEGRADED признаков для нового входа.

#### Research / Simulator / AI jobs
- Replay, dataset building, backtest, parameter optimization, обучение.
- Read-only доступ к raw/derived истории.
- Пишут только versioned research artifacts.

---

## Технологический стек (REQUIRED, §4 ROADMAP)

| Зона | Технология |
|---|---|
| Backend | Python, FastAPI, Uvicorn, Pydantic |
| REST/WS Bybit | `httpx` + `websockets` либо `pybit` за адаптером (выбор через ADR-001) |
| IPC | Protocol Buffers + `grpcio` по Unix domain sockets |
| Числа | Python `int`, `decimal.Decimal`, Arrow Decimal128 |
| Рыночное хранилище | WAL + Apache Arrow/PyArrow Parquet |
| Транзакционные данные | PostgreSQL |
| Frontend | React + TypeScript + Vite |
| График | TradingView Lightweight Charts + custom Canvas/WebGL |
| Редактор | Monaco Editor |
| Backend tests | pytest + Hypothesis |
| Frontend tests | Vitest + Playwright |
| Наблюдаемость | Prometheus + Grafana; JSON logs/journald |
| ML baseline | scikit-learn; опционально XGBoost/PyTorch |
| Optimization | Optuna |
| Experiment registry | MLflow или собственный (ADR после MVP research) |

Redis, ClickHouse, TimescaleDB, Kafka — не являются условием корректности первой версии.

---

## Межпроцессные контракты (§5 ROADMAP)

### Принцип доставки

```
collector: append + fsync WAL
→ non-blocking live publish
→ analytics at-least-once
→ durable checkpoint
→ при пропуске: дочитка WAL
```

- Exactly-once transport не требуется.
- При заполнении IPC-очереди collector не ждёт analytics.
- Разрешено потерять live-уведомление; запрещено потерять принятый raw.

### Ключевые сообщения

- `RawEventEnvelope` — полная схема в §5.2 ROADMAP.
- `Snapshot / Patch` (analytics → API) — в §5.3 ROADMAP.
- `OrderIntentProposal` (strategy → execution) — в §5.4 ROADMAP.

---

## Хранение и целостность (§6 ROADMAP)

### Владение данными

| Dataset | Writer | Publisher |
|---|---|---|
| Raw trades/books/ticker/liquidations | collector | maintenance |
| Derived live state | analytics | maintenance |
| Historical Heatmap tiles | analytics создаёт CLOSED_PENDING | maintenance |
| Orders/executions/positions | execution | PostgreSQL |
| Workspaces/scripts/drawings | API | PostgreSQL |

### Состояния файла

```
ACTIVE → CLOSED_PENDING → PUBLISHING → COMMITTED
                                     ↘ FAILED → retry/quarantine
```

### Числовая модель

```
price       → priceTicks:int64
quantity    → qtySteps:int64 или Decimal128
turnover    → scaled integer/Decimal128
OI          → scaled integer/Decimal128
funding     → Decimal128
VWAP sums   → integer/Decimal128 accumulators
```

---

## Data Quality и signal gating (§7 ROADMAP)

Три независимых документа качества:

- `SourceQuality` — collector; symbol + feed + depth + connectionEpoch.
- `AnalyticsQuality` — analytics; symbol + module + lookback + revision.
- `ExecutionQuality` — execution; environment + account + private stream.

Состояния: `BOOTSTRAP | LIVE_READY | DEGRADED | STALE | GAP | REBUILDING | LAGGING`.

Новый вход разрешён только при одновременном выполнении всех условий §7.5 ROADMAP.

---

## Интеграция Bybit V5 (§8 ROADMAP)

Основные окружения: Mainnet, Testnet, Demo (изолированные secrets/namespace).

Основные public topics: `publicTrade.{symbol}`, `orderbook.50.{symbol}`, `orderbook.1000.{symbol}`, `tickers.{symbol}`, `allLiquidation.{symbol}`, `orderbook.rpi.{symbol}` (raw-only).

Full Orderbook (`orderbook.full.{symbol}`): **DEFERRED** за feature flag. Mainnet rollout ожидался 2026-08-11 — перед реализацией перепроверить production-доступность.

---

## Модули Order Flow (§9, §10 ROADMAP)

Реестр см. в `docs/REQUIREMENTS_TRACEABILITY.md`. Каждый модуль обязан иметь:

- typed input/output schema;
- `algorithmVersion`, `configurationHash`, `sourceDataRevision`;
- deterministic replay;
- gap/late-event policy;
- `BUILDING/PROVISIONAL/FINAL`;
- unit/property/replay/performance tests.

---

## Frontend (§11 ROADMAP)

Desktop-first web UI. Layout: top bar / left toolbar / center chart / right sidebar / bottom dock / status bar.

Server source of truth: workspaces, drawings, templates, scripts, orders, positions, approvals. `localStorage` — только UI cache с `schemaVersion` и safe defaults.

Browser никогда не подключается к Bybit напрямую.

---

## Порядок этапов реализации (§19 ROADMAP)

| Этап | Содержание |
|---|---|
| 0 | Freeze, аудит и baseline — **текущий** |
| 1 | Shared schemas и storage core |
| 2 | Изолированный collector |
| 3 | Базовые live-роли и расширение scope |
| 4 | Четыре процесса |
| 5 | Trade-derived analytics |
| 6 | Book-derived analytics |
| 7 | Frontend analysis workstation |
| P | Indicator runtime (параллельный трек) |
| 8 | Simulator/replay |
| 9 | Пятый процесс: execution |
| 10 | Шестой процесс: стратегии |
| 11 | AI assistant и ML research |
| 12 | Controlled automation и production 24/7 |

---

## Стратегии (§14 ROADMAP)

Шесть основных + один экспериментальный (по умолчанию OFF):

1. Sweep Failure / Failed Auction
2. Breakout Acceptance + Retest
3. Trend Pullback
4. VWAP / Value Area Rotation
5. Absorption Reversal
6. Liquidation Exhaustion
7. Liquidity Vacuum (DEFERRED, `enabled=false`)

Все стратегии проходят promotion gate: replay → unit → backtest → walk-forward → OOS → signal-only → paper → demo → live canary.

---

## Неподлежащие компромиссу свойства (§2.2 ROADMAP)

```
Биржевое событие сначала долговечно записывается, потом вычисляется.
Downstream-процесс не может остановить collector.
Неизвестный участок данных всегда маркируется gap, а не интерполируется.
Одинаковые raw + config + version → одинаковый результат.
UI не является владельцем рыночной истории или ордеров.
Ручной, стратегический и AI-вход проходят один Risk/Execution Engine.
ACK биржи не считается исполнением.
Стратегия не считывает пиксели или цвета — только числовые признаки.
```
