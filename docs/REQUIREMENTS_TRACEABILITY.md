# Трассировка требований

**Stage:** 0  
**Дата:** 2026-08-10  
**Источник:** BYBIT_MULTIPROCESS_PLATFORM_ROADMAP.md v1.0  
**Статус всех требований:** NOT_STARTED

---

## Обозначения

- `REQUIRED` — обязательное требование.
- `DECIDED` — решение зафиксировано в нормативных документах.
- `ASSUMPTION` — рабочее предположение.
- `NOT_STARTED` — не реализовано.

---

## Ядро и процессная архитектура

| ID | Раздел | Требование | Компонент | Проверка | Stage | Статус |
|---|---|---|---|---|---|---|
| REQ-001 | §2.2 | Биржевое событие записывается до вычисления | market-collector, WAL | crash test: SIGKILL после WS receive до fsync | 2 | NOT_STARTED |
| REQ-002 | §2.2 | Downstream-процесс не может остановить collector | market-collector / IPC | SIGKILL analytics → collector продолжает | 2 | NOT_STARTED |
| REQ-003 | §2.2 | Неизвестный участок данных маркируется gap, не интерполируется | все процессы | gap-marker тест на reconnect | 2 | NOT_STARTED |
| REQ-004 | §2.2 | Одинаковые raw + config + version → одинаковый результат | orderflow-worker | deterministic replay checksum | 5 | NOT_STARTED |
| REQ-005 | §2.2 | UI не владеет рыночной историей | api-gateway, browser | reload не теряет данные | 7 | NOT_STARTED |
| REQ-006 | §2.2 | Ручной/стратегический/AI-вход проходят один Risk Engine | execution-risk | intent ledger audit | 9 | NOT_STARTED |
| REQ-007 | §2.2 | ACK биржи не считается исполнением | execution-risk | duplicate Filled test | 9 | NOT_STARTED |
| REQ-008 | §2.2 | Стратегия не считывает пиксели/цвета — только числа | strategy-worker, Feature API | unit test: нет цветов в OrderFlowFeatures | 10 | NOT_STARTED |
| REQ-009 | §3.2 | Эволюция 3→4→5→6 процессов | все сервисы | kill-matrix тест каждой стадии | 2–10 | NOT_STARTED |
| REQ-010 | §3.5 | Структура репозитория contracts/services/packages/web/research/deploy/tests/docs | repo | `find` tree audit | 0 | **DONE** |

---

## Хранение и целостность

| ID | Раздел | Требование | Компонент | Проверка | Stage | Статус |
|---|---|---|---|---|---|---|
| REQ-011 | §6.1 | Один ACTIVE writer на dataset | collector, maintenance | lease + fencing test | 2 | NOT_STARTED |
| REQ-012 | §6.2 | WAL offsets: accepted/durable/closed/published/consumer | collector | offset invariant test | 2 | NOT_STARTED |
| REQ-013 | §6.2 | Torn frame отбрасывается до последнего валидного boundary | collector | torn-write fault test | 2 | NOT_STARTED |
| REQ-014 | §6.2 | WAL GC только до replaySafeOffset | maintenance | GC invariant test | 2 | NOT_STARTED |
| REQ-015 | §6.3 | Состояния файла: ACTIVE→CLOSED_PENDING→PUBLISHING→COMMITTED→FAILED | maintenance | state machine test | 2 | NOT_STARTED |
| REQ-016 | §6.4 | Atomic Parquet commit: tmp→validate→fsync→rename→fsync parent→manifest | maintenance | crash matrix: 4 точки | 1 | NOT_STARTED |
| REQ-017 | §6.5 | Партиционирование: venue/category/symbol/event_type/date | collector, maintenance | schema validation | 2 | NOT_STARTED |
| REQ-018 | §6.6 | Числовая модель: priceTicks:int64, qtySteps:int64, Decimal128 | packages/numeric | round-trip test; нет float ключей | 1 | NOT_STARTED |
| REQ-019 | §6.7 | Derived key включает algorithmVersion + configurationHash | orderflow-worker | cache key test | 5 | NOT_STARTED |
| REQ-020 | §6.8 | Retention 30 суток принимается только после 72h замера | maintenance, ops | capacity measurement + ADR | 3 | NOT_STARTED |

---

## Межпроцессные контракты

