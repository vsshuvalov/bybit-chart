# Stage 2: Bybit WebSocket Adapter + Real Event Deserialization

## Цель

Подключиться к Bybit WebSocket, получать реальные события (RawTrade, BookCheckpoint), 
записывать в WAL → Parquet с полной десериализацией (замена stub из P1-S1-004).

---

## Задачи

### P2-S2-001: Bybit WebSocket Client (базовый)

**Deliverable:** Класс `BybitWebSocketClient` с подключением к `wss://stream.bybit.com/v5/public/linear`.

**Функции:**
- `connect()` — установка WebSocket соединения
- `subscribe(channel, symbol)` — подписка на канал (publicTrade.BTCUSDT, orderbook.200.BTCUSDT)
- `on_message(callback)` — обработка входящих сообщений
- Автоматический reconnect при разрыве соединения
- Ping/pong для keepalive

**Зависимости:** ADR-001 (выбор WS библиотеки) — можем начать с `websockets` (asyncio-native).

**Тесты:** mock WebSocket server, проверка subscribe/reconnect.

---

### P2-S2-002: Event Deserializer (RawTrade)

**Deliverable:** Функция `deserialize_raw_trade(ws_message) -> RawTrade`.

**Входные данные:** JSON от Bybit `publicTrade.BTCUSDT`.

**Выходные данные:** `RawTrade` из `contracts/schemas.py` с корректными:
- `priceTicks` / `qtySteps` (масштабированные целые)
- `exchangeTimestampMs` / `outerTimestampMs` / `receiveTimestampMs`
- `takerSide` (Buy/Sell)

**Тесты:** примеры JSON из Bybit docs → `RawTrade` → round-trip.

---

### P2-S2-003: Event Deserializer (BookCheckpoint)

**Deliverable:** Функция `deserialize_book_snapshot(ws_message) -> BookCheckpoint`.

**Входные данные:** JSON от Bybit `orderbook.200.BTCUSDT` (snapshot).

**Выходные данные:** `BookCheckpoint` с:
- `bids` / `asks` списками `RawBookLevel`
- `levelCount`, `coverageBps` (вычисляются из snapshot)
- `updateId`, `sequence`

**Тесты:** snapshot → `BookCheckpoint` → проверка покрытия.

---

### P2-S2-004: WAL Writer Integration

**Deliverable:** Метод `append_event(event: RawTrade | BookCheckpoint)` в collector.

**Функции:**
- Сериализация события в `bytes` (JSON или Protobuf stub)
- Вызов `wal.append(payload)`
- Batch commit по `GroupCommitPolicy`

**Замена stub:** Модификация `close_and_publish_segment()` — десериализация `Frame.payload` 
→ реальный `RawTrade`/`BookCheckpoint` → rows для Parquet.

---

### P2-S2-005: End-to-End Test

**Deliverable:** Интеграционный тест полного pipeline.

**Сценарий:**
1. Mock WebSocket с примерами Bybit JSON
2. Deserializer → `RawTrade`/`BookCheckpoint`
3. Append в WAL
4. Commit + roll + `close_and_publish_segment()`
5. Чтение .parquet → проверка row count и полей

---

## Приоритет

**Начать с P2-S2-001** (WebSocket client) — базовая инфраструктура для получения данных.

---

## Блокеры

- **ADR-001** (WS библиотека) — можем принять как DECIDED: `websockets` (asyncio).
- **ADR-002** (Protobuf wire format) — пока используем JSON для `Frame.payload` (достаточно для MVP).

---

## Roadmap References

- §5.6: RawTrade, BookCheckpoint схемы
- §8.2: Book reconstruction protocol
- all-modules §5.1: publicTrade normalization
