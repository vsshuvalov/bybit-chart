# NEXT: Текущий статус проекта

**Обновлено:** 2026-08-11 20:30 UTC  
**Статус:** Stage 1 COMPLETE, Этап 5-6 COMPLETE, Production Collector Running

---

## 🎯 Текущее состояние

✅ **Stage 1: 100% COMPLETE (9/9 задач)**  
✅ **Этап 5: 100% COMPLETE (Trade-derived analytics, 7/7 модулей)**  
✅ **Этап 6: 100% COMPLETE (Book-derived analytics, 8/8 модулей)**  
✅ **Collector работает на production-сервере** — круглосуточный сбор невосполнимых данных  
✅ **GitHub CI operational** — automated testing на ubuntu-24.04  
✅ **PostgreSQL schema deployed** — workspace/audit/orders tables  
✅ **Documentation complete** — Analytics README + ADR-014/015/016

**Сервер:** firstbyte.ru, 8 vCPU, 8 GB RAM, Ubuntu 24.04 LTS, Python 3.12.3  
**Символы:** BTCUSDT, ETHUSDT, XRPUSDT (3 отдельных systemd units)  
**Данные:** `/opt/bybit-chart/data/{SYMBOL}/` — WAL + Parquet  
**Throughput:** ~13 MB/час → ~9.3 GB/30 дней (trades only, без orderbook)  
**GitHub:** https://github.com/vsshuvalov/bybit-chart (75+ commits, CI green)

---

## 📊 Roadmap Progress

**Stage 1:** 9/9 COMPLETE (100%)  
**Этап 5:** 7/7 COMPLETE (100%) — Trade-derived analytics  
**Этап 6:** 8/8 COMPLETE (100%) — Book-derived analytics  
**15 практических задач:** 9/15 DONE (60%)  
**Overall Roadmap:** ~52-55% готовности (Этапы 0-6)

---

## ⏰ Critical Timeline

**2026-08-14 00:55 UTC (через ~35 часов):**
```bash
# Capacity measurement baseline
sudo -u bybit /opt/bybit-chart/deploy/measure_capacity.sh > /tmp/capacity_report.txt
```

⚠️ **НЕ ТРОГАТЬ production collector до capacity measurement!**

---

## 🎯 Следующие приоритеты

### ✅ DONE (последние 2 дня):

**Этап 5 (Trade-derived):**
- ✅ Footprint + Imbalance (81b3578)
- ✅ Tape/Bubbles (18964be)
- ✅ Sweep detector (13baa01)

**Этап 6 (Book-derived):**
- ✅ OFI + Microprice (92660a4)
- ✅ Absorption (0e4e6ac)
- ✅ Walls (29d4cc3)
- ✅ Pulling/Stacking (4fff6e9)
- ✅ Liquidation cascades (bc295a2)
- ✅ Heatmap tiles (3fe58a0)
- ✅ Regime/Feature API (197dff3)

**Documentation:**
- ✅ Analytics README (c299df3)
- ✅ ADR-014: Heatmap tile design (c299df3)
- ✅ ADR-015: Regime classification (c299df3)
- ✅ ADR-016: IPC protocol (e781182)

**Quality:**
- ✅ Integration tests (afff846) — 19 tests
- ✅ Property tests (5262c42) — 17 tests

---

### 🔜 Immediate Next (после capacity measurement):

**1. Этап 2 — Multi-Process Safety (P0, блокирует production trading)**

Задачи:
- P1-S2-003: Fencing token implementation
  - Design готов: ADR-013 (Writer Lease + Fencing Token)
  - Реализация: `packages/storage/fencing.py`
  - Tests: cutover/rollback scenarios
  
- P1-S2-004: IPC publisher implementation
  - Design готов: ADR-016 (Unix Domain Sockets)
  - Реализация: `packages/ipc/publisher.py`, `packages/ipc/subscriber.py`
  - Tests: backpressure, disconnect/reconnect

**2. Этап 3 — Orderbook Delta Reconstruction (P1-S3-002)**

Roadmap §8.2 требования:
- BookState machine для reconstruction
- Delta apply logic (add/update/delete levels)
- Sequence validation (u/seq tracking)
- Gap detection и resnapshot trigger

Блокирует: полная работа book-derived analytics (сейчас только snapshots)

**3. Capacity ADR (после measurement)**

На основе `capacity_report.txt` создать:
- ADR-017: Disk capacity planning
- 30-day retention requirements
- RPI feed impact estimate (+2-3x)
- Scaling projections

---

## 📈 Tests Status

**Total:** 780 passed, 8 skipped  
**Breakdown:**
- Contract tests: 249
- Fault injection: 45
- Property tests: 46 (29 storage + 17 analytics)
- Analytics tests: 78 (unit + property)
- Integration tests: 19

**Coverage highlights:**
- ✅ WAL crash recovery
- ✅ Manifest state machine
- ✅ Deterministic aggregation (Hypothesis)
- ✅ API endpoint validation
- ✅ Multi-symbol integration

---

## 🚀 Deployment Status