| ID | Раздел | Требование | Компонент | Проверка | Stage | Статус |
|---|---|---|---|---|---|---|
| REQ-021 | §5.1 | group-commit fsync; live publish не опережает durableOffset | collector | group-commit latency SLO | 2 | NOT_STARTED |
| REQ-022 | §5.2 | RawEventEnvelope: все обязательные поля | contracts | schema validation + backward compat test | 1 | NOT_STARTED |
| REQ-023 | §5.2 | eventId детерминирован и стабилен при replay | collector | replay idempotency test | 2 | NOT_STARTED |
| REQ-024 | §5.3 | Analytics→API: snapshot + ordered patches; gap → resnapshot | api-gateway | patch-loss resnapshot test | 4 | NOT_STARTED |
| REQ-025 | §5.4 | OrderIntentProposal lifecycle: PROPOSED→VALIDATED→MATERIALIZED/REJECTED | execution-risk | state machine test | 9 | NOT_STARTED |
| REQ-026 | §5.5 | Ломающая смена протокола увеличивает major protocolVersion | contracts | compatibility fixture | 1 | NOT_STARTED |

---

## Bybit-адаптер

| ID | Раздел | Требование | Компонент | Проверка | Stage | Статус |
|---|---|---|---|---|---|---|
| REQ-027 | §8.1 | Три окружения: Mainnet/Testnet/Demo; изолированные secrets | market-collector, execution-risk | config isolation test | 2 | NOT_STARTED |
| REQ-028 | §8.2 | Дедупликация trades по tradeId (не seq) | market-collector | duplicate tradeId fixture | 2 | NOT_STARTED |
| REQ-029 | §8.2 | L50 и L1000 — независимые книги | market-collector | independent epoch test | 2 | NOT_STARTED |
| REQ-030 | §8.2 | RPI feed хранится raw-only, не смешивается со standard book | market-collector | non-double-count test | 3 | NOT_STARTED |
| REQ-031 | §8.2 | Full Orderbook: DEFERRED, feature flag | market-collector | flag=off тест | DEFERRED | NOT_STARTED |
| REQ-032 | §8.2 | REST recent trades ≤1000; нет cursor; только короткий backfill | market-collector | overlap-proof test | 2 | NOT_STARTED |
| REQ-033 | §8.3 | retCode=0 на create/amend/cancel — async ACK, не fill | execution-risk | ACK≠fill test | 9 | NOT_STARTED |
| REQ-034 | §8.3 | Dedup fills: environment+accountId+category+symbol+execId | execution-risk | duplicate Filled test | 9 | NOT_STARTED |
| REQ-035 | §8.3 | Rate limiter: X-Bapi-Limit*; 10006 как UID budget; 429 как system | execution-risk | rate-limit fixture | 9 | NOT_STARTED |

---

## Модули Order Flow

| ID | Раздел | Требование | Компонент | Проверка | Stage | Статус |
|---|---|---|---|---|---|---|
| REQ-036 | §9.2 | InstrumentConfig: tickSize/qtyStep/fundingInterval загружаются динамически | market-collector | нет hardcode BTC-параметров | 2 | NOT_STARTED |
| REQ-037 | §9.3 | Все 18 модулей: typed schema, replay, gap policy, BUILDING/PROVISIONAL/FINAL | orderflow-worker | replay checksum test для каждого | 5–6 | NOT_STARTED |
| REQ-038 | §9.1 | CalibratedThreshold: UNCALIBRATED блокирует strategy use | strategy-worker | threshold gate test | 10 | NOT_STARTED |
| REQ-039 | §9.4 | AttributionSnapshot: единая materialization на feature-frame | orderflow-worker | нет per-level журнала | 6 | NOT_STARTED |
| REQ-040 | §9.3 | Heatmap: gap cells пустые/штрихованные, не интерполируются | orderflow-worker, maintenance | gap cell audit | 6 | NOT_STARTED |

---

## Data Quality

| ID | Раздел | Требование | Компонент | Проверка | Stage | Статус |
|---|---|---|---|---|---|---|
| REQ-041 | §7.1 | SourceQuality / AnalyticsQuality / ExecutionQuality — три независимых документа | collector, analytics, execution | unit test каждого | 2–9 | NOT_STARTED |
| REQ-042 | §7.5 | Новый вход только при одновременном выполнении всех gate-условий | execution-risk | gate unit tests | 9 | NOT_STARTED |
| REQ-043 | §7.4 | BUILDING→PROVISIONAL→FINAL; late event после FINAL → новая revision или incident | orderflow-worker | late-event revision test | 5 | NOT_STARTED |
| REQ-044 | §6.9 | Recovery state machine для collector, analytics, browser, execution | все | crash-then-replay test | 2–9 | NOT_STARTED |

