# NEXT: Текущий статус проекта

**Обновлено:** 2026-08-11  
**Статус:** Development + Server Deployment Ready

---

## 🎯 Текущая цель

**Развернуть collector на production-сервере** для начала круглосуточного сбора невосполнимых рыночных данных.

**Сервер:** firstbyte.ru, 8 vCPU, 8 GB RAM, Ubuntu 24.04 LTS  
**Руководство:** `deploy/QUICKSTART.md` (30 минут)

---

### Stage 1: Storage Core (4 коммита)
- WAL (Write-Ahead Log) с atomic commit
- Parquet writer с Arrow schema
- Manifest.json для метаданных
- Offsets tracking (closed, durable)

### Stage 2: Bybit Integration (5 коммитов)
- WebSocket Client (Bybit V5 API)
- RawTrade deserializer
- BookCheckpoint deserializer
- EventCollector (WAL append)
- Live demo работает

### Stage 3: Query API (4 коммита)
- ParquetReader
- FastAPI REST API (/trades, /ohlc, /symbols)
- OHLC server-side aggregation
- CORS middleware для frontend

### Stage 4: Frontend (2 коммита)
- TradingView Lightweight Charts
- Interactive candlestick chart
- Symbol selector (BTCUSDT/ETHUSDT/XRPUSDT)
- Adaptive price precision

### Этап 1: BookCheckpoint, Gap Detection, Multi-symbol (3 коммита)
- **P1-B1:** BookCheckpoint Integration
  - append_book_checkpoint() в EventCollector
  - Parquet schema с bids/asks (JSON strings)
  - Mixed events (RawTrade + BookCheckpoint)
- **P1-B2:** Gap Detection
  - GapDetector для RawTrade.sequence и BookCheckpoint.updateId
  - SourceQuality states (BOOTSTRAP → LIVE_READY → GAP)
  - Автоматическое восстановление после 100 событий
- **P1-B3:** Multi-symbol Support
  - Numeric constants (PRICE_TICK, QTY_STEP) для всех symbols
  - Multi-symbol demo (examples/multi_symbol_demo.py)
  - Frontend selector для BTCUSDT/ETHUSDT/XRPUSDT

### Этап 3: Analytics Modules (6 коммитов)
- **P3-A1:** Delta Calculation
  - Buy/sell pressure: Delta = buy_volume - sell_volume
  - Aggregation by interval (1m, 5m, 15m, ...)
- **P3-A2:** CVD (Cumulative Volume Delta)
  - CVD = cumsum(Delta)
  - Divergence detection (price vs CVD)
  - Reset функция для новых сессий
- **P3-A3:** VWAP (Volume Weighted Average Price)
  - VWAP = Σ(price × volume) / Σ(volume)
  - Aggregation by interval
  - Cumulative VWAP (running from session start)
- **P3-A4:** Volume Profile
  - POC (Point of Control) — max volume level
  - Value Area (70% volume range)
  - HVN/LVN (High/Low Volume Nodes)
- **P3-A5:** OBI (Order Book Imbalance)
  - OBI = (Bid Volume - Ask Volume) / Total Volume
  - Level aggregation: near (top 5), mid (6-20), far (21-50)
  - Extreme imbalance detection (threshold alerts)
- **Analytics API:** REST endpoints
  - GET /api/v1/analytics/delta
  - GET /api/v1/analytics/cvd
  - GET /api/v1/analytics/vwap
  - GET /api/v1/analytics/volume-profile
- **Analytics Frontend:** Interactive visualization
  - Tabs: Price Only / + Delta / + CVD / + VWAP
  - Delta: histogram (green/red bars)
  - CVD: line chart
  - VWAP: overlay line on main chart

---

## 📊 Статистика

- **31 коммитов** (Stage 1-4 + Этап 1 + Этап 3 + Analytics + OBI + Deployment)
- **672 passed, 7 skipped** — все тесты проходят
- **Server deployment ready** — systemd unit + PostgreSQL setup + capacity script

---

## 🚀 Production-Ready Features

✅ **Storage:** WAL → Parquet, Atomic commit, Manifest  
✅ **Data Quality:** GapDetector, SourceQuality tracking  
✅ **Multi-symbol:** BTCUSDT, ETHUSDT, XRPUSDT  
✅ **Events:** RawTrade + BookCheckpoint (mixed segments)  
✅ **Query API:** OHLC aggregation, Trade history  
✅ **Analytics:** Delta, CVD, VWAP, Volume Profile, OBI  
✅ **Frontend:** Interactive charts с analytics visualization  
✅ **Live Demo:** Multi-symbol WebSocket collector  

---

## 🎯 Roadmap Progress

| Этап | Статус | Коммиты |
|---|---|---|
| **Этап 0:** Design freeze | ✅ DONE | 1 |
| **Этап 1:** Collector, Storage, Multi-symbol | ✅ DONE | 3 |
| **Этап 2:** Query API | ✅ DONE | 4 (Stage 3) |
| **Этап 3:** Analytics modules | ✅ DONE | 5 |
| Этап 4+: Production deployment | ⏳ TODO | - |

---

## 📁 Структура проекта

```
bybit-chart/
├── packages/
│   ├── storage/          # WAL, Parquet, GapDetector
│   ├── bybit/            # WebSocket, Deserializers, EventCollector
│   ├── api/              # FastAPI (OHLC, Trades, Analytics)
│   ├── analytics/        # Delta, CVD, VWAP, Volume Profile
│   └── numeric/          # Constants (PRICE_TICK, QTY_STEP)
├── contracts/            # Pydantic schemas (RawTrade, BookCheckpoint)
├── frontend/
│   ├── index.html        # Basic chart
│   └── analytics.html    # Analytics visualization ✨ NEW
├── examples/
│   ├── live_demo.py
│   └── multi_symbol_demo.py
├── tests/                # 518 passed
│   ├── contracts/        # Unit tests
│   └── integration/      # Integration tests
└── docs/                 # Roadmap, ADRs, Architecture
```

---

## 🔥 Next Steps

### Immediate (сейчас)

1. **Развернуть collector на сервере** — следовать `deploy/QUICKSTART.md`
   - Закроет OPEN-005 (архитектура: x86_64, Ubuntu 24.04)
   - Закроет P1-S1-006 (Linux lock после pytest)
   - Начнёт сбор невосполнимых данных

2. **Через 72 часа** — запустить `measure_capacity.sh`
   - Получить bytes/hour baseline (Roadmap §6.8)
   - Принять Capacity ADR
   - Оценить необходимость апгрейда диска

### Short-term (1-2 недели)

3. **PostgreSQL migrations** (P1-S1-009)
   - Реализовать initial schema
   - Закрыть ADR-005

4. **Roadmap Этап 2** — изолированный collector
   - Writer lease / fencing token
   - UDS/gRPC publish к analytics
   - Cutover/rollback protocol

5. **Расширить feed scope**
   - L50/L1000, ticker, allLiquidation
   - RPI on/off capacity test

### Medium-term (1-2 месяца)

6. **Roadmap Этап 4** — изоляция процессов
   - orderflow-worker как отдельный процесс
   - api-gateway без analytics logic

7. **Roadmap Этап 5-6** — Analytics modules
   - Footprint, Sweep detector
   - Heatmap tiles, Attribution, Walls

---

## ⚡ Quick Start

```bash
# Backend
python packages/api/app.py  # FastAPI on http://127.0.0.1:8000

# Frontend
open frontend/analytics.html  # Analytics visualization

# Live data collection
python examples/multi_symbol_demo.py --duration 300
```
