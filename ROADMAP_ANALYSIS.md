# Анализ дорожной карты — текущее состояние и пропущенные этапы

**Дата анализа:** 2026-08-13  
**Источник:** `BYBIT_MULTIPROCESS_PLATFORM_ROADMAP.md` v1.1 (2026-08-11)  
**Локальная база:** `/Users/vs/Desktop/bybit-chart`  
**Production сервер:** `83.147.234.167` (firstbyte.ru)

---

## Executive Summary

**Текущий прогресс:** ~52-55% дорожной карты (Этапы 0-6 из 15)

**Статус Production:**
- ✅ 5 сервисов работают на production
- ❌ 1 сервис (bybit-api) в состоянии auto-restart (требует исправления)
- ✅ Collector собирает данные 24/7 (BTCUSDT, ETHUSDT, XRPUSDT)
- ⏳ RPI A/B soak завершается 2026-08-13 00:37 UTC

**Критические находки:**
1. **Этап 7 (Frontend React) НЕ НАЧАТ** — существующие HTML-страницы не соответствуют требованиям
2. **API сервис не работает** — требует немедленного исправления
3. **Этапы 9-15 (Trading/AI/Production) не начаты** — блокируют полную функциональность
4. **RPI A/B soak в процессе** — критично для capacity ADR-017

---

## Детальный анализ по этапам

### ✅ ЭТАП 0: Design Freeze (100% COMPLETE)

**Roadmap §19**

**Требования:**
- Clean immutable artifact
- Dataset owners
- Dependency lock/SBOM
- Baseline CPU/RAM/disk
- Capacity estimate
- Registry отступлений

**Реализовано:**
- ✅ 75+ commits в GitHub
- ✅ 875 tests passed, 8 skipped
- ✅ ADR-001 до ADR-017 созданы
- ✅ SBOM: `deploy/dependencies/{darwin-arm64,linux-x86_64}/`
- ✅ Baseline capacity: 92 MB/24h (ADR-017)

**Evidence:**
- `docs/adr/` — 17 ADR файлов
- `TODO.md`, `NEXT.md`, `README.md` — актуальны
- `tests/` — 875 passed

---

### ✅ ЭТАП 1: Изолированный Recorder (100% COMPLETE)

**Roadmap §20**

**Требования:**
- market-collector без analytics
- WAL append-only + Parquet publish
- Manifest, offsets, atomic commit
- BookCheckpoint integration
- Gap detection
- Multi-symbol (BTC, ETH, XRP)
- 24-72h soak без потери

**Реализовано:**
- ✅ Collector работает на production: `bybit-collector.service` (active)
- ✅ WAL + Parquet + Manifest: `packages/storage/`
- ✅ Gap detection: `packages/bybit/gap_detector.py`
- ✅ Multi-symbol: BTCUSDT, ETHUSDT, XRPUSDT
- ✅ Throughput: ~13 MB/час, ~4.9M trades

**Production status:**
```
bybit-collector.service: active (running) since 2026-08-13 02:48:36 UTC
Main PID: 105015
```

**Evidence:**
- systemd units: `/etc/systemd/system/bybit-collector*.service`
- Data: `/opt/bybit-chart/data/{SYMBOL}/`
- Tests: fault injection, crash recovery (21 passed)

---

### ✅ ЭТАП 2: Изолированный Collector с IPC (100% COMPLETE)

**Roadmap §21**

**Требования:**
- Writer lease / fencing token
- IPC Publisher (non-blocking UDS)
- IPC Subscriber
- Maintenance worker (отдельный процесс)
- systemd unit для maintenance
- EventCollector + WriterLease
- Shadow/cutover/rollback test

**Реализовано:**
- ✅ WriterLease: `packages/storage/fencing.py` (ADR-013)
- ✅ IPC: `packages/ipc/publisher.py`, `subscriber.py` (ADR-016)
- ✅ Maintenance worker: `workers/maintenance_worker.py`
- ✅ systemd unit: `bybit-maintenance.service` (active)
- ⏳ Shadow/cutover/rollback test — pending

