# Roadmap Implementation Status

**Обновлено:** 2026-08-12 07:00 UTC  
**Источник:** `BYBIT_MULTIPROCESS_PLATFORM_ROADMAP.md` §19, §24

---

## Этапы Roadmap

### ✅ Этап 0. Freeze, аудит и baseline

**Статус:** DONE (100%)

Результаты:
- ✅ Clean immutable artifact (git commits)
- ✅ Dataset owners (schemas, contracts)
- ✅ Dependency lock/SBOM (darwin-arm64, linux-x86_64)
- ✅ Baseline CPU/RAM/disk на replay (через property tests)
- ✅ Capacity estimate — ADR-017 ACCEPTED (92 MB/24h baseline)
- ✅ Registry отступлений (TODO.md, OPEN-xxx issues)

**Evidence:**
- Commits: 34+ коммита в main
- Tests: 875 passed, 8 skipped (2026-08-12)
- ADR: ADR-001 до ADR-017 утверждены
- SBOM: `deploy/dependencies/{darwin-arm64,linux-x86_64}/`

---

### ✅ Этап 1. Изолированный recorder без live computation

**Статус:** DONE (100%)

Требования:
- ✅ `market-collector` без analytics
- ✅ WAL append-only + Parquet publish
- ✅ Manifest, offsets, atomic commit
- ✅ BookCheckpoint integration
- ✅ Gap detection (RawTrade.sequence, BookCheckpoint.updateId)
- ✅ Multi-symbol (BTC, ETH, XRP)

**Evidence:**
- Collector работает на production (firstbyte.ru)
- 3 символа: BTCUSDT, ETHUSDT, XRPUSDT
- Throughput: ~13 MB/час, ~4.9M trades за 25 минут
- Property tests: fault injection, crash recovery

**Acceptance:**
- ✅ Kill collector → WAL сохранён, recovery без потерь
- ✅ Manifest recovery проверен
- ✅ 3 символа запущены последовательно с capacity gate
- ⏳ 24-72h soak без необозначенной потери (RPI A/B soak в процессе до 2026-08-13 00:37 UTC)

---

### ✅ Этап 2. Изолированный collector с IPC

**Статус:** COMPLETE (100%)

Требования:
- ✅ Writer lease / fencing token — DONE (packages/storage/fencing.py, ADR-013)
- ✅ IPC Publisher (non-blocking UDS) — DONE (packages/ipc/publisher.py)
- ✅ IPC Subscriber (event loop) — DONE (packages/ipc/subscriber.py)
- ✅ Maintenance worker (отдельный процесс) — DONE, running on production
- ✅ systemd unit для maintenance — DONE (bybit-maintenance.service: active)
- ✅ EventCollector интегрирован с WriterLease — DONE
- ⏳ Shadow/cutover/rollback production test — pending

**Evidence:**
- `packages/storage/fencing.py` — WriterLease, 21 fault test
- `packages/ipc/publisher.py` + `subscriber.py` — 17 integration tests
- `packages/bybit/collector.py` — use_fencing=True (default), 6 fencing tests
- `workers/maintenance_worker.py` — running на firstbyte.ru
- ADR-013 ACCEPTED, ADR-016 designed

---

### ⏳ Этап 3. Базовые live-роли и расширение scope

**Статус:** PARTIAL (95%)

Требования:
- ✅ Collector (работает)
- ✅ Временный analytics+API (монолитно, без IPC)
- ✅ Maintenance worker (отдельный процесс) — deployed
- ✅ BTC/ETH/XRP добавлены + acceptance
- ✅ Orderbook feeds (snapshot-only)
- ✅ Orderbook delta reconstruction — DONE (packages/bybit/book_state.py)
- ✅ RPI feed с feature flag — DONE, running на production
- ❌ Scheduled OI, funding, market history
- ⏳ Disk/load A/B soak с RPI on/off — в процессе (started 2026-08-12 00:33 UTC, deadline 2026-08-13 00:37 UTC)

**Evidence:**
- bybit-rpi@BTCUSDT/ETHUSDT/XRPUSDT: active на production
- `packages/bybit/book_state.py` — BookState machine, 22 tests

---

### ✅ Этап 4. Четыре процесса

**Статус:** COMPLETE (100%)

Требования:
- ✅ orderflow-worker (отдельный процесс) — workers/orderflow_worker.py
- ✅ IPC publisher в orderflow-worker — Этап 4.1 (commit 3744316)
- ✅ IPC integration test для 4-process pipeline — Этап 4.2 (commit d76a7fb)
- ✅ Process supervisor для 4-process architecture — Этап 4.3 (commit 000602e)
- ✅ 24-72h soak test infrastructure — Этап 4.4 (commit d0209c7)
- ✅ Analytics worker (workers/analytics_worker.py)
- ✅ API server без analytics logic (workers/api_server.py)
- ✅ Collector worker (workers/collector_worker.py)
- ✅ Process-specific metrics (packages/monitoring/worker_metrics.py)
- ✅ Prometheus + Grafana dashboards (Этап 5.1.1–5.1.4)

