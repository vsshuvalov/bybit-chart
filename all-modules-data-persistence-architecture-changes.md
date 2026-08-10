# Изменения к `all-modules-data-persistence-architecture.md`

**Дата проверки:** 2026-08-08  
**Исходный документ:** `/all-modules-data-persistence-architecture.md`  
**Целевой стек:** один FastAPI-процесс, Parquet, server-side aggregation, REST/WebSocket, `localStorage`  
**Инструмент:** BTCUSDT Linear Perpetual, Bybit

## 1. Итог проверки

Документ не требуется переписывать целиком. В силе остаются:

- сырые биржевые события как источник истины;
- воспроизводимость Footprint, Delta, CVD, VWAP и Volume Profile;
- независимость рыночного WebSocket от таймфрейма;
- snapshot/delta-модель стакана;
- gap-маркеры и блокировка сигналов;
- версионирование алгоритмов;
- deterministic replay;
- состояние `LIVE_READY` перед разрешением торговли;
- правило, что UI отображает данные, но не владеет рыночной историей.

Обновить необходимо разделы §2–3, §5–6, §9–10, §14–16, §19–26 и §30–31.

---

## 2. P0 — обязательные изменения

### 2.1. Зафиксировать принятую архитектуру

Заменить абстрактную или браузерную схему на фактическую:

```text
Один FastAPI-процесс
  ├── MarketDataHub
  ├── normalizer/deduplicator
  ├── materialized order book
  ├── aggregation engine
  ├── historical REST API
  ├── frontend WebSocket gateway
  └── data-quality monitoring

Parquet
  ├── raw market events
  ├── закрытые агрегаты
  ├── book checkpoints
  ├── manifests
  └── gap/checkpoint metadata

Memory
  ├── текущий стакан
  ├── live-tail
  ├── bounded ingestion queues
  ├── текущие агрегаты
  └── fan-out подписчикам

localStorage
  └── versioned frontend preferences
```

ClickHouse, TimescaleDB, Redis и IndexedDB считать только возможными средствами будущего масштабирования, а не требованиями корректности.

### 2.2. Разделить рыночные и пользовательские сессии

Добавить три независимые роли:

```text
MarketDataHub
  key: venue + category + symbol
  lifetime: пока работает сервер
  responsibility:
    - публичные Bybit WebSocket
    - reconnect/backfill
    - order book
    - raw persistence
    - gaps/data quality

ViewSession
  key: client/workspace + symbol + timeframe + settings
  lifetime: пока открыт клиент
  responsibility:
    - выбранный ТФ
    - price step
    - видимый диапазон
    - отображаемые модули
    - подписка на готовые агрегаты

ExecutionHub
  key: account/UID
  responsibility:
    - private WebSocket
    - orders/executions/positions
    - reconciliation
    - durable order journal
```

`PrivateFeed` не должен принадлежать `MarketDataHub`, поскольку он привязан к аккаунту, а не к рынку.

### 2.3. Добавить безопасный Parquet commit protocol

Запрещено писать открытым `ParquetWriter` непосредственно в финальный путь и считать такой файл доступной историей.

Обязательная последовательность:

```text
bounded live buffer или WAL
→ записать segment.tmp
→ закрыть ParquetWriter
→ проверить footer
→ проверить schemaVersion
→ проверить row count и checksum
→ fsync(segment.tmp)
→ os.replace(segment.tmp, segment.parquet)
→ fsync(parent directory)
→ атомарно обновить manifest
→ только после commit продвинуть checkpoint
```

Исторический REST должен объединять:

```text
committed Parquet segments
+ server live-tail
+ при необходимости committed WAL/microsegments
```

Добавить:

- восстановление незавершённых `.tmp` после рестарта;
- `schemaVersion` в metadata;
- checksum;
- manifest/index;
- compaction мелких сегментов;
- партиционирование по `category/symbol/event_type/date`;
- checkpoint последнего подтверждённо опубликованного события;
- отдельные ошибки `corrupt`, `incomplete`, `legacy`, `schema mismatch`.

### 2.4. Разделить сценарии восстановления

#### Перезапуск или reconnect коллектора

```text
1. Открыть Bybit WebSocket в buffer-mode.
2. Загрузить durable checkpoint и live-tail/WAL.
3. Выполнить REST recent-trades backfill.
4. Объединить storage + REST + WS buffer.
5. Дедуплицировать по category + symbol + tradeId.
6. Доказать overlap между сохранёнными и восстановленными сделками.
7. Если overlap отсутствует — создать trade gap marker.
8. Для стакана дождаться нового snapshot.
9. Выполнить warm-up.
10. Перейти в LIVE_READY.
```