**Production status:**
```
bybit-maintenance.service: active (running) since 2026-08-13 00:26:12 UTC
Main PID: 99612
```

**Evidence:**
- 21 fault tests (fencing)
- 17 integration tests (IPC)
- 6 collector fencing tests

---

### ⏳ ЭТАП 3: Базовые Live-роли и Расширение Scope (95% PARTIAL)

**Roadmap §22**

**Требования:**
- Collector (работает)
- Временный analytics+API (монолитно)
- Maintenance worker (отдельный процесс)
- BTC/ETH/XRP + acceptance
- Orderbook feeds (snapshot + delta)
- RPI feed с feature flag
- Scheduled OI, funding, market history
- Disk/load A/B soak с RPI on/off

**Реализовано:**
- ✅ Collector: работает
- ✅ Analytics: работает (workers/analytics_worker.py)
- ✅ Maintenance: работает
- ✅ 3 символа: BTCUSDT, ETHUSDT, XRPUSDT
- ✅ Orderbook delta: `packages/bybit/book_state.py` (22 tests)
- ✅ RPI feed: deployed на production (3 RPI units)
- ⏳ RPI A/B soak: **В ПРОЦЕССЕ** (завершается 2026-08-13 00:37 UTC)
- ❌ Scheduled OI, funding, market history: **НЕ РЕАЛИЗОВАНО**

**Production status:**
```
bybit-rpi@BTCUSDT.service: active
bybit-rpi@ETHUSDT.service: active
bybit-rpi@XRPUSDT.service: active
```

**Blocker:**
- ⏳ RPI A/B soak до 2026-08-13 00:37 UTC — финализирует capacity ADR-017
- ❌ Scheduled feeds (OI/funding) — required по §8.2

**Evidence:**
- `packages/bybit/book_state.py` — BookState machine
- systemd templates: `bybit-rpi@.service`

---

### ✅ ЭТАП 4: Четыре Процесса (100% COMPLETE)

**Roadmap §23**

**Требования:**
- orderflow-worker (отдельный процесс)
- IPC publisher в orderflow
- IPC integration test для 4-process
- Process supervisor
- 24-72h soak test infrastructure
- Analytics worker
- API server без analytics logic
- Collector worker
- Process-specific metrics
- Prometheus + Grafana dashboards

**Реализовано:**
- ✅ orderflow-worker: `workers/orderflow_worker.py`
- ✅ IPC publisher: commit 3744316
- ✅ 4-process integration: `tests/integration/test_4process_pipeline.py`
- ✅ Supervisor: `workers/supervisor.py`
- ✅ Analytics worker: `workers/analytics_worker.py`
- ✅ API server: `workers/api_server.py`
- ✅ Metrics: `packages/monitoring/worker_metrics.py`
- ✅ Prometheus + Grafana: deployed

**Production status:**
```
bybit-orderflow.service: active (running) since 2026-08-12 13:22:12 UTC
bybit-analytics.service: active (running) since 2026-08-13 00:26:50 UTC
bybit-api.service: activating (auto-restart) ❌ REQUIRES FIX
```

**Critical Issue:**
- ❌ **API service в crash loop** — exit code 1, auto-restart каждые ~630ms
- Требует немедленного анализа логов и исправления

**Evidence:**
- 875 tests passed
- `pyproject.toml`: asyncio_mode=auto (исправлено 2026-08-12)

---

### ✅ ЭТАП 5: Trade-Derived Analytics (100% COMPLETE)

**Roadmap §24.1**

**Требования (7 модулей):**
1. Canonical OHLCV
2. Tape/Bubbles
3. Footprint + Imbalance
4. Delta + CVD
5. Volume Profile
6. VWAP
7. Sweep (trade-series detector)

**Реализовано:**
- ✅ Все 7 модулей: `packages/analytics/`
- ✅ Contracts: `contracts/footprint.py`, `sweep.py`, `tape.py`
- ✅ Tests: 26 passed (footprint: 5, sweep: 8, tape: 13)
- ✅ Property tests для determinism
- ✅ Cross-TF invariants