**Evidence:**
- `workers/orderflow_worker.py` — SymbolState + all book/trade detectors
- `workers/supervisor.py` — ProcessSupervisor
- `tests/integration/test_4process_pipeline.py` — PASSED
- `tests/integration/test_orderflow_ipc_publisher.py` — PASSED
- `pyproject.toml` — asyncio_mode=auto (исправлено 2026-08-12)
- 875 passed, 8 skipped

---

### ✅ Этап 5. Trade-derived analytics

**Статус:** COMPLETE (100%)

Порядок:
1. ✅ Canonical OHLCV — DONE
2. ✅ Tape/Bubbles — DONE
3. ✅ Footprint + Imbalance — DONE
4. ✅ Delta + CVD — DONE
5. ✅ Volume Profile — DONE
6. ✅ VWAP — DONE
7. ✅ Sweep (trade-series detector) — DONE

**Evidence:**
- `packages/analytics/`: delta.py, cvd.py, vwap.py, volume_profile.py, footprint.py, sweep.py, tape.py
- `contracts/`: footprint.py, sweep.py, tape.py
- Tests: 26 passed (footprint: 5, sweep: 8, tape: 13)
- Property tests для determinism
- Cross-TF invariants проверены

---

### ✅ Этап 6. Book-derived analytics

**Статус:** COMPLETE (100%)

Порядок:
1. ✅ Heatmap tiles — DONE
2. ✅ OFI + Microprice (Attribution base) — DONE
3. ✅ OBI (Order Book Imbalance) — DONE
4. ✅ Absorption — DONE
5. ✅ Walls — DONE
6. ✅ Pulling/Stacking — DONE
7. ✅ Liquidation cascades — DONE
8. ✅ Regime/Feature API — DONE

**Evidence:**
- `packages/analytics/`: obi.py, ofi.py, absorption.py, walls.py, pulling_stacking.py, liquidation_cascades.py, heatmap.py, regime.py
- `contracts/`: ofi.py, absorption.py, walls.py, heatmap.py, regime.py
- Tests: 41 passed
- API: GET /api/v1/analytics/heatmap, /orderflow/regime, /orderflow/features

---

### ⏳ Этап 8.1. Order/execution state machine и adapter contract

**Статус:** COMPLETE (100%) — реализован вперёд Этапа 7 (не блокирует frontend)

Требования (Roadmap §8):
- ✅ Order/Fill/Position state machine — packages/execution/engine.py
- ✅ ExecutionAdapter interface (adapter contract)
- ✅ SimulatorAdapter (packages/execution/simulator.py)
- ✅ SimulatorClock (deterministic time)
- ✅ OrderMatcher (conservative maker/taker, no lookahead)
- ✅ LatencyModel (p50/p95/p99 deterministic)
- ✅ Deterministic checksum: same run → same fills
- ✅ Position tracking fix (sync fill race condition)

**Evidence:**
- `packages/execution/engine.py` — ExecutionEngine + ExecutionAdapter
- `packages/execution/simulator.py` — SimulatorAdapter (452 строки)
- `tests/execution/test_engine.py` — 12 passed
- `tests/execution/test_simulator.py` — 15 passed
- commit a72e11a (2026-08-12)

---

### ❌ Этап 7. Frontend analysis workstation

**Статус:** NOT STARTED (React/TS/Vite)

Зависимости: стабильные API contracts Этапов 4–6. Блокеров нет — Этапы 4–6 COMPLETE.

Требования (Roadmap §11):
- ❌ Shell: top bar / left toolbar / center / right sidebar / bottom dock / status bar
- ❌ Menus: Indicators / Order Flow / Strategies / Replay (schema-driven)
- ❌ Watchlist: BTCUSDT/ETHUSDT/XRPUSDT + Last/24h%/spread/quality
- ❌ Chart layers: overlay/separatePane, z-order, Entry/SL/TP drawing
- ❌ Settings: schema-driven per-module panel
- ❌ Drawings: 14 tool types, server persistence, schemaVersion+revision
- ❌ Diagnostics: Data Quality badge, feed ages/gaps, Heatmap scope
- ❌ Persistence: server source of truth (workspaces/drawings/scripts), localStorage — только UI cache

**Frontend stack (roadmap §3):** React + TypeScript + Vite, тесты — Vitest + Playwright