---

## Execution и Risk

| ID | Раздел | Требование | Компонент | Проверка | Stage | Статус |
|---|---|---|---|---|---|---|
| REQ-045 | §15.1 | Journal-before-network: сначала fsync, потом Bybit | execution-risk | crash-between-journal-and-send test | 9 | NOT_STARTED |
| REQ-046 | §15.1 | Emergency WAL для PROTECT/CANCEL/FLATTEN при недоступности PostgreSQL | execution-risk | DB-outage fault test | 9 | NOT_STARTED |
| REQ-047 | §15.2 | Intent states: все переходы сохраняют cumExecQty, leavesQty, averageFillPrice | execution-risk | state machine test | 9 | NOT_STARTED |
| REQ-048 | §15.5 | Confirmed fill → confirmed server-side protection ≤2s | execution-risk | SLA watchdog test | 9 | NOT_STARTED |
| REQ-049 | §15.4 | Размер позиции: RiskQuote/RiskPerBase, round_down по qtyStep | execution-risk | position sizing unit test | 9 | NOT_STARTED |

---

## Frontend

| ID | Раздел | Требование | Компонент | Проверка | Stage | Статус |
|---|---|---|---|---|---|---|
| REQ-050 | §11.7 | Market data store не очищается при unmount/TF change | web | TF round-trip E2E | 7 | NOT_STARTED |
| REQ-051 | §11.7 | Browser никогда не подключается к Bybit напрямую | web | network audit в E2E | 7 | NOT_STARTED |
| REQ-052 | §11.7 | localStorage — только UI cache; server source of truth для artifacts | web | reload artifact integrity test | 7 | NOT_STARTED |
| REQ-053 | §11.8 | Reload возвращает те же aggregates и drawings | web | E2E reload test | 7 | NOT_STARTED |

---

## Стратегии

| ID | Раздел | Требование | Компонент | Проверка | Stage | Статус |
|---|---|---|---|---|---|---|
| REQ-054 | §14.1 | Универсальный автомат: DISABLED→…→CLOSED/INVALIDATED/ERROR | strategy-worker | state machine test | 10 | NOT_STARTED |
| REQ-055 | §14.2 | Regime enum и матрица разрешённых входов | strategy-worker | regime gate test | 10 | NOT_STARTED |
| REQ-056 | §14.3 | Все 6 стратегий: SL/TP/timeStop/logicExit/maximumHolding | strategy-worker | truth-table test каждой | 10 | NOT_STARTED |
| REQ-057 | §14.7 | Promotion gate: replay→unit→backtest→WF→OOS→signal-only→paper→demo→canary | ops | promotion checklist | 10–12 | NOT_STARTED |

---

## AI/ML

| ID | Раздел | Требование | Компонент | Проверка | Stage | Статус |
|---|---|---|---|---|---|---|
| REQ-058 | §16.1 | LLM Assistant, Optimizer, Strategy runtime — три независимые системы | research, strategy-worker | isolation test | 11 | NOT_STARTED |
| REQ-059 | §16.5 | AI не имеет доступа к API keys и не вызывает Bybit напрямую | research | permission gate test | 11 | NOT_STARTED |
| REQ-060 | §16.4 | Model registry lifecycle: DRAFT→…→APPROVED_LIVE; promotion только человеком | research | promotion gate test | 11 | NOT_STARTED |

---

## Release и SLO

| ID | Раздел | Требование | Компонент | Проверка | Stage | Статус |
|---|---|---|---|---|---|---|
| REQ-061 | §18.4 | Hard gates: ноль потерь принятых raw events; ноль немаркированных gaps | collector | 72h soak + gap audit | 2–3 | NOT_STARTED |
| REQ-062 | §20.1 | Immutable release artifact; service manager не смотрит в worktree | deploy | artifact integrity check | 12 | NOT_STARTED |
| REQ-063 | §18.5 | PostgreSQL backup + restore drill до live | ops | restore drill evidence | 12 | NOT_STARTED |
