# NEXT: Текущий статус проекта

**Обновлено:** 2026-08-11 01:21 UTC  
**Статус:** Production Collector Running (3 symbols)

---

## 🎯 Текущее состояние

✅ **Collector работает на production-сервере** — круглосуточный сбор невосполнимых данных.

**Сервер:** firstbyte.ru, 8 vCPU, 8 GB RAM, Ubuntu 24.04 LTS, Python 3.12.3  
**Символы:** BTCUSDT, ETHUSDT, XRPUSDT (3 отдельных systemd units)  
**Данные:** `/opt/bybit-chart/data/{SYMBOL}/` — WAL + Parquet  
**Throughput:** ~13 MB/час → ~9.3 GB/30 дней (trades only, без orderbook)

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

- **34 коммита** (Stage 0-4 + Этап 1-3 + Analytics + OBI + Deployment + Linux lock)
- **658 passed, 8 skipped** — все тесты проходят (macOS + Linux)
- **Production collector running** — 3 символа, 5.6 MB за 25 минут (~4.9M trades)

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

### Immediate (через 72 часа — 2026-08-14 00:55 UTC)

**Capacity measurement** (Roadmap §6.8):
```bash
# На сервере
sudo -u bybit /opt/bybit-chart/deploy/measure_capacity.sh > /tmp/capacity_report.txt
```
Результат → Capacity ADR → решение про disk size и retention policy.

### Short-term (1-2 недели)

1. **PostgreSQL migrations** (P1-S1-009)
   - Установить PostgreSQL 16 на сервере
   - Реализовать initial schema (workspace/audit/orders)
   - Интегрировать в application startup

2. **Расширить feed scope**
   - Добавить orderbook.200 (сейчас только publicTrade)
   - L50/L1000 feeds (capacity test перед включением)
   - ticker, allLiquidation

3. **GitHub remote + CI** (P1-S1-007)
   - Создать GitHub repository
   - Push main branch
   - GitHub Actions workflow для pytest на Linux

### Medium-term (1-2 месяца)

4. **Roadmap Этап 2** — изолированный collector
   - Writer lease / fencing token
   - UDS/gRPC publish к analytics
   - Cutover/rollback protocol

5. **Roadmap Этап 4** — multi-process architecture
   - orderflow-worker как отдельный процесс
   - api-gateway без analytics logic
   - maintenance-worker для compaction

6. **Roadmap Этап 5-6** — Analytics modules
   - Footprint chart, Sweep detector
   - Heatmap tiles, Attribution snapshot
   - Walls, Absorption, Liquidation cascades

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
