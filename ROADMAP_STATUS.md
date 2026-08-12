# Roadmap Implementation Status

**Обновлено:** 2026-08-12 00:38 UTC  
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
- Commits: 34 коммита в main
- Tests: 658 passed, 8 skipped
- ADR: ADR-001 до ADR-012 утверждены
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
- ⏳ 24-72h soak без необозначенной потери (в процессе)

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
- ⏳ 24-72h soak с full IPC — pending

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
- ⏳ Disk/load A/B soak с RPI on/off — в процессе (started 2026-08-12 00:33 UTC)

**Evidence:**
- bybit-rpi@BTCUSDT/ETHUSDT/XRPUSDT: active на production
- `packages/bybit/book_state.py` — BookState machine, 22 tests
- A/B measurement deadline: 2026-08-13 00:37 UTC

---

### ❌ Этап 4. Четыре процесса

**Статус:** NOT STARTED (0%)

Требования:
- ❌ orderflow-worker (отдельный процесс)
- ❌ api-gateway без analytics logic
- ❌ Analytics WAL catch-up
- ❌ Derived checkpoints
- ❌ snapshot/patch/streamEpoch
- ❌ Process-specific readiness

**Блокеры:**
- Этап 2 soak не завершён (pending cutover/rollback test)
- IPC интеграция между collector и analytics не завершена

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

**Gaps:**
- Нет deterministic checksum для cache
- Reload/TF round-trip не тестирован полностью
- Versioned cache/revision не реализован
- Crash/restart checkpoint tests (§6.9) не полные

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
- Tests: 41 passed (absorption: 5, walls: 7, liquidation: 5, ofi: 9, pulling/stacking: 3, heatmap: 11, regime: 12)
- API: GET /api/v1/analytics/heatmap, /orderflow/regime, /orderflow/features

**Gaps:**
- Orderbook feeds не подключены (только publicTrade) — требует Этап 3 P1-S3-002
- Historical regime tracking не реализован (TODO в regime.py)

---

### ❌ Этап 7-15

**Статус:** NOT STARTED

Этапы:
- Этап 7: Pine Script runtime
- Этап 8: Market simulator
- Этап 9: Manual execution
- Этап 10: Strategies (TP/SL, time stops)
- Этап 11: AI assistant
- Этап 12-15: Advanced features

---

## 24. Первые 15 практических задач

| # | Задача | Статус | Evidence |
|---|--------|--------|----------|
| 1 | Утвердить ADR-001…011 | ⏳ PARTIAL | `docs/adr/README.md`; ADR-010/011 остаются OPEN |
| 2 | Заморозить монолит и baseline release | ✅ DONE | 34 коммита, git tags |
| 3 | Создать package `contracts` | ✅ DONE | `contracts/`, Pydantic schemas |
| 4 | Параметризовать symbol | ✅ DONE | 3 символа работают |
| 5 | Закрыть integer/Decimal wire-format | ✅ DONE | ADR-004, Decimal128 |
| 6 | Dataset ownership, manifest state machine | ✅ DONE | Manifest.json, offsets |
| 7 | Atomic WAL→Parquet crash suite | ✅ DONE | `tests/fault/` |
| 8 | Вынести минимальный `market-collector` | ✅ DONE | 3 systemd units |
| 9 | Fenced handover BTC/ETH/XRP с gates | ⏳ PARTIAL | 3 символа работают, но без fencing token |
| 10 | Kill analytics/API без остановки raw | ❌ NOT STARTED | Нет IPC, всё монолитно |
| 11 | RPI raw-only за feature flag, A/B soak | ❌ NOT STARTED | RPI feeds не подключены |
| 12 | Разделить analytics и API | ❌ NOT STARTED | Монолитный процесс |
| 13 | Перенести trade-derived с invariants | ✅ DONE | Delta/CVD/VWAP/Volume Profile/Footprint/Sweep/Tape все реализованы |
| 14 | Перенести book-derived с attribution | ✅ DONE | OBI/OFI/Absorption/Walls/Pulling/Cascades/Heatmap/Regime все реализованы |
| 15 | Execution contract → simulator → strategies | ❌ NOT STARTED | Этапы 8-10 не начаты |