REST recent trades для linear возвращает максимум 1000 последних сделок и не имеет cursor/start/end. Поэтому backfill не гарантирует закрытие длинного разрыва. [Bybit Recent Public Trades](https://bybit-exchange.github.io/docs/v5/market/recent-trade)

#### Reload frontend

```text
1. Загрузить versioned preferences из localStorage.
2. Подключить frontend WebSocket FastAPI в buffer/cursor-mode.
3. Запросить историю и агрегаты через FastAPI REST.
4. Объединить REST history + FastAPI WS buffer.
5. Выполнить series.setData(history).
6. Перейти на live update.
```

Frontend не должен:

- подключаться к публичному Bybit WebSocket;
- делать Bybit REST-backfill;
- самостоятельно восстанавливать стакан;
- подключать private Bybit streams.

### 2.5. Каноническая числовая модель

Для persistent/replay-данных запретить binary floating point.

```text
price       → priceTicks:int64
quantity    → qtySteps:int64 или Decimal128
book size   → qtySteps:int64 или Decimal128
turnover    → scaled integer или Decimal128
OI          → scaled integer или Decimal128
funding     → Decimal128
VWAP sums   → integer/Decimal128 accumulators
```

`float/number` допустим только в UI и для некритичных визуальных вычислений.

### 2.6. Защита event loop FastAPI

PyArrow scan/write, compaction и тяжёлая агрегация не должны блокировать async event loop.

Добавить:

- bounded queues;
- отдельные writer tasks;
- thread/process offload для PyArrow и тяжёлых агрегатов;
- метрики queue depth и queue lag;
- backpressure policy;
- явную политику `block/drop/degrade`;
- graceful shutdown с flush/commit;
- startup recovery.

---

## 3. P0 — исправления Bybit-адаптера

### 3.1. Сделки

Каноническая структура должна сохранять:

```text
venue
category
symbol
tradeId
seq
trade.T
outer ts
receiveTimestamp
priceTicks
qtySteps
takerSide
BT
RPI
```

`turnoverQuote` отсутствует в public trade WebSocket и является вычисляемым полем `price × size`. Несколько сообщений могут иметь одинаковый `seq`; дедупликация выполняется по `category + symbol + tradeId`. [Bybit Public Trade](https://bybit-exchange.github.io/docs/v5/websocket/public/trade)

### 3.2. Стандартный order book

Исправить тип глубины:

```typescript
type StandardBookDepth = 1 | 50 | 200 | 1000;
```

Для linear:

```text
L1    → 10 мс, snapshot-only
L50   → 20 мс
L200  → 100 мс
L1000 → 200 мс
```

[Bybit Order Book](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)

Book event/checkpoint должен включать:

```text
venue
category
symbol
depth
connectionId
type
u
seq
outer ts
cts
receiveTimestamp
schemaVersion
bids/asks
```

Не считать `u` и `seq` универсально непрерывными по правилу `previous + 1`. Для стандартного order-book Bybit описывает `seq` как cross sequence для порядка и сравнения, но не гарантирует `seq+1`.

Gap validator должен быть feed-specific и учитывать:

- disconnect/reconnect;
- resubscribe;
- новый snapshot;
- `u=1` reset;
- regress/reset sequence;
- аномальную тишину;
- конкретные гарантии выбранного feed.

### 3.3. RPI order book

Обычный публичный стакан не включает RPI liquidity. Опционально доступен:

```text
orderbook.rpi.BTCUSDT
L50
100 мс
```

Он содержит отдельно non-RPI и RPI size. Если он не используется, Heatmap должна быть обозначена как `standard API-visible liquidity only`. [Bybit RPI Order Book](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook-rpi)

### 3.4. Full Orderbook

Добавить отдельную заметку о новом Full Orderbook. Не переключать production-коллектор автоматически: алгоритм синхронизации отличается от стандартного snapshot/delta feed, а доступность должна проверяться для нужной категории и окружения.

После фактического включения для BTCUSDT linear потребуется отдельный адаптер, отдельные тесты sequence/recovery и проверка mainnet rollout. [Bybit Full Orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/full-ob)

### 3.5. История стакана и Heatmap

Заменить неоднозначное `Sparse Book Deltas` на:

```text
Lossless sequence of all received sparse delta messages
within subscribed depth and gap-free connection epoch
```

Слово `sparse` описывает формат сообщения, а не прореживание данных.

Историю можно восстановить только:

- в пределах подписанной глубины;
- от валидного checkpoint/snapshot;
- внутри gap-free connection epoch;
- без претензии на полный биржевой стакан;
- с учётом отсутствия RPI в стандартном feed.

Разделить два источника:

```text
Sampled depth snapshots
→ визуальная Heatmap
→ нельзя восстановить каждое состояние книги

Checkpoint + every received delta
→ воспроизводимый subscribed-depth book
→ только между gap-маркерами
```

Поля `executedBid/executedAsk` в Heatmap tiles переименовать в:

```text
estimatedExecutedBid
estimatedExecutedAsk
attributionConfidence
```

### 3.6. Ликвидации

Убрать двусмысленное `positionSide: Buy | Sell`.

Хранить:

```typescript
interface RawLiquidation {
  rawSide: "Buy" | "Sell";
  liquidatedPositionSide: "Long" | "Short";
  inferredForcedFlow: "Buy" | "Sell";
  bankruptcyPriceTicks: bigint;
  quantitySteps: bigint;
  exchangeTimestampMs: number;
  outerTimestampMs: number;
  receiveTimestampMs: number;
}
```

Нормализация:

```text
S=Buy  → ликвидирована Long-позиция  → inferredForcedFlow=Sell
S=Sell → ликвидирована Short-позиция → inferredForcedFlow=Buy
```

`p` — bankruptcy price, не фактическая цена исполнения. `data` фактически приходит как массив. У события нет exchange ID/seq, поэтому точная cross-reconnect дедупликация невозможна; после disconnect нужен liquidation gap marker. [Bybit All Liquidation](https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation)

Переименовать агрегаты:

```text
Buy Liquidations  → longLiquidatedVolume
Sell Liquidations → shortLiquidatedVolume
```

### 3.7. Ticker, OI и funding

Linear ticker является snapshot/delta-потоком. Если поле отсутствует в delta, оно не изменилось; его нельзя заменять `null` или нулём. Нужен materialized ticker state. [Bybit Ticker](https://bybit-exchange.github.io/docs/v5/websocket/public/ticker)

Указать источники:

```text
live openInterest/openInterestValue → ticker WebSocket
historical openInterest             → Open Interest REST
fundingInterval                     → Instruments Info
funding history                     → Funding History
```

### 3.8. Kline

При REST bootstrap:

- Bybit возвращает свечи newest-first;
- перед `series.setData()` сортировать ascending;
- последняя незакрытая свеча имеет динамический close;
- незакрытую свечу нельзя сравнивать как final.

[Bybit Kline](https://bybit-exchange.github.io/docs/v5/market/kline)

---

## 4. P1 — признаки и агрегаты

### 4.1. Оценочная атрибуция fill/cancel/refill

Публичный order book не позволяет точно разделить исполнение и отмену: исчезнувший размер означает `filled or cancelled`.

Использовать:

```text
executedEstimated
cancelledEstimated
refilledEstimated
attributionConfidence ∈ [0,1]
```

Корреляцию строить преимущественно по:

```text
book.cts ↔ trade.T
price
side
volume window
```

Не считать сопоставление book/trade через `seq` официально гарантированным.

При низкой `attributionConfidence`:

- блокировать absorption/refill-сигналы;
- помечать feature bar как degraded;
- не использовать данные для торгового решения;
- сохранять причину низкой уверенности.

### 4.2. Единый ключ кеша

Унифицировать все локальные описания ключей.

Логическая идентичность:

```text
venue
category
symbol
module
timeframe/resolution
priceStep
anchor/session
range
algorithmVersion
configurationHash
```

Ревизию исходных данных хранить одним из двух способов.

#### Вариант A — стабильный ключ

```text
logicalKey → value(sourceDataRevision=N)
```

Новая ревизия атомарно заменяет старую.

#### Вариант B — immutable physical key

```text
logicalKey:revision → immutable value
logicalKey → latestRevision pointer
```

Нельзя просто добавить `dataRevision` в ключ без атомарного указателя на последнюю ревизию.

### 4.3. Watermark

Убрать связь watermark с клиентским ping 200 мс.

Watermark рассчитывается на серверном collector по event-time lateness:

```text
lateness = receiveTimestamp - exchangeTimestamp
watermarkDelay = observed p99 или p99.9 lateness + safety margin
```

Настройки должны быть отдельными для:

- trades;
- order book;
- liquidations;
- ticker;
- private executions.

Очень позднее событие после `FINAL` должно:

- создать новую `dataRevision`/patch; либо
- создать data-quality incident;
- но не изменять историю молча.

### 4.4. DataQualityState

Расширить состояния:

```text
BOOTSTRAP
LIVE_READY
DEGRADED
STALE
GAP
REBUILDING
```

Добавить:

```text
collectorId
connectionId
tradeGap
bookGap
liquidationGap
tickerGap
lastTradeSequence
lastBookSequence
lastTradeId
lastBookUpdateId
attributionConfidence
queueDepth
queueLagMs
sourceDataRevision
```

Новые торговые сигналы разрешены только в `LIVE_READY`.

---

## 5. P1 — frontend и настройки

### 5.1. Смена таймфрейма

Целевой сценарий:

```text
TIMEFRAME_CHANGE
→ не трогать Bybit WebSocket
→ не очищать server raw state/book state
→ запросить агрегат нового ТФ через FastAPI REST
→ сохранить старый график до готовности нового набора
→ series.setData(new timeframe history)
→ атомарно переключить FastAPI live subscription
→ продолжить series.update(live bars)
```

Старый View не уничтожается до загрузки нового, чтобы график не становился пустым.

### 5.2. localStorage

Разрешить:

- цвета;
- размеры панелей;
- видимость модулей;
- последний symbol/TF;
- visible range;
- небольшие UI-фильтры.

Обязательно:

- `schemaVersion`;
- миграции;
- проверка повреждённых значений;
- безопасные defaults.

Скрипты индикаторов, разметка и шаблоны являются долговечными пользовательскими артефактами. Для них требуется:

- server-side versioned storage; либо
- минимум export/import, backup и миграции.

IndexedDB для рыночной истории в принятой архитектуре не нужен.

---

## 6. P1 — private recovery и исполнение

### 6.1. Startup/reconnect

```text
1. Запретить новые заявки.
2. Подключить private WebSocket в buffer-mode.
3. Получить позиции.
4. Получить active orders.
5. Получить order history от durable checkpoint.
6. Получить execution history от durable checkpoint.
7. Объединить REST + WS buffer.
8. Дедуплицировать fills по category + symbol + execId.
9. Сопоставить orderLinkId с durable order journal.
10. Проверить server-side SL каждой позиции.
11. Перейти в EXECUTION_READY.
```

`/v5/order/realtime` не является полноценным архивом закрытых заявок; после server release/restart использовать order history. Order WebSocket может прислать два `Filled` при гонке fill/cancel. [Bybit Open & Closed Orders](https://bybit-exchange.github.io/docs/v5/order/open-order), [Bybit Private Order Stream](https://bybit-exchange.github.io/docs/v5/websocket/private/order)

### 6.2. Durable order journal

Order journal должен храниться на сервере. Для него использовать:

- WAL; либо
- атомарно публикуемые микросегменты;
- idempotent commands через уникальный `orderLinkId`;
- checkpoint подтверждённых executions.

Нельзя полагаться на browser/localStorage или незакрытый ParquetWriter.

---

## 7. P2 — тесты

Добавить к существующим тестам:

### 7.1. Parquet crash consistency

```text
crash до close
crash после close до rename
crash после rename до manifest
crash после manifest до checkpoint
```

Проверить:

- незавершённый файл не публикуется как история;
- committed segment читается;
- manifest/checkpoint согласованы;
- recovery не создаёт дублей;
- live-tail закрывает текущий интервал.

### 7.2. Trade recovery

- reconnect с overlap внутри 1000 REST trades;
- reconnect без overlap;
- одинаковый `seq` в нескольких сообщениях;
- дубликат `tradeId`;
- out-of-order trades;
- gap marker при недоказанной полноте.

### 7.3. Book recovery

- новый snapshot заменяет книгу;
- `u=1` reset;
- reconnect создаёт новую connection epoch;
- gap не интерполируется;
- checkpoint + deltas воспроизводят subscribed-depth book;
- sampled Heatmap не объявляется полной историей;
- стандартный и RPI feed не смешиваются без явного правила.

### 7.4. Aggregation precision

- повторный replay даёт идентичный checksum;
- нет расхождений из-за float;
- `Delta(5m) = sum(Delta(1m))`;
- VWAP не меняется от визуального ТФ;
- late event создаёт новую revision;
- клиент получает последнюю revision.

### 7.5. Frontend

- reload не очищает историю;
- `1m → 5m → 1m` возвращает идентичный набор;
- Bybit WebSocket не перезапускается при смене ТФ;
- старый график остаётся до готовности нового;
- REST history и FastAPI WS buffer не создают дубли.

### 7.6. Private execution

- duplicate Filled;
- fill/cancel race;
- execution во время disconnect;
- orphan exchange order;
- позиция без защитного SL;
- повтор команды с тем же `orderLinkId`;
- восстановление executions от checkpoint.

### 7.7. Test runner

Пропущенный набор JS/frontend-тестов не должен завершаться сообщением «всё зелёное».

Допустимые результаты:

```text
PASS
FAIL
SKIPPED с явным количеством и причиной
```

CI должен завершаться ошибкой, если обязательный suite не был запущен.

---

## 8. Новый порядок внедрения

### P0. Непрерывность и целостность

1. Запуск FastAPI collector под supervisor/systemd.
2. Health check и auto-restart.
3. Канонические trade ID/timestamps/sequences.
4. Integer/Decimal numeric model.
5. Lossless raw trade/book events.
6. Atomic Parquet commit protocol.
7. Manifest/schema/checkpoint/gap metadata.
8. REST recent-trades overlap proof.
9. Honest test runner.

### P1. Развязка

1. `MarketDataHub`.
2. `ViewSession`.
3. `ExecutionHub`.
4. Независимость Bybit subscription от ТФ.
5. FastAPI REST history + frontend WS cursor/buffer.

### P2. Агрегация и Heatmap

1. Book checkpoints.
2. Every received delta внутри connection epoch.
3. Heatmap tiles.
4. Unified cache identity/revisions.
5. Event-time watermark.
6. Estimated attribution + confidence.

### P3. Стратегии и исполнение

1. Версионированные feature events.
2. Explainable StrategySignal.
3. Durable order journal.
4. Private reconciliation.
5. Signal blocking при плохих данных.
6. Deterministic replay и event-driven backtest.

### P4. Масштабирование при необходимости

Рассматривать отдельные процессы, ClickHouse/TimescaleDB/Redis/Object Storage только при фактических проблемах:

- недостаточная скорость диапазонных запросов;
- блокировка ingestion;
- несколько символов/пользователей;
- недостаточная отказоустойчивость;
- невозможность выполнить retention/SLA текущими средствами.

---

## 9. Критерии готовности обновлённой архитектуры

Изменения считаются завершёнными, когда:

- FastAPI collector работает независимо от браузера;
- смена ТФ не меняет Bybit subscriptions;
- raw trades дедуплицируются по `category + symbol + tradeId`;
- при недоказанном overlap создаётся trade gap;
- book history ограничена subscribed depth и connection epochs;
- стандартный/RPI/Full order book не смешиваются неявно;
- открытый Parquet-файл не публикуется как история;
- checkpoint продвигается только после атомарного commit;
- REST возвращает committed history + live-tail;
- replay не зависит от floating-point ошибок;
- refill/cancel/fill имеют `attributionConfidence`;
- liquidation side нормализована в Long/Short;
- ticker delta материализуется корректно;
- frontend получает историю от FastAPI, а не Bybit;
- localStorage имеет schemaVersion/migrations;
- private recovery включает executions и order history;
- новые сигналы разрешаются только в `LIVE_READY` и `EXECUTION_READY`;
- все обязательные тестовые suites реально выполняются.

---

## 10. Официальные источники

- [Bybit Public Trade](https://bybit-exchange.github.io/docs/v5/websocket/public/trade)
- [Bybit Recent Public Trades](https://bybit-exchange.github.io/docs/v5/market/recent-trade)
- [Bybit Standard Order Book](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)
- [Bybit RPI Order Book](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook-rpi)
- [Bybit Full Orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/full-ob)
- [Bybit All Liquidation](https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation)
- [Bybit Ticker](https://bybit-exchange.github.io/docs/v5/websocket/public/ticker)
- [Bybit Open Interest](https://bybit-exchange.github.io/docs/v5/market/open-interest)
- [Bybit Funding History](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate)
- [Bybit Instruments Info](https://bybit-exchange.github.io/docs/v5/market/instrument)
- [Bybit Kline](https://bybit-exchange.github.io/docs/v5/market/kline)
- [Bybit Private Order Stream](https://bybit-exchange.github.io/docs/v5/websocket/private/order)
- [Bybit Private Execution Stream](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)
- [Bybit Open & Closed Orders](https://bybit-exchange.github.io/docs/v5/order/open-order)
- [Bybit Order History](https://bybit-exchange.github.io/docs/v5/order/order-list)
- [Bybit Execution History](https://bybit-exchange.github.io/docs/v5/order/execution)
