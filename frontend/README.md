# Bybit Chart Frontend

Простой HTML/JavaScript frontend для визуализации BTCUSDT trades через TradingView Lightweight Charts.

## Возможности

- 📊 **OHLC Candles** — визуализация candles из REST API
- ⚡ **Real-time controls** — выбор interval (1m-1d) и range (1h-7d)
- 📈 **Statistics** — candle count, volume, trades, price range
- 🎨 **Dark theme** — TradingView-style UI

## Использование

### 1. Запустить API сервер

```bash
cd /Users/vs/Desktop/bybit-chart

# Убедитесь, что есть данные (запустите live demo если нужно)
PYTHONPATH=/Users/vs/Desktop/bybit-chart .venv/bin/python examples/bybit_live_demo.py --duration 60 --output-dir /tmp/bybit-chart-data

# Запустите API
PYTHONPATH=/Users/vs/Desktop/bybit-chart .venv/bin/python packages/api/app.py
```

API будет доступен на `http://127.0.0.1:8000`

### 2. Открыть frontend

```bash
# Откройте в браузере
open frontend/index.html

# Или запустите простой HTTP server (для избежания CORS)
cd frontend
python3 -m http.server 8080
# Откройте http://localhost:8080
```

### 3. Загрузить данные

- Выберите **Interval** (1m, 5m, 15m, 30m, 1h, 4h, 1d)
- Выберите **Range** (1h, 6h, 24h, 3d, 7d)
- Нажмите **Load Data**

Chart загрузит OHLC candles из API и отобразит статистику.

## Архитектура

```
frontend/index.html
    ↓ HTTP GET /api/v1/ohlc
FastAPI Server (127.0.0.1:8000)
    ↓ ParquetReader.read_range()
Parquet files (/tmp/bybit-chart-data/BTCUSDT/)
```

## API Endpoints

- `GET /api/v1/symbols` — список доступных symbols
- `GET /api/v1/ohlc?symbol=BTCUSDT&start_ts=...&end_ts=...&interval=1m` — OHLC candles

## Конфигурация

Измените в `index.html` (строка ~157):

```javascript
const API_BASE_URL = 'http://127.0.0.1:8000/api/v1';
const SYMBOL = 'BTCUSDT';
```

## Требования

- **Браузер:** Chrome, Firefox, Safari (современные версии)
- **API:** FastAPI server должен быть запущен
- **Данные:** Parquet files должны существовать в `DATA_DIR`

## Технологии

- **TradingView Lightweight Charts 4.2.0** — chart library (CDN)
- **Vanilla JavaScript** — без фреймворков
- **CSS** — dark theme inspired by TradingView

## Roadmap

- [ ] WebSocket для live updates
- [ ] Volume histogram под candles
- [ ] Trade markers на chart
- [ ] Timeframe selector (zoom/pan)
- [ ] Export to CSV/JSON
- [ ] Multiple symbols support

## Screenshot

```
┌──────────────────────────────────────────────┐
│ Bybit Chart - BTCUSDT          [Interval ▼]  │
│                                 [Range ▼]     │
│                                 [Load Data]   │
├──────────────────────────────────────────────┤
│ Candles: 96    Volume: 123.456   Trades: 450 │
├──────────────────────────────────────────────┤
│                                              │
│         📊 TradingView Chart                 │
│            (OHLC Candles)                    │
│                                              │
└──────────────────────────────────────────────┘
```

## Troubleshooting

**CORS ошибка:**
```
Access to fetch at 'http://127.0.0.1:8000/...' from origin 'null' has been blocked by CORS
```

**Решение:** Запустите frontend через HTTP server:
```bash
cd frontend
python3 -m http.server 8080
```

**"No data available":**
- Убедитесь, что API запущен (`http://127.0.0.1:8000/health`)
- Проверьте, что есть данные: `http://127.0.0.1:8000/api/v1/symbols`
- Запустите live demo для создания данных

**Chart не отображается:**
- Откройте DevTools (F12) → Console для ошибок
- Проверьте, что TradingView CDN загружен (Network tab)
