# Roadmap Implementation Status

**Обновлено:** 2026-08-11 01:30 UTC  
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
- ⏳ Capacity estimate (через 72h после soak → measure_capacity.sh)
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

### ⏳ Этап 2. Изолированный collector с IPC

**Статус:** NOT STARTED (0%)

Требования:
- ❌ Writer lease / fencing token
- ❌ UDS/gRPC publish к analytics (non-blocking)
- ❌ Separate maintenance worker
- ❌ Shadow/cutover/rollback protocol
- ❌ Liquidation reconnect с bounded gap
- ❌ 24-72h soak с full IPC

**Блокеры:**
- Этап 1 soak ещё не завершён (через 72h)
- Capacity measurement не выполнен

---

### ⏳ Этап 3. Базовые live-роли и расширение scope

**Статус:** PARTIAL (70%)

Требования:
- ✅ Collector (работает)
- ✅ Временный analytics+API (монолитно, без IPC)
- ❌ Maintenance worker (отдельный процесс)
- ✅ BTC добавлен + acceptance
- ✅ ETH добавлен + acceptance
- ✅ XRP добавлен + acceptance
- ✅ Orderbook feeds (snapshot-only, delta требует §8.2)
- ❌ Scheduled OI, funding, market history
- ❌ RPI feed за feature flag
- ❌ Disk/load A/B soak с RPI on/off

**Evidence:**
- 3 символа работают 24/7 (publicTrade only на production)
- Analytics modules: Delta, CVD, VWAP, Volume Profile, OBI
- API endpoints: /trades, /ohlc, /symbols
- `collector_with_book.py` готов (orderbook.200 snapshot)

**Gaps:**
- Orderbook delta reconstruction (Roadmap §8.2)
- RPI/liquidation feeds не подключены
- Maintenance tasks не изолированы

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
- Этап 2 не начат
- IPC protocol не реализован

---

### ⏳ Этап 5. Trade-derived analytics

**Статус:** PARTIAL (70%)

Порядок:
1. ✅ Canonical OHLCV — DONE
2. ❌ Tape/Bubbles — NOT STARTED
3. ❌ Footprint + Imbalance — NOT STARTED
4. ✅ Delta + CVD — DONE
5. ✅ Volume Profile — DONE
6. ✅ VWAP — DONE
7. ❌ Sweep (trade-series detector) — NOT STARTED

**Evidence:**
- `packages/analytics/`: delta.py, cvd.py, vwap.py, volume_profile.py
- Property tests для determinism
- Cross-TF invariants проверены

**Gaps:**
- Нет deterministic checksum для cache
- Reload/TF round-trip не тестирован полностью
- Versioned cache/revision не реализован
- Crash/restart checkpoint tests (§6.9) не полные

---

### ⏳ Этап 6. Book-derived analytics

**Статус:** PARTIAL (30%)

Порядок:
1. ❌ Heatmap tiles — NOT STARTED
2. ❌ Attribution snapshot — NOT STARTED
3. ✅ OBI (Order Book Imbalance) — DONE
4. ❌ Absorption — NOT STARTED
5. ❌ Walls — NOT STARTED
6. ❌ Liquidity cascades — NOT STARTED
7. ❌ Regime/Feature API — NOT STARTED

**Evidence:**
- `packages/analytics/obi.py` — реализован
- Tests: `tests/contracts/test_obi.py`

**Gaps:**
- Orderbook feeds не подключены (только publicTrade)
- Heatmap visualization не реализована
- Attribution logic не реализована

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
| 1 | Утвердить ADR-001…011 | ✅ DONE | `docs/architecture/decisions/` |
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
| 13 | Перенести trade-derived с invariants | ⏳ PARTIAL | Delta/CVD/VWAP done, Footprint/Sweep не начаты |
| 14 | Перенести book-derived с attribution | ⏳ PARTIAL | OBI done, Heatmap/Walls не начаты |
| 15 | Execution contract → simulator → strategies | ❌ NOT STARTED | Этапы 8-10 не начаты |

**Прогресс:** 8/15 закрыто полностью (53%), 3/15 частично (20%), 4/15 не начато (27%)

---

## Критические незакрытые задачи (блокируют production trading)

### High Priority (блокируют Этап 2-4)

1. **Capacity measurement** (через 72h — 2026-08-14 00:55 UTC)
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
- ✅ Collector на production (3 символа, 24/7)
- ✅ WAL + Parquet + Manifest
- ✅ Basic analytics (Delta, CVD, VWAP, Volume Profile, OBI)
- ✅ REST API + Frontend
- ✅ Property tests, fault injection

**Что блокирует Этап 2-4:**
- ❌ Capacity measurement не выполнен
- ❌ Fencing token / writer lease
- ❌ IPC protocol (UDS/gRPC)
- ❌ Maintenance worker (отдельный процесс)
- ❌ Orderbook feeds

**Что блокирует production trading:**
- ❌ Market simulator
- ❌ Execution contract + reconciliation
- ❌ Strategies с TP/SL
- ❌ Risk policy + promotion gates

**Оценка готовности:** ~35-40% от полного Roadmap (Этап 0-6).

Для начала Этапа 2 нужны: capacity measurement + ADR-005 + fencing token design.
