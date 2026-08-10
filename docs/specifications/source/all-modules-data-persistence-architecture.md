# Архитектура хранения и восстановления всех модулей торговой платформы

> **Ревизия 2026-08-08.** Документ приведён в соответствие с принятым
> стеком (один процесс FastAPI, Parquet, серверная агрегация, REST и
> WebSocket наружу, `localStorage` для настроек) и с проверенным
> поведением API Bybit. Переписан не целиком: в силе остались сырьё как
> источник истины, воспроизводимость производных, независимость сокета от
> таймфрейма, snapshot/delta-модель книги, gap-маркеры, версионирование
> алгоритмов, детерминированный повтор и правило «UI отображает, но не
> владеет историей». Обновлены разделы 2–3, 4–6, 9–10, 14–17, 19–27,
> 30–31.

## 1. Назначение документа

Документ описывает, как организовать данные всех модулей BTCUSDT на Bybit так, чтобы:

- данные не исчезали после обновления страницы;
- смена таймфрейма не очищала графики;
- после обрыва WebSocket не возникали незаметные пропуски;
- Footprint, Delta, CVD, Heatmap, Volume Profile и сигналы воспроизводились одинаково;
- UI не являлся владельцем рыночной истории;
- стратегию можно было тестировать на тех же данных и той же логике, что используются в live-режиме.

Главный архитектурный принцип:

```text
Сырые биржевые события являются источником истины.
Индикаторы и графики являются воспроизводимыми производными.
UI только отображает состояние и никогда не владеет историей.
```

---

## 2. Общая схема системы

Схема ниже — не пожелание, а описание принятого и работающего стека.

```text
Один процесс FastAPI
  ├── MarketDataHub            публичные потоки, reconnect, книга, сырьё
  ├── normalizer/deduplicator  нормализация и дедупликация
  ├── materialized order book  текущий стакан в памяти
  ├── aggregation engine       Footprint, Delta, CVD, профиль, tiles
  ├── historical REST API      committed-история наружу
  ├── frontend WS gateway      раздача кадров браузеру
  └── data-quality monitoring  состояние данных и разрывы

Parquet
  ├── сырые биржевые события
  ├── закрытые агрегаты
  ├── book checkpoints
  ├── manifest и индексы
  └── метаданные разрывов и checkpoint'ов

Память
  ├── текущий стакан
  ├── live-tail (ещё не изданное)
  ├── ограниченные очереди приёма
  ├── текущие агрегаты
  └── раздача подписчикам

localStorage
  └── версионированные настройки интерфейса
```

ClickHouse, TimescaleDB, Redis и IndexedDB — **возможные средства
будущего масштабирования, а не требования корректности.** Отсутствие
любого из них не является отступлением от этого документа; переход к ним
оправдан только фактическими проблемами, перечисленными в разделе 30.

### Три независимые роли

Разделение по времени жизни, а не по слоям кода. Рынок, представление и
аккаунт живут разное время и умирают по разным причинам.

```text
MarketDataHub
  ключ:        venue + category + symbol
  время жизни: пока работает сервер
  отвечает за: публичные потоки Bybit, reconnect и backfill,
               стакан, запись сырья, разрывы и качество данных

ViewSession
  ключ:        клиент/рабочее место + symbol + timeframe + настройки
  время жизни: пока открыт клиент
  отвечает за: выбранный таймфрейм, шаг цены, видимый диапазон,
               набор показанных модулей, подписку на готовые агрегаты

ExecutionHub
  ключ:        аккаунт / UID
  время жизни: пока работает сервер
  отвечает за: приватный WebSocket, ордера, исполнения, позиции,
               сверку с биржей, долговечный order journal
```

`PrivateFeed` **не должен принадлежать `MarketDataHub`:** он привязан к
аккаунту, а не к рынку. Смена инструмента не имеет к нему отношения, и
переподключать приватный поток вместе с рыночным — значит терять
состояние ордеров на ровном месте.

Смена таймфрейма относится только к `ViewSession`. Она не должна
переподключать WebSocket, очищать серверное сырьё или трогать стакан.

---

## 3. Классы данных

Все данные нужно заранее разделить на четыре класса.

| Класс | Примеры | Способ хранения |
|---|---|---|
| Сырые события | сделки, ликвидации, order-book delta | append-only хранилище |
| Текущее состояние | актуальный стакан, позиция, активные ордера | snapshot + journal |
| Производные данные | Footprint, Delta, VWAP, Heatmap tiles, OFI | пересчитываемый кеш |
| Настройки | ТФ, цвета, price step, фильтры | серверное хранилище + локальный кеш |

Производные данные можно удалить и пересчитать. Сырые данные удалять
нельзя, пока они входят в требуемый период истории или бэктеста.

### Каноническая числовая модель

Для всего, что сохраняется и участвует в повторе, **двоичный
floating-point запрещён.**

```text
цена        → priceTicks: int64
количество  → qtySteps: int64 или Decimal128
объём книги → qtySteps: int64 или Decimal128
turnover    → масштабированное целое или Decimal128
OI          → масштабированное целое или Decimal128
funding     → Decimal128
накопители VWAP → целочисленные или Decimal128
```

`float` допустим только в интерфейсе и в некритичных визуальных
вычислениях. Причина не в педантизме: из цены считается ключ ценовой
корзины, а два прогона на одних данных обязаны давать один ключ.

### Защита цикла событий

PyArrow, уплотнение и тяжёлая агрегация выполняются в одном процессе с
приёмом данных, поэтому обязаны не блокировать асинхронный цикл.

```text
ограниченные очереди приёма
отдельные задачи записи
вынос PyArrow и тяжёлых агрегатов в поток или процесс
метрики: глубина очереди, отставание очереди
явная политика при переполнении: block / drop / degrade
корректное завершение с flush и commit
восстановление при старте
```

Молчаливая потеря событий из-за занятого цикла неотличима от разрыва
связи, но, в отличие от него, не помечается ничем.

---

## 4. Источники Bybit

Для BTCUSDT linear perpetual используются:

```text
publicTrade.BTCUSDT
orderbook.{1|50|200|1000}.BTCUSDT
allLiquidation.BTCUSDT
tickers.BTCUSDT
private execution stream
private order stream
private position stream
```

### Сделки

Публичная лента содержит время, цену, объём, сторону taker, trade ID и
`seq`. Один `seq` может встретиться в нескольких сообщениях, поэтому
уникальность обеспечивается через `category + symbol + tradeId`, а не
через `seq`.