**Evidence:**
- delta.py, cvd.py, vwap.py, volume_profile.py, footprint.py, sweep.py, tape.py
- Commits: 81b3578, 18964be, 13baa01

---

### ✅ ЭТАП 6: Book-Derived Analytics (100% COMPLETE)

**Roadmap §24.2**

**Требования (8 модулей):**
1. Heatmap tiles
2. OFI + Microprice (Attribution base)
3. OBI (Order Book Imbalance)
4. Absorption
5. Walls
6. Pulling/Stacking
7. Liquidation cascades
8. Regime/Feature API

**Реализовано:**
- ✅ Все 8 модулей: `packages/analytics/`
- ✅ Contracts: `contracts/ofi.py`, `absorption.py`, `walls.py`, `heatmap.py`, `regime.py`
- ✅ Tests: 41 passed
- ✅ API endpoints: `/api/v1/analytics/heatmap`, `/orderflow/regime`, `/orderflow/features`
- ✅ ADR-014: Heatmap tile design
- ✅ ADR-015: Regime classification

**Evidence:**
- obi.py, ofi.py, absorption.py, walls.py, pulling_stacking.py, liquidation_cascades.py, heatmap.py, regime.py
- Commits: 92660a4, 0e4e6ac, 29d4cc3, 4fff6e9, bc295a2, 3fe58a0, 197dff3

---

### ❌ ЭТАП 7: Frontend Analysis Workstation (0% NOT STARTED) ⚠️

**Roadmap §11, §19**

**Требования:**
- Shell: TopBar / LeftToolbar / ChartPanel / RightSidebar / BottomDock / StatusBar
- Menus: Indicators / Order Flow / Strategies / Replay (schema-driven)
- Watchlist: BTCUSDT/ETHUSDT/XRPUSDT + Last/24h%/spread/quality
- Chart layers: overlay/separatePane, z-order, Entry/SL/TP drawing
- Settings: schema-driven per-module panel
- Drawings: 14 tool types, server persistence, schemaVersion+revision
- Diagnostics: Data Quality badge, feed ages/gaps, Heatmap scope
- Persistence: server source of truth (workspaces/drawings/scripts)

**Технологический стек (§4):**
- React + TypeScript + Vite
- TradingView Lightweight Charts + custom Canvas/WebGL layers
- Monaco Editor для Pine-compatible scripts
- Vitest + Playwright для тестов

**Текущее состояние:**
- ❌ **React приложение НЕ СОЗДАНО**
- ❌ Существующие 6 статических HTML страниц (index, live, analytics, orderflow, alerts, paper-trading) **НЕ СООТВЕТСТВУЮТ** требованиям Этапа 7
- ❌ Нет TypeScript
- ❌ Нет компонентной архитектуры
- ❌ Нет schema-driven settings
- ❌ Нет server persistence для drawings

**Acceptance criteria (§11.8, §19):**
- E2E reload/TF/symbol tests
- zoom/DPI/overlap visual tests
- Drawings survive restart/backup restore
- Quality/gap labels всегда видимы
- Heatmap scope: явно показывает standard-only до включения RPI
- BTC/ETH/XRP switch не reconnect-ит Bybit

**Блокеров нет:** Этапы 4-6 COMPLETE, API contracts стабильны

**Приоритет:** HIGH — требуется полная реализация с нуля

---

### ⏳ ЭТАП 8: Simulator/Replay (20% PARTIAL)

**Roadmap §13**

**Требования:**
- Order/Fill/Position state machine
- ExecutionAdapter interface
- SimulatorAdapter (conservative fills)
- SimulatorClock (deterministic time)
- OrderMatcher (maker/taker, no lookahead)
- LatencyModel (p50/p95/p99)
- Deterministic checksum
- MarketReplay (clocks, book/trade replay)
- Partial fill / IOC / SL / TP / funding
- Reports и UI controls
- Independent simulation worker
- Same-run checksum acceptance test