**Production (firstbyte.ru):**
- ✅ 3 symbols collecting 24/7
- ✅ PostgreSQL 16.14 operational
- ✅ GitHub CI green
- ⏳ 72h soak in progress (через ~35h)

**Pending:**
- ❌ RPI feed activation (за feature flag)
- ❌ Orderbook delta feeds
- ❌ Maintenance worker (отдельный процесс)
- ❌ IPC между processes

---

## 📝 Documentation Artifacts

**ADR (Architecture Decision Records):**
1. ADR-001 до ADR-012 — Stage 0-1 decisions
2. ADR-013 — Writer Lease + Fencing Token ✅
3. ADR-014 — Heatmap Tile Design ✅
4. ADR-015 — Regime Classification ✅
5. ADR-016 — IPC Protocol (UDS) ✅

**README files:**
- ✅ `packages/analytics/README.md` — 18 модулей с examples
- ✅ `ROADMAP_STATUS.md` — актуальный прогресс
- ✅ `TODO.md` — task backlog

**Missing (TODO):**
- ❌ CHANGELOG.md — история изменений
- ❌ CONTRIBUTING.md — guide для contributors
- ❌ Performance benchmarks (analytics throughput)

---

## ⚠️ Known Issues & Technical Debt

**High Priority:**
1. Orderbook feeds не подключены (только publicTrade)
   - Блокирует: полная работа OBI/OFI/Walls/Absorption
   - Требует: P1-S3-002 (delta reconstruction)

2. No IPC между processes
   - Блокирует: Этап 2-4
   - Требует: P1-S2-003, P1-S2-004

3. Capacity measurement pending
   - Блокирует: Capacity ADR, disk size decision
   - Deadline: 2026-08-14 00:55 UTC

**Medium Priority:**
4. Deterministic cache/revision не реализован (§9.6)
5. Crash/restart checkpoint tests не полные (§6.9)
6. Live integration для Regime API (сейчас mock data)

**Low Priority:**
7. 293 deprecation warnings (FastAPI on_event → lifespan, Pydantic Config)
8. Historical regime tracking не реализован
9. Property tests для остальных analytics модулей

---

## 🎯 Success Metrics (Stage 1-6)

**Functionality:**
- ✅ 18 analytics modules реализованы
- ✅ 17 API endpoints работают
- ✅ 780 tests passed
- ✅ Multi-symbol support (3 symbols)
- ✅ Property tests для determinism

**Performance:**
- ✅ Throughput: ~13 MB/час (trades only)
- ✅ Latency: <1s для API queries
- ⏳ Capacity baseline pending (через 35h)

**Quality:**
- ✅ CI/CD pipeline operational
- ✅ Fault injection tests
- ✅ Property-based tests (Hypothesis)
- ✅ ADR documentation complete

---

## 🔒 Production Safety

**До capacity measurement НЕ МЕНЯТЬ:**
- ❌ Collector configuration
- ❌ Feed scope (orderbook delta)
- ❌ Storage layer (WAL/Parquet)
- ❌ Production deployment
- ❌ RPI feed activation

**Безопасно:**
- ✅ Analytics module changes
- ✅ API endpoint changes
- ✅ Documentation updates
- ✅ Test additions
- ✅ ADR creation

---

## 📞 Handoff Notes

**Для тимлида:**

1. **Этапы 5-6 завершены полностью (100%)**
   - Trade-derived: Delta, CVD, VWAP, Volume Profile, Footprint, Sweep, Tape
   - Book-derived: OBI, OFI, Absorption, Walls, Pulling/Stacking, Liquidation, Heatmap, Regime

2. **Этап 2 готов к реализации**
   - Design complete: ADR-013 (Fencing), ADR-016 (IPC)
   - Остаётся: implementation + tests

3. **Capacity measurement через 35 часов**
   - Collector не трогали
   - Данные чистые для baseline

4. **780 tests passed, quality высокая**
   - Property tests добавлены
   - Integration tests покрывают API

5. **Documentation актуальна**
   - Analytics README complete
   - ADR для всех major decisions
   - ROADMAP_STATUS синхронизирован

**Вопросы для обсуждения:**
- Приоритет Этапа 2 vs Этап 3 (IPC vs Orderbook delta)?
- Deployment strategy для multi-process architecture?
- Capacity threshold для production trading?

---

**Last updated:** 2026-08-11 20:30 UTC  
**Next review:** После capacity measurement (2026-08-14)
   - Roadmap §6.5, §18.1 требования
   - Варианты: file lock, Redis lease, PostgreSQL advisory lock
   - Критично для Этапа 2 (IPC isolation)

2. **Capacity Measurement** (2026-08-14)
   - Baseline: 3 symbols, trades-only
   - Затем: A/B test с RPI feed on/off
   - Output: disk requirements, load impact

3. **ADR-013: IPC Protocol Design** (P1-S2-002)
   - Roadmap §5.1, §5.2 требования
   - Варианты: UDS, gRPC, shared memory
   - Зависимость: ADR-012 accepted

