# Сводка текущего состояния — Bybit Chart Platform

**Дата:** 2026-08-13  
**Сервер:** 83.147.234.167 (firstbyte.ru)  
**Локальная база:** `/Users/vs/Desktop/bybit-chart`

---

## Executive Summary

**Общий прогресс:** 52-55% дорожной карты выполнено (Этапы 0-6 из 15)

**Production статус:**
- ✅ 4 сервиса работают корректно
- ❌ 1 сервис (bybit-api) в crash loop — **ТРЕБУЕТ ИСПРАВЛЕНИЯ**
- ✅ Collector собирает данные 24/7 (BTCUSDT, ETHUSDT, XRPUSDT)
- ⏳ RPI A/B soak завершается через ~18 часов (2026-08-13 00:37 UTC)

---

## Критическая проблема: API Service

**Симптом:**
```
ERROR: [Errno 98] error while attempting to bind on address ('127.0.0.1', 8000): address already in use
bybit-api.service: Main process exited, code=exited, status=1/FAILURE
Restart counter is at 138
```

**Причина:** Порт 8000 уже занят другим процессом

**Решение:**
1. Найти процесс: `lsof -i :8000`
2. Проверить конфликт с другими workers
3. Либо изменить порт в systemd unit, либо остановить конфликтующий процесс

**Приоритет:** P0 — блокирует все API endpoints

---

## Что работает (Production)

### ✅ Сервисы (5/6 active):

1. **bybit-collector.service** — active (running)
   - Main PID: 105015
   - Uptime: 3h 46min
   - Функция: Сбор trades (BTCUSDT, ETHUSDT, XRPUSDT)

2. **bybit-orderflow.service** — active (running)
   - Main PID: 57436
   - Uptime: 17h
   - Функция: Book/trade analytics pipeline

3. **bybit-analytics.service** — active (running)
   - Main PID: 99669
   - Uptime: 6h
   - Функция: Analytics computation (Delta, CVD, VWAP, etc.)

4. **bybit-maintenance.service** — active (running)
   - Main PID: 99612
   - Uptime: 6h
   - Функция: Parquet compaction, cleanup

5. **bybit-api.service** — ❌ activating (auto-restart)
   - Status: FAILED (exit-code 1)
   - Issue: Port 8000 already in use
   - Restart count: 138+

### ✅ Данные:

- **Путь:** `/opt/bybit-chart/data/{SYMBOL}/`
- **Формат:** WAL + Parquet
- **Throughput:** ~13 MB/час (trades only)
- **Projected 30-day:** ~9.3 GB
- **Символы:** BTCUSDT, ETHUSDT, XRPUSDT

### ✅ Тесты:

- **Total:** 875 passed, 8 skipped
- **Coverage:** Fault injection, crash recovery, property tests
- **CI:** GitHub Actions green (ubuntu-24.04)

---

## Выполненные этапы дорожной карты

### ✅ Этап 0: Design Freeze (100%)
- 75+ commits в GitHub
- ADR-001 до ADR-017 созданы
- SBOM для darwin-arm64, linux-x86_64
- Baseline capacity: 92 MB/24h (ADR-017)

### ✅ Этап 1: Изолированный Recorder (100%)
- market-collector без analytics
- WAL + Parquet + Manifest
- Gap detection (RawTrade.sequence, BookCheckpoint.updateId)
- Multi-symbol: BTC, ETH, XRP
- Production: 3 systemd units

### ✅ Этап 2: IPC (100%)
- WriterLease / fencing token (ADR-013)
- IPC Publisher/Subscriber (UDS, ADR-016)
- Maintenance worker (отдельный процесс)
- 21 fault tests, 17 integration tests

### ⏳ Этап 3: Расширение Scope (95%)
- ✅ Orderbook delta reconstruction
- ✅ RPI feed deployed (3 RPI units)
- ⏳ RPI A/B soak до 2026-08-13 00:37 UTC
- ❌ Scheduled OI/funding feeds — NOT IMPLEMENTED

### ✅ Этап 4: Четыре Процесса (100%)
- orderflow-worker, analytics-worker, api-server, collector-worker
- IPC 4-process pipeline
- Process supervisor
- Prometheus + Grafana
- ❌ API service crashed — requires fix

### ✅ Этап 5: Trade-Derived Analytics (100%)
- 7/7 модулей: OHLCV, Tape, Footprint, Delta, CVD, VWAP, Volume Profile, Sweep
- 26 tests passed
- Property tests для determinism

### ✅ Этап 6: Book-Derived Analytics (100%)
- 8/8 модулей: Heatmap, OBI, OFI, Absorption, Walls, Pulling/Stacking, Liquidations, Regime
- 41 tests passed
- API endpoints: `/api/v1/analytics/heatmap`, `/orderflow/regime`, `/orderflow/features`

### ⏳ Этап 8: Simulator (20%)
- ✅ Этап 8.1: State machine + adapter (100%)
- ❌ Этапы 8.2-8.n: MarketReplay, reports (0%)

---

## НЕ выполненные этапы (блокеры)

### ❌ Этап 7: Frontend React (0%) — HIGH PRIORITY