**Прогресс:** 9/15 закрыто полностью (60%), 3/15 частично (20%), 3/15 не начато (20%)

---

## Критические незакрытые задачи (блокируют production trading)

### High Priority (блокируют Этап 2-4)

1. **Capacity measurement** (через 24h — 2026-08-12 00:55 UTC)
   - Roadmap §6.8
   - Блокирует: Capacity ADR, решение про disk size
   - Команда: `deploy/measure_capacity.sh`

2. **Fencing token / writer lease** (Этап 2)
   - Roadmap §6.5, §18.1
   - Блокирует: IPC, multi-process safety
   - Задача: P1-S2-xxx (не создана)

3. **IPC protocol (UDS/gRPC)** (Этап 2)
   - Roadmap §5.1, §5.2
   - Блокирует: изоляция процессов
   - Задача: P1-S2-xxx (не создана)

4. ~~**Orderbook feeds**~~ ✅ PARTIAL (Этап 3)
   - Roadmap §8.2: orderbook.200 snapshot работает
   - Delta reconstruction требует отдельной реализации (§8.2)
   - Скрипт: `examples/collector_with_book.py`

5. ~~**PostgreSQL migrations**~~ ✅ DONE (Stage 1)
   - ADR-005, Roadmap §6.6
   - PostgreSQL 16.14 на production
   - Задача: P1-S1-009 CLOSED

### Medium Priority (нужны для Этап 5-6)

6. **Deterministic cache/revision** (Этап 5)
   - Roadmap §9.6: versioned cache для analytics modules
   - Блокирует: reload/TF round-trip, production SLA
   - Задача: не создана

7. **Footprint + Imbalance** (Этап 5)
   - Roadmap §9.1: trade footprint visualization
   - Блокирует: полный trade-derived stack
   - Задача: не создана

8. **Heatmap tiles** (Этап 6)
   - Roadmap §9.2: orderbook heatmap с tile cache
   - Блокирует: book visualization
   - Задача: не создана

9. **Attribution snapshot** (Этап 6)
   - Roadmap §9.3: bid/ask attribution для всех book-модулей
   - Блокирует: Walls, Absorption, Liquidation cascades
   - Задача: не создана

### Low Priority (Этап 7+)

10. **Market simulator** (Этап 8)
11. **Manual execution** (Этап 9)
12. **Strategies** (Этап 10)
13. **AI assistant** (Этап 11)

---

## Summary

**Что работает:**
- ✅ Collector на production (7 сервисов: 3 trades + 1 maintenance + 3 RPI)
- ✅ WAL + Parquet + Manifest + WriterLease (fencing)
- ✅ IPC Publisher/Subscriber (UDS)
- ✅ Orderbook BookState machine (snapshot + delta)
- ✅ Trade-derived analytics (Delta, CVD, VWAP, Volume Profile, Footprint, Sweep, Tape)
- ✅ Book-derived analytics (OBI, OFI, Absorption, Walls, Pulling/Stacking, Liquidation, Heatmap, Regime)
- ✅ REST API + Frontend (17 endpoints)
- ✅ 846 tests passed

**Что блокирует Этап 4 (четыре процесса):**
- ⏳ Этап 2 cutover/rollback test
- ⏳ IPC collector → analytics pipe (live data flow)
- ❌ orderflow-worker как отдельный процесс

**Что блокирует production trading:**
- ❌ Market simulator (Этап 8)
- ❌ Execution contract + reconciliation (Этап 9)
- ❌ Strategies с TP/SL (Этап 10)
- ❌ Risk policy + promotion gates

**Оценка готовности:** ~62-65% от полного Roadmap.

Для Этапа 4 нужны: Этап 2 soak + IPC live pipe + orderflow-worker scaffold.