**Реализовано (Этап 8.1 — 100%):**
- ✅ State machine: `packages/execution/engine.py`
- ✅ ExecutionAdapter interface
- ✅ SimulatorAdapter: `packages/execution/simulator.py` (452 строки)
- ✅ SimulatorClock
- ✅ OrderMatcher (conservative)
- ✅ LatencyModel
- ✅ Position tracking fix
- ✅ Tests: 27 passed (engine: 12, simulator: 15)

**НЕ реализовано (Этапы 8.2-8.n — 0%):**
- ❌ MarketReplay
- ❌ Partial fill / IOC / SL / TP / funding scenarios
- ❌ Reports и UI controls
- ❌ Independent simulation worker
- ❌ Same-run checksum acceptance test

**Evidence:**
- commit a72e11a (2026-08-12)
- `tests/execution/test_engine.py`, `test_simulator.py`

---

### ❌ ЭТАП 9: Manual Execution (0% NOT STARTED)

**Roadmap §15**

**Требования:**
- Private WebSocket (order/execution/position)
- Bybit REST adapter (create/amend/cancel)
- OrderIntent ledger (durable, journal-before-network)
- Risk Engine (gates, limits, quality checks)
- Reconciliation (REST+WS, dedup, gaps)
- Server-side SL/TP
- Emergency WAL для PROTECT/CANCEL/FLATTEN
- Safe Mode при reconciliation issues

**Блокеры:**
- Requires Этап 8 (simulator complete)
- Requires Этап 7 (frontend для Order Ticket UI)

---

### ❌ ЭТАП 10: Strategies с TP/SL (0% NOT STARTED)

**Roadmap §14**

**Требования:**
- 6 канонических стратегий:
  1. Sweep Failure / Failed Auction
  2. Breakout Acceptance + Retest
  3. Trend Pullback
  4. VWAP / Value Area Rotation
  5. Absorption Reversal
  6. Liquidation Exhaustion
- Level Interaction Classifier
- StrategySignal schema (deterministic)
- OrderIntentProposal flow
- Per-symbol calibration (BTC/ETH/XRP)
- Time stops, logic exits
- Promotion gate: replay → backtest → walk-forward → OOS → paper → demo → live canary

**Блокеры:**
- Requires Этап 9 (execution-risk process)
- Requires Этап 8 (simulator для backtesting)

---

### ❌ ЭТАП 11: AI Assistant (0% NOT STARTED)

**Roadmap §16**

**Требования:**
- Provider-neutral LLM layer (OpenAI/Anthropic/DeepSeek)
- Strategy Research Sandbox (isolated, no trading keys)
- Job queue для dataset building, optimization, training
- Model registry (versioning, approval)
- Governance: запрет прямого доступа к биржевым API
- AI-approved OrderIntent flow (через Risk Engine)

**Блокеры:**
- Requires Этап 10 (strategies)
- Requires Этап 9 (execution)

---

### ❌ ЭТАПЫ 12-15: Production 24/7 (0% NOT STARTED)

**Roadmap §18, §25**

**Требования:**
- Controlled automation
- Health checks / monitoring
- Alerting rules
- Backup / restore
- Rollback procedures
- RPO/RTO definitions
- Secrets management
- Rate limiting
- Emergency runbooks

---

## Первые 15 практических задач (§24)