**`turnoverQuote` в потоке отсутствует** — это вычисляемое поле
`price × size`, и хранить его как пришедшее с биржи нельзя.
[Bybit Public Trade](https://bybit-exchange.github.io/docs/v5/websocket/public/trade)

### Стандартный стакан

Допустимые глубины и частоты для linear:

| Глубина | Частота | Замечание |
|---|---|---|
| 1 | 10 мс | только snapshot |
| 50 | 20 мс | ближняя книга, DOM, OBI |
| 200 | 100 мс | средняя глубина |
| 1000 | 200 мс | глубокая Heatmap и стены |

```typescript
type StandardBookDepth = 1 | 50 | 200 | 1000;
```

Стакан передаётся как `snapshot` и последующие `delta`; новый snapshot
полностью заменяет локальное состояние соответствующей глубины. `cts`
содержит время matching engine.

**Не считать `u` и `seq` непрерывными по правилу «предыдущий + 1».** Для
стандартного стакана Bybit описывает `seq` как cross sequence для
порядка и сравнения, но непрерывности не гарантирует. Контроль разрывов
обязан быть привязан к конкретному потоку и учитывать: обрыв и
переподключение, переподписку, новый snapshot, сброс `u=1`, регресс
последовательности, аномальную тишину и гарантии именно выбранного
feed'а.
[Bybit Order Book](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)

### RPI-стакан

Обычный публичный стакан **не включает RPI-ликвидность.** Опционально
доступен отдельный поток:

```text
orderbook.rpi.BTCUSDT   L50, 100 мс
```

Он содержит non-RPI и RPI размер раздельно. Если он не используется,
Heatmap обязана быть подписана как `standard API-visible liquidity only`
— иначе картинка обещает полноту, которой у неё нет.
[Bybit RPI Order Book](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook-rpi)

### Full Orderbook

Существует отдельный Full Orderbook feed. **Переключать на него
рабочий коллектор автоматически нельзя:** алгоритм синхронизации
отличается от стандартного snapshot/delta, а доступность нужно
проверять для конкретной категории и окружения. После фактического
включения для BTCUSDT linear потребуются отдельный адаптер, отдельные
тесты последовательности и восстановления и проверка выката на mainnet.
[Bybit Full Orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/full-ob)

### Ликвидации

Поток публикуется с частотой 500 мс, `data` приходит **массивом**.
У события **нет биржевого идентификатора и `seq`,** поэтому точная
дедупликация через переподключение невозможна: после обрыва нужен
liquidation gap marker.
[Bybit All Liquidation](https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation)

### Ticker

Linear ticker — поток **snapshot и delta.** Отсутствие поля в delta
означает «не изменилось», а не «пусто»: заменять его `null` или нулём
нельзя. Нужно материализованное состояние тикера.
[Bybit Ticker](https://bybit-exchange.github.io/docs/v5/websocket/public/ticker)

### REST recent trades

Возвращает не более 1000 последних сделок и **не имеет курсора,
`start` или `end`.** Годится для короткого backfill, но закрытие
длинного разрыва не гарантирует и собственный коллектор не заменяет.
[Bybit Recent Public Trades](https://bybit-exchange.github.io/docs/v5/market/recent-trade)

---

## 5. Нормализованные структуры событий

### 5.1. Сделка

```typescript
interface RawTrade {
  venue: "BYBIT";
  category: "linear";
  symbol: "BTCUSDT";

  tradeId: string;
  sequence: bigint;              // не непрерывен, для порядка
  exchangeTimestampMs: number;   // trade.T
  outerTimestampMs: number;      // ts сообщения
  receiveTimestampMs: number;

  priceTicks: bigint;
  qtySteps: bigint;
  takerSide: "Buy" | "Sell";

  isBlockTrade: boolean;         // BT
  isRpiTrade: boolean;           // RPI
}
```

Уникальный ключ:

```text
BYBIT:linear:BTCUSDT:<tradeId>
```

`turnoverQuote` в структуре нет намеренно: биржа его не присылает, это
вычисляемое `price × size`. Хранить вычисленное рядом с сырьём — значит
однажды получить два несовпадающих ответа на один вопрос.

Цена и количество хранятся целыми (см. раздел 3). Floating-point цена не
используется как ключ `Map` ни при каких условиях.

### 5.2. Order-book delta

```typescript
interface RawBookEvent {
  venue: "BYBIT";
  category: "linear";
  symbol: string;
  depth: StandardBookDepth;      // 1 | 50 | 200 | 1000
  connectionId: string;          // эпоха соединения

  type: "snapshot" | "delta";

  updateId: bigint;              // u
  sequence: bigint;              // seq, не непрерывен
  exchangeTimestampMs: number;   // cts, время matching engine
  outerTimestampMs: number;      // ts сообщения
  receiveTimestampMs: number;
  schemaVersion: number;

  bids: Array<[priceTicks: bigint, qtySteps: bigint]>;
  asks: Array<[priceTicks: bigint, qtySteps: bigint]>;
}
```

`connectionId` обязателен: история книги достоверна только внутри одной
эпохи соединения, и без него два потока после переподключения в записи
неотличимы.

### 5.3. Ликвидация

Поле `positionSide: Buy | Sell` двусмысленно и запрещено. Сторона
раскладывается на три однозначных:

```typescript
interface RawLiquidation {
  symbol: string;

  rawSide: "Buy" | "Sell";                    // поле S как пришло
  liquidatedPositionSide: "Long" | "Short";   // чью позицию закрыли
  inferredForcedFlow: "Buy" | "Sell";         // куда пошёл поток

  bankruptcyPriceTicks: bigint;               // не цена исполнения
  quantitySteps: bigint;

  exchangeTimestampMs: number;
  outerTimestampMs: number;
  receiveTimestampMs: number;
}
```

Нормализация:

```text
S=Buy  → ликвидирована Long-позиция  → inferredForcedFlow = Sell
S=Sell → ликвидирована Short-позиция → inferredForcedFlow = Buy
```

`p` — цена банкротства, а не фактическая цена исполнения; подписывать её
как цену сделки нельзя.

### 5.4. Технический envelope

Каждое событие оборачивается в технические поля:

```typescript
interface EventEnvelope<T> {
  eventId: string;
  schemaVersion: number;
  collectorId: string;
  connectionId: string;
  receivedAtMs: number;
  payload: T;
}
```

Это позволяет отлаживать дубли, переподключения и миграции формата.
`collectorId` и `connectionId` записываются в момент приёма и задним
числом не восстанавливаются.

---

## 6. Модуль Raw Trades и лента сделок

### Источник истины

`publicTrade.BTCUSDT`.

### Что хранить

- каждую уникальную сделку;
- exchange timestamp, outer timestamp и local receive timestamp;
- trade ID и sequence;
- taker side;
- цену в тиках и количество в шагах;
- признаки block и RPI.

### Восстановление — два разных сценария

Их нельзя путать: у коллектора и у браузера разные источники и разные
права.

**Перезапуск или переподключение коллектора**

```text
1.  Открыть Bybit WebSocket в режиме буферизации.
2.  Загрузить durable checkpoint и live-tail/WAL.
3.  Выполнить REST recent-trades backfill.
4.  Объединить хранилище + REST + буфер сокета.
5.  Дедуплицировать по category + symbol + tradeId.
6.  Доказать перекрытие между сохранённым и восстановленным.
7.  Перекрытия нет — поставить trade gap marker.
8.  Для стакана дождаться нового snapshot.
9.  Выполнить warm-up.
10. Перейти в LIVE_READY.
```

Шаг 6 — не формальность. REST отдаёт максимум 1000 последних сделок и не
принимает курсор или диапазон, поэтому длинный разрыв им не закрывается.
Пока перекрытие не доказано, участок считается неполным, и честнее
поставить маркер, чем склеить молча.

**Перезагрузка браузера**

```text
1. Загрузить версионированные настройки из localStorage.
2. Подключить WebSocket FastAPI в режиме буфера/курсора.
3. Запросить историю и агрегаты через REST FastAPI.
4. Объединить REST-историю и буфер сокета.
5. Выполнить series.setData(history).
6. Перейти на live-обновления.
```

Браузер **не должен**: подключаться к публичному сокету Bybit, делать
REST-backfill у Bybit, самостоятельно восстанавливать стакан, открывать
приватные потоки. Всё это делает сервер, и только он.

### Смена ТФ

Не влияет на Raw Trades. Переподключение запрещено.

### Проверки

```text
tradeId уникален внутри category + symbol
priceTicks > 0
qtySteps > 0
exchangeTimestamp не уходит назад без маркировки out-of-order
```

---

## 7. Модуль Footprint

### Источник истины

Сырые сделки, а не OHLCV-свечи.

### Структура

```typescript
interface FootprintLevel {
  priceTicks: bigint;
  bidVolume: number;       // агрессивные Sell
  askVolume: number;       // агрессивные Buy
  delta: number;
  totalVolume: number;
  tradeCount: number;
}

interface FootprintBar {
  symbol: string;
  timeframeMs: number;
  priceStepTicks: bigint;
  startTimeMs: number;
  endTimeMs: number;

  openTicks: bigint;
  highTicks: bigint;
  lowTicks: bigint;
  closeTicks: bigint;

  buyVolume: number;
  sellVolume: number;
  delta: number;
  totalVolume: number;
  levels: FootprintLevel[];

  status: "building" | "provisional" | "final";
  dataVersion: number;
}
```

### Формулы

```text
Ask Volume = сумма taker Buy
Bid Volume = сумма taker Sell
Level Delta = Ask Volume - Bid Volume
Bar Delta = сумма Level Delta
```

### Восстановление

- загрузить raw trades нужного диапазона;
- загрузить кеш Footprint той же версии;
- проверить checksum или `lastProcessedTradeId`;
- пересчитать последний незакрытый и 1–2 предыдущих бара;
- применить WebSocket buffer;
- передать полную историю в `series.setData()`;
- затем использовать `series.update()`.

### Смена ТФ

ТФ меняет только размер временного bucket:

```typescript
barStart = Math.floor(timestampMs / timeframeMs) * timeframeMs;
```

Ключ агрегата:

```text
symbol + timeframe + priceStep + sessionTimezone + algorithmVersion
```

### Инварианты

```text
buyVolume + sellVolume = totalVolume
buyVolume - sellVolume = delta
sum(level.totalVolume) = totalVolume
sum(level.delta) = bar.delta
```

---

## 8. Модули Delta и CVD

### Источник истины

Сырые сделки.

### Формулы

```text
TradeSign = +1 для taker Buy, -1 для taker Sell
Delta(bar) = sum(TradeSign × Quantity)
CVD(n) = CVD(n - 1) + Delta(n)
```

### Обязательная настройка якоря CVD

```yaml
cvd:
  reset_mode: utc_session
  reset_hour_utc: 0
```

Допустимые режимы:

- UTC day;
- пользовательская сессия;
- выбранный диапазон;
- continuous.

Режим должен входить в ключ кеша. Иначе один CVD будет ошибочно использован для разных якорей.

### Восстановление

Для CVD нельзя загрузить только последний бар без начального значения. Нужен один из вариантов:

1. Пересчитать Delta от начала якорной сессии.
2. Сохранить checkpoint `cvdBeforeRange` и продолжить от него.

### Смена ТФ

Delta пересчитывается для нового bucket. CVD затем строится из Delta нового ТФ. Нельзя просто растягивать старый массив по новой временной шкале.

### Проверка

```text
Delta(5m) = сумма Delta пяти выровненных 1m баров
Последний CVD = начальный CVD + сумма всех Delta
```

---

## 9. Модуль текущего стакана

### Источник истины

Последний корректный snapshot и непрерывная цепочка delta **внутри одной
эпохи соединения.**

### Правила обработки

```text
snapshot → полностью очистить локальный стакан → установить snapshot
delta size > 0 → вставить или обновить уровень
delta size = 0 → удалить уровень
нарушение порядка → признать стакан невалидным
новый snapshot → заменить состояние
переподключение → новая эпоха соединения
```

Контроль порядка привязан к потоку и не опирается на «предыдущий + 1»
(см. раздел 4). Валидатор обязан различать пропуск, сброс `u=1`, регресс
последовательности и смену эпохи соединения — это разные события с
разными последствиями.

### Хранение

Нужно хранить отдельно:

- текущий materialized order book;
- периодические checkpoints;
- **все полученные sparse delta** внутри эпохи (см. раздел 10);
- `connectionId` и последовательность последнего события.

```typescript
interface BookCheckpoint {
  venue: string;
  category: string;
  symbol: string;
  depth: StandardBookDepth;
  connectionId: string;

  timestampMs: number;
  updateId: bigint;
  sequence: bigint;
  schemaVersion: number;

  stale: boolean;
  staleReason: string;

  bids: Array<[bigint, bigint]>;
  asks: Array<[bigint, bigint]>;
}
```

### Reload и reconnect

Сохранённый стакан **нельзя считать актуальным после разрыва.** Он
годится для мгновенного предварительного показа с пометкой `STALE`, но
торговые сигналы запрещены до нового snapshot и warm-up.

```text
reload
→ показать сохранённый стакан как STALE
→ подключить WebSocket
→ дождаться snapshot
→ заменить стакан целиком
→ выполнить warm-up
→ разрешить сигналы
```

Стакан, помеченный `stale`, не берётся в основу повтора: катить дельты от
книги, про которую известно, что она разошлась с биржевой, — значит
получить правдоподобные числа неизвестной верности.

### Смена ТФ

Текущий стакан не имеет таймфрейма. Смена ТФ не пересоздаёт ни его
хранилище, ни сокет.

---

## 10. Модуль Heatmap

### Источник истины

Историческая последовательность состояний стакана.

Один актуальный snapshot восстанавливает только текущий стакан. Прошедшую
Heatmap он не восстанавливает, поэтому её необходимо сохранять
самостоятельно.

### Что именно сохраняется

Формулировка «sparse book deltas» двусмысленна: `sparse` описывает
**формат сообщения**, а не прореженность данных. Точная формулировка:

```text
Lossless sequence of all received sparse delta messages
within subscribed depth and gap-free connection epoch
```

То есть **все полученные сообщения без исключения**, внутри подписанной
глубины и внутри эпохи соединения без разрывов.

Два источника, и путать их нельзя:

```text
Прореженные снимки глубины
→ визуальная Heatmap
→ восстановить каждое состояние книги по ним НЕЛЬЗЯ

Checkpoint + каждая полученная дельта
→ воспроизводимая книга подписанной глубины
→ только между gap-маркерами
```

История восстановима только: в пределах подписанной глубины, от валидного
checkpoint или snapshot, внутри эпохи соединения без разрывов, без
претензии на полный биржевой стакан и с учётом того, что RPI в
стандартный feed не входит.

### Модель хранения

```text
Periodic Book Checkpoint
+
Every received delta within the epoch
+
Precomputed Heatmap Tiles
```

```typescript
interface HeatmapTile {
  symbol: string;
  startTimeMs: number;
  endTimeMs: number;
  timeResolutionMs: number;
  priceStepTicks: bigint;

  cells: Array<{
    timeBucket: number;
    priceBucketTicks: bigint;
    bidLiquidity: number;
    askLiquidity: number;
    estimatedExecutedBid: number;
    estimatedExecutedAsk: number;
    attributionConfidence: number;   // 0..1
  }>;

  dataVersion: number;
}
```

Поля исполнения названы `estimated*` намеренно: публичная книга
агрегирована по цене, и отделить исполнение от отмены точно невозможно
(раздел 14). Величина без пометки оценочности читается как факт — это и
есть та самая тихая ложь, которую документ запрещает.

### Временная агрегация

```yaml
heatmap:
  time_resolution_ms: 250
  price_step_ticks: 5
  checkpoint_interval_ms: 10000
```

При смене свечного ТФ Heatmap не исчезает. Меняется только визуальная
детализация; данные запрашиваются по диапазону времени.

### Разрыв данных

Order-book gap невозможно честно заполнить задним числом через REST.
Нужно: поставить gap marker, не интерполировать неизвестную ликвидность,
обнулить признаки OFI и refill на границе, запретить сигналы до нового
snapshot и warm-up.

### Retention

```text
сырые book deltas: 1–7 дней
checkpoints:       7–30 дней
heatmap tiles:     30–180 дней
```

Сроки зависят от диска и требуемой глубины бэктеста. **Ретенция по срокам,
а не только по размеру:** предел в мегабайтах защищает диск, но не
отвечает на вопрос «за какой период у нас есть данные».

Порядок сроков задаёт зависимость: tiles живут дольше сырья, из которого
считаются. Значит всё, что нужно в tiles, обязано попасть в них **до**
истечения срока сырья — иначе досчитать будет неоткуда.

---

## 11. Модуль Volume Profile

### Источник истины

Сырые сделки.

### Расчёт

```text
VolumeAtPrice[priceBucket] += trade.quantity
BuyVolumeAtPrice += quantity для taker Buy
SellVolumeAtPrice += quantity для taker Sell
DeltaAtPrice = BuyVolumeAtPrice - SellVolumeAtPrice
```

### Типы профиля

- Visible Range;
- Fixed Range;
- UTC Session;
- Daily/Weekly;
- Anchored;
- Composite.

Тип профиля и anchor входят в cache key:

```text
symbol + profileType + from + to + priceStep + version
```

### POC и Value Area

```text
POC = price bucket с максимальным объёмом
Value Area = диапазон, содержащий заданную долю объёма
```

Рекомендуемое значение по умолчанию:

```yaml
value_area_percent: 70
```

### Reload и смена ТФ

Профиль не должен зависеть от компонента свечей. Visible Range пересчитывается при изменении видимого диапазона, а session/fixed profile загружается из кеша или raw trades.

---

## 12. Модуль VWAP

### Источник истины

Сырые сделки или корректные агрегаты `price × volume`.

### Формула

```text
VWAP = sum(TradePrice × TradeVolume) / sum(TradeVolume)
```

Для точного продолжения после reload сохраняются накопители:

```typescript
interface VwapCheckpoint {
  anchorId: string;
  cumulativePriceVolume: number;
  cumulativeVolume: number;
  cumulativeVarianceState: object;
  lastTradeId: string;
}
```

### Якоря

- UTC day;
- week;
- пользовательское время;
- high/low события;
- начало импульса;
- начало liquidation cascade.

Anchor обязательно входит в cache key.

### Смена ТФ

VWAP не должен менять математическое значение из-за смены ТФ, если anchor и диапазон одинаковы. Меняется только частота точек отображения.

---

## 13. OFI, MLOFI, imbalance и microprice

### Источник истины

Последовательность валидных состояний стакана.

### Простое imbalance

```text
BookImbalance = (BidDepth - AskDepth) / (BidDepth + AskDepth)
```

### Microprice

```text
Microprice =
  (BestAsk × BidSize + BestBid × AskSize)
  / (BidSize + AskSize)
```

### OFI

OFI строится из изменений лучшего Bid/Ask и их размеров. MLOFI расширяет расчёт на несколько уровней.

### Хранение

Необязательно хранить каждый рассчитанный microprice. Достаточно:

- raw book deltas;
- book checkpoints;
- агрегированных feature bars для быстрого отображения и бэктеста.

```typescript
interface OrderFlowFeatureBar {
  startTimeMs: number;
  resolutionMs: number;
  meanImbalance: number;
  maxAbsImbalance: number;
  meanMicropriceEdgeBps: number;
  ofi: number;
  mlofi: number[];
  validSampleRatio: number;
}
```

### Reload

После нового snapshot нужны warm-up события. Нельзя сравнивать первый новый snapshot с последним стаканом до disconnect.

```yaml
order_flow:
  warmup_ms_after_snapshot: 3000
  minimum_valid_samples: 20
```

### Смена ТФ

Вычислительный resolution OFI может быть 100–1000 мс и не обязан совпадать со свечным ТФ. Свечной ТФ влияет только на последующую агрегацию признаков.

---

## 14. Sweep, absorption, refill и liquidity pull

Это не сырые данные, а события feature engine.

### Sweep

Хранить:

```typescript
interface SweepEvent {
  eventId: string;
  symbol: string;
  side: "Buy" | "Sell";
  startTimeMs: number;
  endTimeMs: number;
  startPriceTicks: bigint;
  endPriceTicks: bigint;
  levelsCrossed: number;
  aggressiveVolume: number;
  delta: number;
  configurationVersion: string;
}
```

### Absorption

```typescript
interface AbsorptionEvent {
  eventId: string;
  zoneLowTicks: bigint;
  zoneHighTicks: bigint;
  startTimeMs: number;
  endTimeMs: number;
  aggressiveVolume: number;
  priceDisplacementTicks: number;
  impactEfficiency: number;
  refillRatio: number;
  score: number;
  configurationVersion: string;
}
```

### Refill и pull

Нужно различать:

```text
executed liquidity — объём действительно прошёл в сделках
cancelled liquidity — объём исчез без исполнения
refilled liquidity — объём восстановился после исполнения
```

Сопоставление trades и book updates выполняется по exchange timestamp/sequence с допустимым временным окном.

### Атрибуция оценочна, и это обязано быть видно

Публичная книга агрегирована по цене: исчезнувший размер означает
**«исполнено или отменено»**, и разделить эти два случая точно
невозможно. Поэтому величины называются так, как они посчитаны:

```text
executedEstimated
cancelledEstimated
refilledEstimated
attributionConfidence ∈ [0, 1]
```

Сопоставление строится преимущественно по:

```text
book.cts ↔ trade.T
цена
сторона
окно по объёму
```

**Связывать book и trade через `seq` нельзя:** официальной гарантии
такого соответствия нет, и опираться на него — значит строить признак на
недокументированном поведении.

При низкой `attributionConfidence`:

- сигналы absorption и refill блокируются;
- feature bar помечается как degraded;
- данные не используются для торгового решения;
- причина низкой уверенности сохраняется вместе с величиной.

Без последнего пункта «низкая уверенность» через неделю превращается в
необъяснимое число.

### Reload

События можно:

1. Загружать как сохранённые результаты с `configurationVersion`.
2. Пересчитывать из raw trades и book history.

Если версия алгоритма изменилась, старый кеш должен быть признан устаревшим.

### Смена ТФ

Sweep и absorption являются событиями, а не свечами. При смене ТФ они остаются на тех же timestamp и только привязываются к другому визуальному бару.

---

## 15. Модуль ликвидаций

### Источник истины

`allLiquidation.BTCUSDT`.

### Хранение

- каждую ликвидацию;
- три поля стороны из раздела 5.3, а не двусмысленное `positionSide`;
- цену банкротства;
- объём;
- exchange, outer и receive timestamps.

### Производные агрегаты

```text
Liquidation Volume 1s/5s/1m
longLiquidatedVolume     (ликвидированы длинные позиции)
shortLiquidatedVolume    (ликвидированы короткие)
Liquidation Delta
Liquidation Z-score
Cascade ID
```

Прежние названия `Buy Liquidations` и `Sell Liquidations` запрещены: из
них не следует, чью позицию закрыли и куда пошёл принудительный поток.

### Reload

Загрузить сохранённые ликвидации и продолжить поток. **У события нет
биржевого идентификатора,** поэтому дедупликация через переподключение
невозможна: после обрыва ставится liquidation gap marker. Придумывать
пропущенные ликвидации по свечам запрещено.

### Смена ТФ

Пересчитать агрегацию из сырых событий. Сами события сохраняются.

---

## 16. Open Interest, funding, mark и index

Эти данные используются как контекст и фильтр режима.

### Откуда что берётся

| Величина | Источник |
|---|---|
| живой `openInterest` и `openInterestValue` | ticker WebSocket |
| исторический open interest | Open Interest REST |
| `fundingInterval` | Instruments Info |
| фактическая история фандинга | Funding History REST |
| текущая ставка и время следующего расчёта | ticker WebSocket |

Разделение существенное: ставка в ticker — **прогноз**, он меняется до
самого расчёта; Funding History отдаёт то, что действительно списали.
Одно другое не заменяет.

```typescript
interface OpenInterestSample {
  symbol: string;
  timestampMs: number;
  openInterest: number;
  openInterestValue: number;
}
```

### Материализация ticker

Ticker приходит snapshot'ом и дельтами. Отсутствие поля в дельте означает
«не изменилось». Записывать в этом случае `null` или ноль — значит
испортить ряд: нужно материализованное состояние, из которого дельта
обновляет только присутствующие поля.

### Смена ТФ

Эти ряды ресэмплируются по правилу `last known value`, `open/close` или
изменению за интервал. Очищать их при смене свечного ТФ нельзя.

[Bybit Open Interest](https://bybit-exchange.github.io/docs/v5/market/open-interest) ·
[Bybit Funding History](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) ·
[Bybit Instruments Info](https://bybit-exchange.github.io/docs/v5/market/instrument)

---

## 17. Свечи OHLCV

Свечи можно получать с Bybit или строить из raw trades.

Для визуального восстановления допустим REST Kline, но Footprint и Delta
из него восстановить нельзя: OHLCV не содержит taker side и распределения
объёма по ценам.

### Особенности REST bootstrap

```text
Bybit отдаёт свечи от новых к старым — перед setData() сортировать по возрастанию
последняя свеча не закрыта, её close меняется
незакрытую свечу нельзя сравнивать как окончательную
```

Пренебрежение первым пунктом даёт график, нарисованный задом наперёд;
пренебрежение третьим — ложные data-quality alert на каждой минуте.

Рекомендуется:

```text
Bybit Kline → быстрый bootstrap и контроль
Raw Trades → собственные canonical candles
```

Проверка:

```text
собственные OHLCV сравниваются с закрытыми свечами Bybit
расхождение выше tolerance создаёт data-quality alert
```

[Bybit Kline](https://bybit-exchange.github.io/docs/v5/market/kline)

---

## 18. Стратегические сигналы

Сигнал должен быть сохранён как объяснимое событие, а не только как метка на графике.

```typescript
interface StrategySignal {
  signalId: string;
  strategyId: string;
  strategyVersion: string;
  configurationVersion: string;

  symbol: string;
  side: "Long" | "Short";
  detectedAtMs: number;
  expiresAtMs: number;

  referencePriceTicks: bigint;
  proposedEntryTicks: bigint;
  proposedStopTicks: bigint;
  proposedTargetsTicks: bigint[];

  featureSnapshot: Record<string, number | string | boolean>;
  marketDataQuality: {
    tradeAgeMs: number;
    bookAgeMs: number;
    hasBookGap: boolean;
  };

  state:
    | "detected"
    | "confirmed"
    | "expired"
    | "cancelled"
    | "submitted"
    | "filled"
    | "rejected";
}
```

После reload приложение должно восстановить сигналы, но не исполнять просроченные:

```text
currentTime > expiresAtMs → EXPIRED
```

---

## 19. Ордера, исполнения и позиции

Этот модуль нельзя восстанавливать из браузерного состояния.

Источник истины:

```text
Bybit private WebSocket
+
REST reconciliation
+
durable order journal на сервере
```

### Order journal

```typescript
interface OrderJournalRecord {
  localCommandId: string;
  orderLinkId: string;
  exchangeOrderId?: string;
  signalId?: string;
  command: "create" | "amend" | "cancel";
  requestedAtMs: number;
  acknowledgedAtMs?: number;
  status: string;
  payloadHash: string;
}
```

Журнал хранится **на сервере** — в WAL или атомарно публикуемых
микросегментах. Браузер, `localStorage` и незакрытый `ParquetWriter` для
него не годятся. Команды идемпотентны через уникальный `orderLinkId`;
подтверждённые исполнения продвигают checkpoint.

### Восстановление при старте и переподключении

```text
1.  Запретить новые заявки.
2.  Подключить private WebSocket в режиме буферизации.
3.  Получить позиции.
4.  Получить активные ордера.
5.  Получить order history от durable checkpoint.
6.  Получить execution history от durable checkpoint.
7.  Объединить REST и буфер сокета.
8.  Дедуплицировать исполнения по category + symbol + execId.
9.  Сопоставить orderLinkId с order journal.
10. Проверить наличие server-side SL у каждой позиции.
11. Перейти в EXECUTION_READY.
```

Шаги 5 и 6 добавлены не для полноты: `/v5/order/realtime` **не является
архивом закрытых заявок**, и после перезапуска сервера восстановить по
нему историю нельзя. Приватный поток ордеров вдобавок может прислать два
`Filled` при гонке исполнения и отмены — дедупликация по `execId`
обязательна.

Локальное состояние не может считаться источником истины для позиции:
заявка могла исполниться, пока сервер был отключён.

[Bybit Open & Closed Orders](https://bybit-exchange.github.io/docs/v5/order/open-order) ·
[Bybit Private Order Stream](https://bybit-exchange.github.io/docs/v5/websocket/private/order) ·
[Bybit Execution History](https://bybit-exchange.github.io/docs/v5/order/execution)

---

## 20. Настройки модулей и оформление

Настройки не хранятся внутри компонента. Нужен отдельный versioned
preferences store.

```typescript
interface WorkspacePreferences {
  schemaVersion: number;
  workspaceId: string;
  symbol: string;

  timeframe: string;
  visibleRange: { fromMs: number; toMs: number };

  footprint: { enabled: boolean; mode: "bidAsk" | "delta" | "volume";
               priceStepTicks: number; imbalanceRatio: number;
               buyColor: string; sellColor: string; neutralColor: string };
  heatmap:   { enabled: boolean; timeResolutionMs: number;
               priceStepTicks: number; minLiquidity: number;
               colorScale: string[]; opacity: number };
  delta:     { enabled: boolean; positiveColor: string;
               negativeColor: string; showCvd: boolean; cvdResetMode: string };
  profile:   { enabled: boolean; type: string; valueAreaPercent: number;
               pocColor: string; valueAreaColor: string };
}
```

### Где что хранить

`localStorage` **разрешён** для: цветов, размеров панелей, видимости
модулей, последнего символа и ТФ, видимого диапазона, мелких фильтров
интерфейса. Обязательны `schemaVersion`, миграции, проверка повреждённых
значений и безопасные значения по умолчанию.

`localStorage` **запрещён** для: скриптов индикаторов, объектов разметки и
шаблонов инструментов. Это долговечные пользовательские артефакты —
единственные данные в системе, которых нет больше нигде. Рыночную историю
в худшем случае докачает биржа; уровень, проведённый по трём касаниям
полгода назад, не восстановит никто. Для них требуется серверное
версионированное хранилище либо, как минимум, экспорт, импорт, резервная
копия и миграции.

Файл настроек лежит **рядом с конфигурацией, а не в каталоге рыночных
данных:** там работает ретенция, а пользовательские данные под неё
попадать не должны ни при каких настройках — они не «старые», они просто
редко меняются.

IndexedDB для рыночной истории в принятой архитектуре **не нужен:**
историю отдаёт сервер.

Цвета, размеры панелей и видимость модулей сохраняются немедленно или с
задержкой 300–1000 мс.

---

## 21. Правильный bootstrap приложения

Два независимых сценария: сервер поднимает рынок, браузер поднимает
представление. Смешивать их нельзя — у браузера нет ни прав, ни причин
ходить к бирже.

**Коллектор (сервер)**

```text
BOOT
  ↓
LOAD_CONFIG
  ↓
OPEN_PUBLIC_SOCKETS_IN_BUFFER_MODE
  ↓
LOAD_CHECKPOINT_AND_LIVE_TAIL
  ↓
REST_BACKFILL_TRADES
  ↓
MERGE_AND_DEDUPLICATE
  ↓
PROVE_OVERLAP_OR_MARK_GAP
  ↓
WAIT_FOR_BOOK_SNAPSHOT
  ↓
WARM_UP
  ↓
LIVE_READY
  ↓
CONNECT_PRIVATE_STREAMS
  ↓
RECONCILE_ORDERS_AND_POSITIONS
  ↓
EXECUTION_READY
```

**Браузер**

```text
BOOT
  ↓
LOAD_PREFERENCES
  ↓
OPEN_FASTAPI_WS_IN_BUFFER_MODE
  ↓
LOAD_HISTORY_FROM_FASTAPI_REST
  ↓
MERGE_REST_AND_WS_BUFFER
  ↓
RENDER_HISTORY_WITH_SET_DATA
  ↓
APPLY_BUFFERED_EVENTS
  ↓
LIVE
```

Новые торговые сигналы разрешены только в `LIVE_READY`; отправка заявок —
только в `EXECUTION_READY`. Это два разных состояния: данные могут быть
исправны, пока сверка ордеров ещё не завершена.

---

## 22. Поведение при смене таймфрейма

```text
TIMEFRAME_CHANGE
  ↓
не трогать Bybit WebSocket
  ↓
не очищать серверное сырьё и состояние стакана
  ↓
запросить агрегат нового ТФ через FastAPI REST
  ↓
сохранить старый график до готовности нового набора
  ↓
series.setData(история нового ТФ)
  ↓
атомарно переключить подписку на live-агрегат
  ↓
series.update(живые бары)
```

Старое представление **не уничтожается, пока не готово новое.** Пустой
график на время пересчёта — это не «загрузка», а потеря контекста у
человека, который в этот момент смотрит на рынок. Если показать нечего,
показывается `loading overlay` поверх прежних данных.

### Запрещённый вариант

```typescript
useEffect(() => {
  setTrades([]);
  setFootprint([]);
  bookStore.clear();
  reconnectWebSocket();
}, [timeframe]);
```

### Правильная зависимость

```typescript
useEffect(() => {
  return marketDataService.subscribe(symbol);
}, [symbol]);

const view = useFootprintView({
  symbol,
  timeframe,
  priceStepTicks,
});
```

---

## 23. Cache keys и версии алгоритмов

Логическая идентичность производного набора:

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

Пример:

```text
BYBIT:linear:BTCUSDT:footprint:5m:5ticks:UTC:v3:cfg-a91f
```

Если меняется формула Delta, правила ценовой корзины или логика
absorption — растёт `algorithmVersion`, и кеш пересчитывается.

### Ревизия исходных данных

`dataRevision` **нельзя просто дописать в ключ**: получив новую ревизию,
читатель должен знать, какая из них последняя, иначе он найдёт обе и не
выберет. Допустимы два способа.

**Вариант A — стабильный ключ**

```text
logicalKey → value(sourceDataRevision = N)
```

Новая ревизия атомарно заменяет старую. Просто; истории ревизий нет.

**Вариант B — неизменяемый физический ключ**

```text
logicalKey:revision → неизменяемое значение
logicalKey          → указатель на последнюю ревизию
```

Дороже, но позволяет сослаться на конкретную ревизию — например, из
сохранённого сигнала, который на ней и сработал.

---

## 24. Watermark и late events

Событие может прийти позже своего момента: биржа шлёт потоки разными
соединениями, и сделка с временем 12:59:59.900 приезжает после сделки
13:00:00.100. Поэтому последний бар нельзя окончательно закрывать в точку
`barEnd`.

### Watermark считается по данным, а не по пингу клиента

Привязывать окно к клиентскому RTT неверно: клиент к приёму данных
отношения не имеет. Watermark вычисляется на серверном коллекторе по
запаздыванию событий:

```text
lateness       = receiveTimestamp - exchangeTimestamp
watermarkDelay = наблюдаемый p99 или p99.9 lateness + запас
```

Настройки **раздельные для каждого потока** — у сделок, книги, ликвидаций,
тикера и приватных исполнений разное запаздывание, и одно общее число
либо слишком мало для одного, либо слишком велико для всех:

```yaml
aggregation:
  trades:      { provisional_close_delay_ms: 1000, late_max_age_ms: 5000 }
  order_book:  { provisional_close_delay_ms: 500,  late_max_age_ms: 2000 }
  liquidations:{ provisional_close_delay_ms: 1000, late_max_age_ms: 5000 }
  mutable_closed_bars: 2
```

### Состояния бара

```text
BUILDING     → интервал ещё открыт
PROVISIONAL  → время прошло, но поздние события принимаются
FINAL        → бар зафиксирован
```

Если поздняя сделка попала в предыдущий бар: обновить Footprint и Delta,
пересчитать последующий CVD, обновить Volume Profile и VWAP, увеличить
`dataRevision`, отправить исправление клиенту.

### Событие после FINAL

Очень позднее событие **не меняет историю молча.** Допустимо только:

- создать новую `dataRevision` или патч; либо
- создать data-quality incident.

Отбросить событие, ничего не сообщив, — значит получить историю, которая
расходится с сырьём без следа.

Order-book gap обрабатывается иначе: неизвестное состояние стакана нельзя
восстановить поздней сделкой, поэтому участок помечается невалидным.

---

## 25. Принятый стек и пределы его применимости

Проектом принята серверная схема; браузерный прототип с IndexedDB и
Web Worker **не рассматривается** — сервер уже считает, браузер уже
только рисует.

```text
Один процесс FastAPI
+ Parquet как долговременное хранилище
+ агрегация на сервере
+ REST для истории и WebSocket для живых кадров
+ localStorage для настроек интерфейса
```

### Что эта схема решает

- данные собираются, пока браузер закрыт;
- история книги существует дольше одной вкладки;
- смена ТФ не трогает соединение с биржей;
- одно сырьё кормит любые агрегации;
- повтор воспроизводим.

### Чего она не решает

- сон или выключение машины останавливают сбор, и кодом это не лечится;
- один процесс — одна точка отказа;
- диапазонные запросы упираются в скорость чтения parquet.

### Когда переходить к другим хранилищам

Только по факту проблемы, а не заранее:

| Хранилище | Когда оправдано |
|---|---|
| ClickHouse | диапазонные запросы перестали укладываться в отклик |
| PostgreSQL/TimescaleDB | появились сигналы, ордера и несколько пользователей |
| Redis | нужен общий стакан между процессами |
| Object Storage | архив перерос локальный диск |
| IndexedDB | понадобилась работа браузера без сервера |

Отсутствие любого из них само по себе **не является отступлением от
этого документа.**

---

## 26. Контроль качества данных

```typescript
interface DataQualityState {
  status:
    | "BOOTSTRAP"     // поднимаемся, данных ещё нет
    | "LIVE_READY"    // данные исправны, сигналы разрешены
    | "DEGRADED"      // считать можно, но с оговоркой
    | "STALE"         // данные перестали приходить
    | "GAP"           // известен участок без данных
    | "REBUILDING";   // книга собирается заново

  collectorId: string;
  connectionId: string;

  tradesConnected: boolean;
  bookConnected: boolean;
  liquidationConnected: boolean;
  tickerConnected: boolean;

  tradeAgeMs: number;
  bookAgeMs: number;
  liquidationAgeMs: number;
  tickerAgeMs: number;

  tradeGap: boolean;
  bookGap: boolean;
  liquidationGap: boolean;
  tickerGap: boolean;

  duplicateRate: number;
  outOfOrderRate: number;

  lastTradeSequence?: bigint;
  lastBookSequence?: bigint;
  lastTradeId?: string;
  lastBookUpdateId?: bigint;

  attributionConfidence: number;
  queueDepth: number;
  queueLagMs: number;
  sourceDataRevision: number;
}
```

Стартовые ограничения:

```yaml
data_quality:
  max_trade_age_ms: 400
  max_book_age_ms: 400
  max_book_trade_skew_ms: 300
  max_websocket_silence_ms: 1000
  warmup_after_book_snapshot_ms: 3000
  minimum_valid_samples: 20
```

Пороги — стартовые, но **отступление от них объявляется явно.** Мягкий
порог, поставленный молча, превращает состояние в украшение: флаг,
который никогда не загорается, ничем не отличается от отсутствующего.

`GAP` выделен отдельно от `STALE` и `REBUILDING` намеренно. `STALE` —
данные не приходят сейчас; `REBUILDING` — книга собирается; `GAP` —
известно, что участок в прошлом потерян навсегда. Лечатся они по-разному,
и слив их в одно, различить причину уже нельзя.

При `STALE`, `GAP` и `REBUILDING` графики отображаются, но новые торговые
сигналы блокируются. Разрешены они только в `LIVE_READY`.

---

## 27. Обязательные тесты по модулям

### Reload test

```text
1. Собрать данные 10 минут.
2. Сохранить checksums.
3. Перезагрузить страницу.
4. Выполнить restore.
5. Сравнить checksums всех завершённых агрегатов.
```

### Timeframe round-trip

```text
1m → 5m → 15m → 1m
```

После возврата данные 1m должны быть идентичны.

### Footprint invariants

```text
buy + sell = total
buy - sell = delta
sum(level volume) = bar volume
sum(level delta) = bar delta
```

### Cross-timeframe invariants

```text
Volume(5m) = сумма пяти выровненных Volume(1m)
Delta(5m) = сумма пяти выровненных Delta(1m)
```

### VWAP invariants

```text
VWAP одного диапазона не меняется из-за смены визуального ТФ
```

### Parquet crash consistency

Падение проверяется в четырёх точках, потому что последствия у них
разные:

```text
падение до close
падение после close, до rename
падение после rename, до записи в manifest
падение после manifest, до продвижения checkpoint
```

Проверяется: незавершённый файл не публикуется как история; изданный
сегмент читается; manifest и checkpoint согласованы; восстановление не
создаёт дублей; live-tail закрывает текущий интервал.

### Trade recovery

```text
переподключение с перекрытием внутри 1000 REST-сделок
переподключение без перекрытия
одинаковый seq в нескольких сообщениях
дубликат tradeId
сделки не по порядку
gap marker при недоказанной полноте
```

### Book recovery

```text
новый snapshot заменяет книгу целиком
сброс u=1
переподключение открывает новую эпоху соединения
разрыв не интерполируется
checkpoint + дельты воспроизводят книгу подписанной глубины
прореженные снимки не объявляются полной историей
стандартный и RPI feed не смешиваются без явного правила
```

### Aggregation precision

```text
повторный прогон даёт идентичный checksum
расхождений из-за float нет
Delta(5m) = сумма Delta(1m)
VWAP не меняется от визуального ТФ
позднее событие создаёт новую ревизию
клиент получает последнюю ревизию
```

### Frontend

```text
перезагрузка не очищает историю
1m → 5m → 1m возвращает идентичный набор
Bybit WebSocket не перезапускается при смене ТФ
старый график остаётся до готовности нового
REST-история и буфер сокета не создают дублей
```

### Private execution

```text
дубликат Filled
гонка fill/cancel
исполнение во время обрыва
ордер на бирже без записи в журнале
позиция без защитного стоп-приказа
повтор команды с тем же orderLinkId
восстановление исполнений от checkpoint
```

### Deterministic replay

Одинаковый набор сырых событий и одинаковая конфигурация всегда дают
одинаковые Footprint, Delta/CVD, VWAP/Profile, события sweep/absorption и
стратегические сигналы.

### Честный прогон тестов

Пропущенный набор тестов **не должен завершаться сообщением «всё
зелёное».** Допустимы три исхода:

```text
PASS
FAIL
SKIPPED с явным числом и причиной
```

Прогон завершается ошибкой, если обязательный набор не был запущен.
Тест, которого никто не звал, ничем не отличается от пройденного, пока
его не пересчитать.

---

## 28. Типовые ошибки

### Данные находятся в состоянии React/Vue-компонента

Результат: исчезновение после unmount/reload.

### `key={timeframe}` на корневом chart-компоненте

Результат: полное уничтожение графика при смене ТФ.

### Cleanup вызывает `store.clear()`

Результат: навигация по интерфейсу удаляет историю.

### WebSocket зависит от timeframe

Результат: лишние reconnect, gaps и потеря текущего бара.

### Используется только `series.update()`

Результат: после пересоздания серии появляется только последний бар. Сначала нужен `setData(history)`, затем `update(liveBar)`.

### Footprint восстанавливается из OHLCV

Результат: математически недостоверная Delta и распределение по ценам.

### Старый стакан используется после reconnect

Результат: ложный OFI, refill и absorption.

### Кеш не содержит algorithm/config version

Результат: новые формулы смешиваются со старыми результатами.

### CVD не имеет определённого anchor

Результат: после reload линия начинается с другого значения.

---

## 29. Рекомендуемая структура проекта

```text
src/
  market-data/
    bybit/
      PublicTradeSocket
      OrderBookSocket
      LiquidationSocket
      PrivateSocket
      RestBackfillClient
    normalize/
      TradeNormalizer
      BookNormalizer
      LiquidationNormalizer
    quality/
      SequenceValidator
      GapDetector
      LatencyMonitor

  storage/
    RawTradeRepository
    BookEventRepository
    LiquidationRepository
    AggregateRepository
    CheckpointRepository
    PreferenceRepository
    OrderJournalRepository

  aggregation/
    TimeBucket
    PriceBucket
    CandleAggregator
    FootprintAggregator
    DeltaAggregator
    CvdAggregator
    HeatmapAggregator
    VolumeProfileAggregator
    VwapAggregator
    OfiAggregator

  features/
    SweepDetector
    AbsorptionDetector
    RefillDetector
    LiquidityPullDetector
    RegimeClassifier

  strategies/
    SweepFailureStrategy
    AbsorptionReversalStrategy
    BreakoutRetestStrategy
    LiquidationExhaustionStrategy
    RiskEngine

  state/
    MarketDataStore
    BookStore
    AggregateStore
    StrategyStore
    ExecutionStore
    PreferenceStore

  ui/
    charts/
      CandleChart
      FootprintChart
      DeltaChart
      HeatmapChart
      VolumeProfileChart
    panels/
      TapePanel
      OrderBookPanel
      StrategyPanel
      DataQualityPanel
```

---

## 30. План внедрения

Порядок задан не важностью модулей, а необратимостью потерь: сначала то,
чего нельзя добрать задним числом.

### P0. Непрерывность и целостность

```text
1. Запуск коллектора под supervisor/systemd
2. Health check и автоперезапуск
3. Канонические trade ID, timestamps, sequences
4. Целочисленная/Decimal числовая модель
5. Lossless сырьё: сделки и события книги
6. Атомарный commit-протокол Parquet
7. Manifest, schemaVersion, checkpoint, метаданные разрывов
8. Доказательство перекрытия при REST-backfill
9. Честный прогон тестов
```

### P1. Развязка

```text
1. MarketDataHub
2. ViewSession
3. ExecutionHub
4. Независимость подписки Bybit от таймфрейма
5. REST-история FastAPI + курсор/буфер во frontend WS
```

### P2. Агрегация и Heatmap

```text
1. Book checkpoints
2. Все полученные дельты внутри эпохи соединения
3. Heatmap tiles
4. Единая идентичность кеша и ревизии
5. Watermark по времени события
6. Оценочная атрибуция и attributionConfidence
```

### P3. Стратегии и исполнение

```text
1. Версионированные feature events
2. Объяснимый StrategySignal
3. Durable order journal
4. Сверка приватного состояния с биржей
5. Блокировка сигналов при плохих данных
6. Детерминированный повтор и event-driven backtest
```

### P4. Масштабирование — только по факту проблемы

Отдельные процессы, ClickHouse, TimescaleDB, Redis и объектное хранилище
рассматриваются, когда наступило одно из:

```text
диапазонные запросы перестали укладываться в отклик
приём данных блокируется обработкой
появилось много символов или пользователей
отказоустойчивости одного процесса не хватает
ретенцию или SLA нельзя выполнить текущими средствами
```

Пока ничего из этого не наступило, переход к ним — усложнение без
причины.

---

## 31. Критерии готовности

Изменения считаются внедрёнными, когда выполнено всё перечисленное.

```text
коллектор работает независимо от браузера
смена ТФ не меняет подписки Bybit
сделки дедуплицируются по category + symbol + tradeId
при недоказанном перекрытии создаётся trade gap
история книги ограничена подписанной глубиной и эпохами соединения
стандартный, RPI и Full order book не смешиваются неявно
открытый Parquet-файл не публикуется как история
checkpoint продвигается только после атомарного commit
REST отдаёт committed-историю плюс live-tail
повтор не зависит от ошибок floating-point
refill/cancel/fill имеют attributionConfidence
сторона ликвидации нормализована в Long/Short
дельта тикера материализуется корректно
браузер получает историю от сервера, а не от Bybit
localStorage имеет schemaVersion и миграции
пользовательские артефакты хранятся на сервере
приватное восстановление включает executions и order history
новые сигналы разрешены только в LIVE_READY и EXECUTION_READY
все обязательные наборы тестов действительно выполняются
```

### Итог

Ключевое остаётся неизменным: **REST-свечи не восстанавливают Footprint,
Delta или историческую Heatmap.** Footprint и Delta требуют истории
сделок со стороной тейкера, Heatmap — сохранённой последовательности
состояний стакана. Поэтому собственный непрерывный сборщик — не
оптимизация, а обязательная часть архитектуры.

Второе по важности: **величина без пометки оценочности читается как
факт.** Публичная книга агрегирована по цене, исполнение от отмены
отделить точно нельзя, и всё, что из этого выведено, обязано нести
`attributionConfidence` и причину, по которой уверенность низка.

---

## 32. Источники

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