**Проблема:** Существующие 6 HTML-страниц НЕ соответствуют требованиям §11

**Требуется:**
- React + TypeScript + Vite с нуля
- Shell: TopBar / LeftToolbar / ChartPanel / Sidebar / BottomDock / StatusBar
- TradingView Lightweight Charts + custom layers
- Schema-driven settings
- 14 drawing tools
- Server persistence (workspaces/drawings/scripts)
- E2E + visual tests (Vitest + Playwright)

**Блокеров нет:** API contracts готовы (Этапы 4-6 complete)

**Roadmap:** §11, §19

---

### ❌ Этап 9: Manual Execution (0%)

**Требуется:**
- Private WebSocket (order/execution/position)
- Bybit REST adapter
- OrderIntent ledger
- Risk Engine
- Reconciliation logic
- Server-side SL/TP

**Блокеры:** Требует Этап 7 (frontend для Order Ticket UI)

**Roadmap:** §15

---

### ❌ Этап 10: Strategies (0%)

**Требуется:**
- 6 канонических стратегий
- Level Interaction Classifier
- StrategySignal schema
- Per-symbol calibration
- Promotion gate (replay → backtest → OOS → paper → live)

**Блокеры:** Требует Этап 9 (execution-risk), Этап 8 (simulator complete)

**Roadmap:** §14

---

### ❌ Этап 11: AI Assistant (0%)

**Требуется:**
- Provider-neutral LLM layer
- Strategy Research Sandbox
- Model registry
- Governance (no direct trading keys)

**Блокеры:** Требует Этапы 9-10

**Roadmap:** §16

---

### ❌ Этапы 12-15: Production 24/7 (0%)

**Требуется:**
- Health checks / monitoring
- Alerting rules
- Backup / restore
- Rollback procedures
- Secrets management
- Emergency runbooks

**Roadmap:** §18, §25

---

## Пропущенные требования

### 1. Scheduled Feeds (Этап 3)

**Roadmap §8.2, §22:**
- ❌ Scheduled REST ingestion для OI
- ❌ Scheduled REST ingestion для funding
- ❌ Market history kline validation
- ❌ Separate checkpoints для scheduled data

**Приоритет:** P2 — не блокирует core, но требуется по roadmap

---

### 2. ADR-010/011 Not Approved (Этап 0)

**Roadmap §1.2:**
- ❌ ADR-010: ML-модель lifecycle, запрет прямого доступа ИИ к бирже
- ❌ ADR-011: Release, rollback, backup, RPO/RTO, secrets

**Приоритет:** P2 — блокирует Этапы 11-15

---

### 3. Shadow/Cutover/Rollback Test (Этап 2)

**Roadmap §21:**
- ⏳ Production cutover test не выполнен
- ⏳ Rollback procedure не проверен

**Приоритет:** P2 — требуется для production confidence

---

### 4. MarketReplay Complete (Этап 8)

**Roadmap §13:**
- ❌ MarketReplay (clocks, book/trade replay)
- ❌ Partial fill / IOC / SL / TP / funding
- ❌ Reports UI
- ❌ Independent simulation worker
- ❌ Same-run checksum acceptance test

**Приоритет:** P1 — блокирует Этап 10 (strategies)

---

## Immediate Actions (Priority Order)

### 🚨 P0: Fix API Service (0-1 hour)

**Проблема:** Port 8000 already in use

**Действия:**
1. `ssh root@83.147.234.167`
2. `lsof -i :8000` — найти конфликтующий процесс
3. Проверить, не запущен ли другой worker на :8000
4. **Опции:**
   - Остановить конфликтующий процесс
   - Изменить порт в `/etc/systemd/system/bybit-api.service`
5. `systemctl restart bybit-api`
6. `systemctl status bybit-api` — проверить active
7. `curl http://127.0.0.1:8000/health` — проверить endpoint

**Evidence:** journalctl logs показывают Errno 98

---

### ⏰ P0: RPI A/B Soak Completion (18 hours)

**Deadline:** 2026-08-13 00:37 UTC

**Действия:**
1. Дождаться завершения soak
2. Выполнить: `sudo -u bybit /opt/bybit-chart/deploy/measure_capacity.sh > /tmp/capacity_report.txt`
3. Проанализировать disk usage (RPI on vs off)
4. Финализировать ADR-017 (Disk capacity planning)
5. Принять решение о permanent RPI deployment

**Evidence:** RPI units active с 2026-08-12 00:33 UTC

---

### 📋 P1: Начать Этап 7 — Frontend (1-2 weeks)

**План:**

**Week 1: Shell + Basic Chart (30%)**
1. Создать React + TypeScript + Vite проект
2. Setup структура: `web/src/{components,hooks,stores,api,types}`
3. Реализовать shell layout (§11.1):
   - TopBar (workspace, symbol, timeframe, quality badge)
   - LeftToolbar (drawing tools)
   - ChartPanel (TradingView Lightweight Charts)
   - RightSidebar (Watchlist, DOM, Orders)
   - BottomDock (Delta/CVD, logs)
   - StatusBar (feed ages, gaps)