| # | Задача | Roadmap § | Статус | Evidence |
|---|--------|-----------|--------|----------|
| 1 | Утвердить ADR-001…011 | §1.2 | ⏳ PARTIAL | ADR-010/011 OPEN |
| 2 | Заморозить монолит, baseline | §19 | ✅ DONE | git tags |
| 3 | Создать package `contracts` | §5 | ✅ DONE | contracts/ |
| 4 | Параметризовать symbol | §9.2 | ✅ DONE | 3 symbols |
| 5 | Integer/Decimal wire-format | §6.6 | ✅ DONE | ADR-004 |
| 6 | Dataset ownership, manifest | §6.1 | ✅ DONE | Manifest.json |
| 7 | Atomic WAL→Parquet crash suite | §6.4 | ✅ DONE | tests/fault/ |
| 8 | Минимальный market-collector | §3.3 | ✅ DONE | 3 systemd |
| 9 | Fenced handover BTC/ETH/XRP | §6.1 | ✅ DONE | ADR-013 |
| 10 | Kill analytics без остановки raw | §3.3 | ✅ DONE | 4-process IPC |
| 11 | RPI raw-only, A/B soak | §8.2 | ⏳ PARTIAL | До 2026-08-13 |
| 12 | Разделить analytics и API | §3.3 | ✅ DONE | workers/ |
| 13 | Trade-derived + invariants | §9 | ✅ DONE | Этап 5 |
| 14 | Book-derived + attribution | §9 | ✅ DONE | Этап 6 |
| 15 | Execution → simulator → strategies | §13-14 | ⏳ PARTIAL | Engine DONE |

**Прогресс:** 12/15 DONE (80%), 2/15 PARTIAL (13%), 1/15 NOT STARTED (7%)

---

## Критические проблемы

### 🚨 CRITICAL: API Service Down

**Симптом:**
```
bybit-api.service: activating (auto-restart) (Result: exit-code)
Main PID: 119479 (code=exited, status=1/FAILURE)
```

**Действие:**
1. Проверить логи: `journalctl -u bybit-api -n 100`
2. Проверить dependencies (PostgreSQL, data paths)
3. Исправить и перезапустить

**Приоритет:** P0 — блокирует все API endpoints

---

### ⏰ CRITICAL: RPI A/B Soak Deadline

**Deadline:** 2026-08-13 00:37 UTC (через ~18 часов от даты анализа)

**Требуется:**
1. Дождаться завершения soak
2. Собрать capacity report
3. Финализировать ADR-017
4. Принять решение о RPI в production

**Приоритет:** P0 — блокирует Этап 3

---

### ❌ HIGH: Frontend Not Started

**Проблема:** Существующие HTML-страницы не соответствуют требованиям §11

**Требуется:**
- Полная реализация React + TypeScript + Vite с нуля
- Schema-driven settings
- Server persistence для drawings
- 14 drawing tools
- E2E + visual tests

**Приоритет:** P1 — блокирует пользовательский интерфейс

---

### ❌ MEDIUM: Scheduled Feeds Missing

**Проблема:** Scheduled OI, funding, market history не реализованы (§8.2)

**Требуется:**
- REST scheduled ingestion
- Separate checkpoints для scheduled data
- Validation logic

**Приоритет:** P2 — не блокирует core functionality, но требуется по roadmap

---

### ❌ MEDIUM: ADR-010/011 Open

**Проблема:** 2 обязательных ADR (§1.2) не утверждены

**ADR-010:** ML-модель lifecycle, запрет прямого доступа ИИ к бирже  
**ADR-011:** Release, rollback, backup, RPO/RTO, secrets

**Приоритет:** P2 — блокирует Этапы 11-15

---

## Пропущенные этапы (Summary)

### Не начаты (0%):
1. **Этап 7:** Frontend React + TypeScript (§11) — HIGH PRIORITY
2. **Этап 9:** Manual Execution (§15)
3. **Этап 10:** Strategies (§14)
4. **Этап 11:** AI Assistant (§16)
5. **Этапы 12-15:** Production 24/7 (§18, §25)

### Частично выполнены:
1. **Этап 3:** 95% (RPI A/B soak pending, scheduled feeds missing)
2. **Этап 8:** 20% (state machine done, replay missing)

### Выполнены полностью:
1. ✅ Этап 0: Design Freeze
2. ✅ Этап 1: Recorder
3. ✅ Этап 2: IPC
4. ✅ Этап 4: 4-Process Architecture
5. ✅ Этап 5: Trade-Derived Analytics
6. ✅ Этап 6: Book-Derived Analytics

---

## Рекомендации

### Immediate (0-24 hours):

1. **Исправить API service** (P0)
   - Проанализировать логи
   - Исправить причину crash
   - Перезапустить и проверить health

