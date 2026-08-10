# Stage 3: Query API для чтения Parquet данных

## Цель

Создать REST API для чтения опубликованных Parquet сегментов.
Разблокирует визуализацию (Stage 4: Frontend).

---

## Требования из Roadmap

**§7 Query & Aggregation:**
- Чтение .parquet через PyArrow
- Фильтрация по временному диапазону (timestampUs)
- Server-side aggregation (OHLC, volume, counts)
- REST для исторических данных

**§4 Технологический стек:**
- FastAPI для REST endpoints
- Uvicorn для ASGI server
- Pydantic для request/response schemas

**all-modules-changes §2:**
- FastAPI-процесс с historical REST API
- Parquet как источник для query
- Memory для live-tail (опционально)

---

## Архитектура

```
Client (Frontend)
    ↓ HTTP GET /api/v1/trades?symbol=BTCUSDT&start=...&end=...
FastAPI Server
    ↓ ParquetReader.read_range()
PyArrow
    ↓ .parquet files
Storage (manifest.json + segments)
```

---

## Задачи

### P3-S3-001: ParquetReader

**Deliverable:** Класс `ParquetReader` для чтения Parquet сегментов.

**Функции:**
- `read_range(symbol, start_ts, end_ts)` → list[dict]
- Использует manifest.json для поиска релевантных сегментов
- Фильтрация по timestampUs через PyArrow filter
- Возвращает rows в хронологическом порядке
- Поддержка multiple segments (merge + sort)

**Тесты:** чтение одного/нескольких сегментов, фильтрация по времени, edge cases.

---

### P3-S3-002: FastAPI основа

**Deliverable:** Базовое FastAPI приложение с health check.

**Endpoints:**
- `GET /health` — health check (200 OK)
- `GET /api/v1/symbols` — список доступных symbols из manifest

**Зависимости:** 
- fastapi==0.115.6 (последняя stable)
- uvicorn[standard]==0.34.0 (ASGI server с HTTP/2)

**Структура:**
```
packages/api/
  __init__.py
  app.py         # FastAPI application
  router.py      # API routes
  models.py      # Pydantic request/response models
```

**Тесты:** запуск сервера через TestClient, health check endpoint.

---

### P3-S3-003: Trades Endpoint

**Deliverable:** `GET /api/v1/trades` для чтения RawTrade.

**Query params:**
- `symbol` (required): BTCUSDT
- `start_ts` (required): начало диапазона (microseconds, int64)
- `end_ts` (required): конец диапазона (microseconds, int64)
- `limit` (optional): max rows (default 1000, max 10000)
- `event_type` (optional): фильтр по eventType (RawTrade, BookCheckpoint)

**Response:**
```json
{
  "symbol": "BTCUSDT",
  "start_ts": 1786372648000000,
  "end_ts": 1786372650000000,
  "events": [
    {
      "timestampUs": 1786372648615000,
      "eventType": "RawTrade",
      "priceTicks": 647780,
      "qtySteps": 30,
      "sequence": 100,
      "exchangeTimestampMs": 1786372648615,
      "outerTimestampMs": 1786372648618,
      "receiveTimestampMs": 1786372648620
    }
  ],
  "count": 158,
  "has_more": false
}
```

**Error handling:**
- 400 Bad Request: invalid params (start_ts > end_ts, missing symbol)
- 404 Not Found: symbol не существует
- 500 Internal Server Error: ошибка чтения Parquet

**Тесты:** 
- Запрос trades из существующих .parquet файлов
- Фильтрация по временному диапазону
- Pagination с limit
- Error cases

---

### P3-S3-004 (опционально): OHLC Aggregation

**Deliverable:** `GET /api/v1/ohlc` для агрегированных candles.

**Query params:**
- `symbol`, `start_ts`, `end_ts`
- `interval`: 1m, 5m, 15m, 1h, 4h, 1d

**Response:**
```json
{
  "symbol": "BTCUSDT",
  "interval": "1m",
  "start_ts": 1786372620000000,
  "end_ts": 1786372680000000,
  "candles": [
    {
      "timestamp_us": 1786372620000000,
      "open_ticks": 647780,
      "high_ticks": 647850,
      "low_ticks": 647750,
      "close_ticks": 647800,
      "volume_steps": 1500,
      "trade_count": 45
    }
  ],
  "count": 1
}
```

**Aggregation:**
- Группировка по interval через floor(timestampUs / interval_us)
- OHLC: first, max, min, last priceTicks в каждом окне
- Volume: sum(qtySteps)
- Trade count: count(*)

---

## Приоритет

**P3-S3-001** → **P3-S3-002** → **P3-S3-003** → (P3-S3-004 опционально)

Начинаем с ParquetReader — базовая инфраструктура для чтения данных.

---

## Roadmap References

- §7: Query & Aggregation
- §4: FastAPI, Uvicorn
- all-modules-changes §2: FastAPI-процесс с REST API
- all-modules §5.2: REST endpoints для trades