4. Интегрировать Lightweight Charts
5. Basic API client (`/api/v1/trades`, `/ohlc`)
6. Symbol switch (BTCUSDT/ETHUSDT/XRPUSDT)

**Week 2: Analytics + Persistence (60%)**
7. Analytics overlay layers (Delta, CVD, VWAP)
8. Schema-driven settings panel
9. Workspaces persistence API (`GET/POST /api/v1/workspaces`)
10. Drawings persistence API (`GET/POST /api/v1/drawings`)
11. Data Quality badge integration
12. Heatmap integration

**Week 3-4: Drawing Tools + Tests (100%)**
13. 14 drawing tools (trend line, horizontal, rectangle, etc.)
14. Risk-reward tool (Entry/SL/TP)
15. E2E tests (Playwright)
16. Visual regression tests
17. Performance optimization

**Roadmap compliance:** §11, §19

---

### 📋 P2: Завершить Этап 3 (1 week)

**После RPI soak:**

1. **Scheduled OI feed** (§8.2)
   - `GET /v5/market/open-interest` с интервалом 5m
   - Separate checkpoint для scheduled data
   - Schema: `ScheduledOI(symbol, timestamp, openInterest, openInterestValue)`

2. **Scheduled Funding feed** (§8.2)
   - `GET /v5/market/funding/history` с интервалом 8h
   - Schema: `ScheduledFunding(symbol, timestamp, fundingRate, fundingRateTimestamp)`

3. **Kline validation** (§8.2)
   - `GET /v5/market/kline` для cross-check
   - Validation против собственных OHLCV aggregates

**Evidence:** REST scheduler + tests

---

### 📋 P2: Утвердить ADR-010/011 (2-3 days)

**ADR-010: ML Model Lifecycle**
- Training data isolation
- Model registry (versioning, approval)
- Запрет прямого доступа ИИ к биржевым API
- Research Sandbox boundaries
- Dataset/feature leakage prevention
- Drift detection

**ADR-011: Release & Operations**
- Immutable artifact (git SHA, docker image)
- Canary deployment
- Rollback procedure
- Backup strategy (WAL, Parquet, PostgreSQL)
- RPO/RTO targets
- Secrets management (not in git)
- Emergency runbooks

**Roadmap compliance:** §1.2

---

## Roadmap Compliance Summary

### Обязательные свойства (§2.2):

| Свойство | Статус | Evidence |
|----------|--------|----------|
| Событие записывается, потом вычисляется | ✅ COMPLIANT | WAL append-only |
| Downstream не останавливает collector | ✅ COMPLIANT | IPC non-blocking |
| Gap маркируется, не интерполируется | ✅ COMPLIANT | GapDetector |
| Deterministic replay | ✅ COMPLIANT | Property tests |
| UI не владеет историей | ⏳ PARTIAL | API готов, frontend pending |
| Один Risk Engine | ❌ NOT COMPLIANT | Этап 9 не реализован |
| ACK не считается fill | ❌ NOT COMPLIANT | Этап 9 не реализован |
| Numeric features (no colors) | ❌ NOT COMPLIANT | Этап 10 не реализован |

### Процессы (§3.3):

| Процесс | Статус | Evidence |
|---------|--------|----------|
| market-collector | ✅ RUNNING | PID 105015 |
| orderflow-worker | ✅ RUNNING | PID 57436 |
| api-gateway | ❌ CRASHED | Port conflict |
| maintenance-worker | ✅ RUNNING | PID 99612 |
| execution-risk | ❌ NOT IMPLEMENTED | Этап 9 |
| strategy-worker | ❌ NOT IMPLEMENTED | Этап 10 |

---

## Заключение

**Достижения:**
- ✅ Solid foundation (Этапы 0-6): WAL, IPC, Analytics
- ✅ 875 tests passed
- ✅ Production collector стабилен 24/7
- ✅ Multi-process architecture работает

**Критические блокеры:**
1. ❌ API service crashed (port conflict) — **FIX IMMEDIATELY**
2. ⏳ RPI A/B soak (18h remaining) — **WAIT & ANALYZE**
3. ❌ Frontend не начат — **START AFTER SOAK**

**Пропущенные этапы:**
- Этап 7: Frontend (0%) — блокирует UI
- Этап 9: Execution (0%) — блокирует trading
- Этап 10: Strategies (0%) — блокирует automation
- Этап 11: AI (0%) — блокирует assistant

**Next steps:**
1. Исправить API service (P0, 1h)
2. Дождаться RPI soak (P0, 18h)
3. Начать Frontend React (P1, 2-4 weeks)
4. Завершить Этап 3: scheduled feeds (P2, 1 week)
5. Утвердить ADR-010/011 (P2, 2-3 days)

**Overall assessment:** Хороший прогресс по backend infrastructure (52-55%), но frontend и trading functionality полностью отсутствуют. Требуется фокус на Этап 7 (Frontend) для разблокировки user-facing features.

---

**Prepared by:** Claude Opus 5  
**Date:** 2026-08-13  
**Working directory:** `/Users/vs/Desktop/bybit-chart`  
**Production server:** `83.147.234.167` (firstbyte.ru)