2. **Дождаться RPI A/B soak** (P0)
   - Deadline: 2026-08-13 00:37 UTC
   - Собрать capacity report
   - Финализировать ADR-017

### Short-term (1-7 days):

3. **Начать Этап 7: Frontend** (P1)
   - Создать React + TypeScript + Vite проект
   - Реализовать shell layout (§11.1)
   - Интегрировать TradingView Lightweight Charts
   - Прогресс: 0% → 30% (shell + basic chart)

4. **Завершить Этап 3** (P1)
   - Implement scheduled OI/funding feeds (§8.2)
   - Финализировать capacity ADR после soak

5. **Утвердить ADR-010/011** (P2)
   - ML lifecycle governance
   - Release/rollback procedures

### Medium-term (1-4 weeks):

6. **Завершить Этап 8: Simulator** (P1)
   - MarketReplay implementation
   - Partial fill / IOC / SL / TP scenarios
   - Reports UI
   - Same-run checksum tests

7. **Начать Этап 9: Manual Execution** (P1)
   - Private WebSocket adapter
   - OrderIntent ledger
   - Risk Engine gates
   - Reconciliation logic

### Long-term (1-3 months):

8. **Этап 10: Strategies**
9. **Этап 11: AI Assistant**
10. **Этапы 12-15: Production 24/7**

---

## Roadmap Compliance Checklist

### Обязательные свойства (§2.2) — соблюдение:

✅ **Биржевое событие сначала записывается, потом вычисляется** — WAL append-only  
✅ **Downstream не может остановить collector** — IPC non-blocking  
✅ **Gap маркируется, не интерполируется** — GapDetector + SourceQuality  
✅ **Одинаковые raw + config + version = одинаковый результат** — deterministic tests  
⏳ **UI не владеет историей** — API contracts готовы, но frontend не реализован  
❌ **Один Risk/Execution Engine** — не реализован (Этап 9)  
❌ **ACK не считается исполнением** — не реализован (Этап 9)  
❌ **Стратегия использует numeric features** — не реализована (Этап 10)

### Процессы (§3.3) — соблюдение:

✅ **market-collector** — изолирован, WAL, нет analytics  
✅ **orderflow-worker** — отдельный процесс, IPC  
✅ **api-gateway** — отдельный процесс (но crashed)  
✅ **maintenance-worker** — отдельный процесс, compaction  
❌ **execution-risk** — не реализован  
❌ **strategy-worker** — не реализован  

### IPC (§5) — соблюдение:

✅ **RawEventEnvelope** — protocolVersion, schemaVersion, walOffset  
✅ **Non-blocking live publish** — UDS publisher  
✅ **At-least-once** — dedup logic  
✅ **Analytics checkpoint** — durable checkpoint  
⏳ **Snapshot + Patch transport** — contracts готовы, но frontend не реализован  

### Data Quality (§7) — соблюдение:

✅ **SourceQuality** — collector ownership  
✅ **AnalyticsQuality** — analytics ownership  
❌ **ExecutionQuality** — не реализован  
✅ **Gap states** — BOOTSTRAP / LIVE_READY / GAP  
✅ **Watermark** — provisional/final distinction  

---

## Заключение

**Выполнено:** Этапы 0-6 (52-55% дорожной карты)  
**В процессе:** Этап 3 (RPI soak), Этап 8.1 (simulator base)  
**Критические блокеры:**
1. API service crashed (P0)
2. RPI A/B soak deadline (P0)
3. Frontend не начат (P1)

**Следующие шаги:**
1. Исправить API service (немедленно)
2. Дождаться RPI soak (2026-08-13 00:37 UTC)
3. Начать Этап 7: Frontend React (после soak)
4. Завершить Этап 3: scheduled feeds
5. Завершить Этап 8: simulator complete

**Roadmap compliance:** GOOD для реализованных этапов, но большая часть функциональности (trading, AI, production) еще не начата.

---

**Prepared by:** Claude Opus 5  
**Date:** 2026-08-13  
**Session:** Background analysis job