### Medium Priority (1-2 недели):

4. **Orderbook Delta Reconstruction** (P1-S3-002)
   - Roadmap §8.2
   - Сейчас: только snapshot, delta пропускаются
   - Требует: BookState machine, sequence validation

5. **Footprint Chart** (P1-S5-001)
   - Roadmap §9.1 Этап 5
   - Bid/ask volume per price level
   - Imbalance detection

6. **Deploy RPI Collector** (P1-S3-004)
   - После capacity measurement baseline
   - 24-72h A/B soak (RPI on/off)
   - Disk usage comparison

---

## 📋 Сегодняшние достижения (2026-08-11)

### ✅ Закрыто:
1. P1-S1-006 — Linux dependency lock (137 строк, Python 3.12.3)
2. P1-S1-009 — PostgreSQL setup (16.14, 3 таблицы, 9 индексов)
3. P1-S1-007 — GitHub Actions CI workflow
4. P1-S3-001 — RPI feed collector (kline.1.{SYMBOL})
5. Stage 1 → 100% COMPLETE
6. Orderbook snapshot collector (`collector_with_book.py`)
7. Roadmap audit → 45% готовности
8. TODO.md update → Stage 2-3 tasks added

### 📈 Метрики:
- **Commits:** 34 → 42 (+8 today)
- **Tests:** 666+ passed
- **CI:** Green (ubuntu-24.04)
- **Production:** 3 symbols running
- **PostgreSQL:** 3 tables operational

---

## 🚧 Текущие блокеры

### Stage 2 (IPC, Fencing):
- ❌ ADR-012 не написан (fencing token design)
- ❌ ADR-013 не написан (IPC protocol)
- ❌ Fencing token implementation
- ❌ Maintenance worker не изолирован

### Этап 3 (Scope):
- ⏳ Capacity measurement pending (через 72h)
- ⏳ A/B soak (RPI on/off) не выполнен
- ❌ Orderbook delta reconstruction
- ❌ Scheduled OI, funding feeds

### Production Trading:
- ❌ Market simulator (Этап 8)
- ❌ Execution contract (Этап 9)
- ❌ Strategies with TP/SL (Этап 10)
- ❌ Risk policy + promotion gates

---

## 💡 Recommendations for Next Session

### Option A: Design Work (2-3 hours)
1. Write ADR-012: Fencing Token Design
2. Write ADR-013: IPC Protocol Design
3. Review Roadmap §6.5, §18.1 requirements

### Option B: Implementation (2-3 hours)
1. Footprint Chart implementation
2. Contract tests для RPI feed
3. Integration test для multi-symbol

### Option C: Documentation (1-2 hours)
1. README.md improvement (badges, quick start)
2. CONTRIBUTING.md
3. Architecture diagrams

**Recommended:** Option A (Design Work) — unblocks Stage 2 critical path.

---

## 📁 Key Files

**Production:**
- Collector: `/opt/bybit-chart/packages/bybit/`
- Data: `/opt/bybit-chart/data/{SYMBOL}/`
- Systemd: `/etc/systemd/system/bybit-collector-*.service`

**Development:**
- Roadmap: `BYBIT_MULTIPROCESS_PLATFORM_ROADMAP.md`
- Status: `ROADMAP_STATUS.md`
- Tasks: `TODO.md`
- Next: `NEXT.md` (this file)

**Contracts:**
- `contracts/schemas.py` — RawTrade, BookCheckpoint
- `contracts/raw_kline.py` — RPI kline feed

**Examples:**
- `examples/collector_with_book.py` — orderbook snapshot
- `examples/rpi_collector.py` — RPI feed с feature flag

---

## 🔍 Health Checks

**Production Collector:**
```bash
# Status
sudo systemctl status bybit-collector-BTCUSDT
sudo systemctl status bybit-collector-ETHUSDT
sudo systemctl status bybit-collector-XRPUSDT

# Logs
sudo journalctl -u bybit-collector-BTCUSDT -n 50 --no-pager

# Data size
du -sh /opt/bybit-chart/data/*/
```

**PostgreSQL:**
```bash
psql -h 148.113.178.18 -U bybit_user -d bybit_chart -c '\dt'
psql -h 148.113.178.18 -U bybit_user -d bybit_chart -c 'SELECT COUNT(*) FROM workspace;'
```

**GitHub CI:**
```bash
gh run list --repo vsshuvalov/bybit-chart --limit 5
```

---

## ⚠️ Important Notes

1. **Capacity measurement через 72h** — НЕ менять collector конфигурацию до этого
2. **Production collector стабилен** — 3 символа работают непрерывно
3. **RPI feed готов** — но deployment после capacity baseline
4. **Stage 2 design required** — fencing token + IPC protocol ADRs
5. **Orderbook delta** — требует отдельную реализацию (§8.2)

---

**Last update by:** Claude Opus 5  
**Session ID:** ec06c0f4-07f6-46f9-9b1a-fb74d19a4bb8  
**Repository:** https://github.com/vsshuvalov/bybit-chart

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