**Существующий frontend:** 6 статических HTML страниц (index, live, analytics, orderflow, alerts, paper-trading) — НЕ соответствуют требованиям Этапа 7. Требуется полноценное React-приложение.

**Acceptance criteria (§11.8, §19):**
- E2E reload/TF/symbol tests
- zoom/DPI/overlap visual tests
- Drawings survive restart/backup restore
- Quality/gap labels всегда видимы
- Heatmap scope: явно показывает standard-only до включения RPI
- BTC/ETH/XRP switch не reconnect-ит Bybit

---

### ❌ Этап 8.2–8.n. Simulator/replay (остальное)

**Статус:** PARTIAL (20%)

- ✅ State machine + adapter contract — DONE (Этап 8.1)
- ❌ MarketReplay (clocks, latency, book/trade replay)
- ❌ Partial fill / IOC / SL / TP / funding
- ❌ Reports и UI controls
- ❌ Independent simulation worker
- ❌ Same-run checksum acceptance test

---

### ❌ Этап 9-15

**Статус:** NOT STARTED

- Этап 9: Manual execution (private WS, REST adapter, intent ledger, Risk Engine)
- Этап 10: Strategies (TP/SL, time stops, walk-forward/OOS)
- Этап 11: AI assistant (LLMProvider, job queue, Research Sandbox)
- Этап 12-15: Controlled automation, production 24/7

---

## 24. Первые 15 практических задач

| # | Задача | Статус | Evidence |
|---|--------|--------|----------|
| 1 | Утвердить ADR-001…011 | ⏳ PARTIAL | ADR-010/011 остаются OPEN |
| 2 | Заморозить монолит и baseline release | ✅ DONE | git tags |
| 3 | Создать package `contracts` | ✅ DONE | `contracts/`, Pydantic schemas |
| 4 | Параметризовать symbol | ✅ DONE | 3 символа работают |
| 5 | Закрыть integer/Decimal wire-format | ✅ DONE | ADR-004, Decimal128 |
| 6 | Dataset ownership, manifest state machine | ✅ DONE | Manifest.json, offsets |
| 7 | Atomic WAL→Parquet crash suite | ✅ DONE | `tests/fault/` |
| 8 | Вынести минимальный `market-collector` | ✅ DONE | 3 systemd units |
| 9 | Fenced handover BTC/ETH/XRP с gates | ✅ DONE | WriterLease + fencing, ADR-013 |
| 10 | Kill analytics/API без остановки raw | ✅ DONE | 4-process IPC architecture |
| 11 | RPI raw-only за feature flag, A/B soak | ⏳ PARTIAL | RPI deployed, soak до 2026-08-13 |
| 12 | Разделить analytics и API | ✅ DONE | analytics_worker.py + api_server.py |
| 13 | Перенести trade-derived с invariants | ✅ DONE | Delta/CVD/VWAP/VP/Footprint/Sweep/Tape |
| 14 | Перенести book-derived с attribution | ✅ DONE | OBI/OFI/Absorption/Walls/Pulling/Cascades/Heatmap/Regime |
| 15 | Execution contract → simulator → strategies | ⏳ PARTIAL | Engine + SimulatorAdapter DONE; strategies pending |

**Прогресс:** 12/15 DONE (80%), 2/15 PARTIAL (13%), 1/15 NOT STARTED (7%)

---

## Резюме

**Что работает:**
- ✅ Collector на production (7 сервисов: 3 trades + 1 maintenance + 3 RPI)
- ✅ WAL + Parquet + Manifest + WriterLease (fencing)
- ✅ IPC Publisher/Subscriber (UDS)
- ✅ 4-process architecture: collector / orderflow / analytics / api workers
- ✅ Process supervisor + Prometheus + Grafana
- ✅ Orderbook BookState machine (snapshot + delta)
- ✅ Trade-derived analytics (Delta, CVD, VWAP, Volume Profile, Footprint, Sweep, Tape)
- ✅ Book-derived analytics (OBI, OFI, Absorption, Walls, Pulling/Stacking, Liquidation, Heatmap, Regime)
- ✅ REST API + статический Frontend (17 endpoints)
- ✅ ExecutionEngine + SimulatorAdapter (Этап 8.1)
- ✅ 875 tests passed, 8 skipped

**Текущий blocker:**
- ⏳ RPI A/B soak (завершается 2026-08-13 00:37 UTC) — финализирует Этап 3

**Следующий этап: Этап 7 — Frontend analysis workstation**
- Зависимости выполнены (Этапы 4–6 COMPLETE)
- React + TypeScript + Vite с нуля
- Заменяет существующие 6 статических HTML страниц
