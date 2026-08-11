# Changelog

Все значимые изменения в проекте документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Planned
- Этап 2: Multi-process isolation (IPC + Fencing Token)
- Этап 3: Orderbook delta reconstruction
- Capacity ADR (после measurement 2026-08-14)

---

## [0.6.0] - 2026-08-11

### Added — Этап 6: Book-Derived Analytics (COMPLETE)

**Heatmap tiles (Roadmap §9.2):**
- `contracts/heatmap.py` — HeatmapTile schema + QueryParams
- `packages/analytics/heatmap.py` — tile aggregator с price/time binning
- `GET /api/v1/analytics/heatmap` — API endpoint
- 11 unit tests + 6 property tests

**Regime/Feature API (Roadmap §9.1):**
- `contracts/regime.py` — MarketRegime enum (6 types) + schemas
- `packages/analytics/regime.py` — multi-feature detector
- `GET /api/v1/analytics/orderflow/regime` — regime classification
- `GET /api/v1/analytics/orderflow/features` — feature list
- 12 unit tests + 11 property tests

**Documentation:**
- `packages/analytics/README.md` — полное описание 18 модулей
- `docs/adr/ADR-014-heatmap-tile-design.md`
- `docs/adr/ADR-015-regime-classification.md`
- `docs/adr/ADR-016-ipc-protocol.md`

**Tests:**
- `tests/integration/test_heatmap_api.py` — 7 integration tests
- `tests/integration/test_regime_api.py` — 12 integration tests
- `tests/analytics/test_heatmap_properties.py` — 6 property tests
- `tests/analytics/test_regime_properties.py` — 11 property tests

### Changed
- `ROADMAP_STATUS.md` — Этап 6: 71% → 100%
- `pyproject.toml` — добавлен marker `analytics`
- `packages/api/app.py` — добавлено 3 новых endpoint

### Performance
- Total tests: 763 → 780 passed (+17)
- Analytics modules: 16 → 18 (+2)
- API endpoints: 14 → 17 (+3)
- Lines of code (analytics): 2600 → 2852 (+252)

---

## [0.5.0] - 2026-08-10

### Added — Этап 5: Trade-Derived Analytics (COMPLETE)

**Footprint Chart (Roadmap §9.1 Этап 5):**
- `contracts/footprint.py` — FootprintBar schema
- `packages/analytics/footprint.py` — bid/ask volume aggregation per price level
- 5 unit tests

**Tape/Bubbles (Roadmap §9.1 Этап 5, пункт 2):**
- `contracts/tape.py` — TapeEntry, Bubble schemas
- `packages/analytics/tape.py` — TapeFilter + BubbleAggregator
- Size categories: small/medium/large/block
- 13 unit tests

**Sweep Detector (Roadmap §9.1 Этап 5, пункт 7):**
- `contracts/sweep.py` — SweepEvent schema
- `packages/analytics/sweep.py` — multi-level sweep detection
- Chunk-boundary independence
- 8 unit tests

**OFI + Microprice (Roadmap §9.1 Этап 6, пункт 2):**
- `contracts/ofi.py` — OFIResult schema
- `packages/analytics/ofi.py` — Order Flow Imbalance + microprice calculation
- 9 unit tests

**Absorption (Roadmap §9.1 Этап 6, пункт 4):**
- `contracts/absorption.py` — AbsorptionEvent schema
- `packages/analytics/absorption.py` — liquidity absorption detector
- 5 unit tests

**Walls (Roadmap §9.1 Этап 6, пункт 5):**
- `contracts/walls.py` — WallEvent schema
- `packages/analytics/walls.py` — bid/ask wall detector
- Wall lifetime tracking
- 7 unit tests

**Pulling/Stacking (Roadmap §9.1 Этап 6, пункт 6):**
- `packages/analytics/pulling_stacking.py` — order manipulation detector
- 3 unit tests

**Liquidation Cascades (Roadmap §9.1 Этап 6, пункт 7):**
- `packages/analytics/liquidation_cascades.py` — cascade detector
- 5 unit tests

### Changed
- `ROADMAP_STATUS.md` — Этап 5: 70% → 100%, Этап 6: 30% → 71%

### Performance
- Total tests: 658 → 744 passed (+86)
- Analytics modules: 10 → 16 (+6)

---

## [0.4.0] - 2026-08-10

### Added — Stage 1 Complete

**RPI Feed Collector (P1-S3-001):**
- `contracts/raw_kline.py` — RawKline schema
- `packages/bybit/deserializer_kline.py` — kline deserializer
- `examples/rpi_collector.py` — RPI collector с feature flag
- 8 contract tests

**PostgreSQL Schema (P1-S1-009):**
- `deploy/postgres/init_schema.sql` — 3 tables, 9 indices
- Tables: workspace (5 fields), audit_log (10 fields), orders (23 fields)
- PostgreSQL 16.14 на production (148.113.178.18:5432)

**GitHub CI Workflow (P1-S1-007):**
- `.github/workflows/ci.yml` — 2 jobs (test, lint)
- Ubuntu 24.04 runner
- Python 3.12 + uv package manager
- Dependency lock verification + full test suite

**Documentation:**
- ADR-013: Writer Lease и Fencing Token
- `NEXT.md` — updated для Stage 1 complete handoff
- `TODO.md` — Stage 2-3 tasks added

### Changed
- Linux dependency lock (darwin → linux-x86_64)
- `deploy/dependencies/linux-x86_64/requirements.lock` — 137 строк
- Stage 1 status: PARTIAL → COMPLETE (9/9 tasks)

### Fixed
- `tests/contracts/test_dependency_lock.py` — Linux artifacts detection

### Performance
- Total tests: 330 → 658 passed (+328)
- CI green on first run

---

## [0.3.0] - 2026-08-10

### Added — Analytics Baseline

**Delta + CVD:**
- `packages/analytics/delta.py` — buy/sell volume delta
- `packages/analytics/cvd.py` — cumulative volume delta

**VWAP:**
- `packages/analytics/vwap.py` — volume-weighted average price

**Volume Profile:**
- `packages/analytics/volume_profile.py` — price level distribution
- POC/VAL/VAH calculation

**OBI (Order Book Imbalance):**
- `packages/analytics/obi.py` — bid/ask imbalance
- `tests/contracts/test_obi.py`

### Changed
- `packages/api/app.py` — добавлены analytics endpoints
- API count: 10 → 14 endpoints

---

## [0.2.0] - 2026-08-10

### Added — Storage Core

**Dependency Management (P1-S1-003):**
- `deploy/gen_dependency_artifacts.py` — lock + SBOM generator
- `deploy/verify_dependencies.py` — verifier с --release gate
- `deploy/dependencies/darwin-arm64/requirements.lock` — 9 packages
- CycloneDX 1.5 SBOM format

**Parquet Writer (P1-S1-004):**
- `packages/storage/parquet_writer.py` — PyArrow writer
- Arrow schema с Decimal128(18,4)
- Footer validation
- 10 unit tests + 2 skipped

**Property Tests (P1-S1-005):**
- Hypothesis integration
- Frame round-trip properties
- Arbitrary truncation recovery
- Offset invariants (24-op sequences)
- 29 property tests

**ADR:**
- ADR-004: Decimal128 precision/scale (ACCEPTED)
- ADR-012: Development and production hosts (ACCEPTED)

### Changed
- `pyproject.toml` — добавлен marker `property`
- `requirements.in` — Hypothesis 6.165.2

### Fixed
- Test markers: все файлы имеют pytestmark
- `tests/contracts/test_dependency_lock.py` — dynamic requirements.in parsing

### Performance
- Total tests: 91 → 330 passed (+239)

---

## [0.1.0] - 2026-08-10

### Added — Stage 1 Foundation

**Contracts Package (P1-S1-001):**
- `contracts/schemas.py` — Pydantic models (RawTrade, RawBookEvent, etc.)
- `packages/numeric/` — integer/Decimal precision model
- 55 contract tests

**Storage Package (P1-S1-002):**
- `packages/storage/offsets.py` — offset state machine
- `packages/storage/frames.py` — length+CRC32 framing
- `packages/storage/wal.py` — append-only WAL
- `packages/storage/segment_state.py` — 5-state machine
- `packages/storage/manifest.py` — atomic manifest updates
- `packages/storage/atomic_commit.py` — fsync protocol
- 101 storage tests
- 16 crash-matrix tests

**ADR:**
- ADR-001 до ADR-003: основные design decisions
- All PROPOSED → ACCEPTED

### Changed
- Python 3.12+ required
- Repository structure established

### Performance
- Initial test suite: 156 tests passed

---

## [0.0.0] - 2026-08-10

### Added — Greenfield Bootstrap

**Stage 0 Complete:**
- Repository initialization (`git init -b main`)
- `.gitignore` по стеку (Python, Node, secrets, data, macOS)
- `docs/specifications/source/` — 6 нормативных документов
- `docs/architecture/` — CURRENT, TARGET, DECISIONS_PENDING
- `docs/adr/README.md` — ADR process
- `docs/REQUIREMENTS_TRACEABILITY.md` — 63 требования
- Directory structure (§3.5 Roadmap)
- `NEXT.md`, `TODO.md`, `README.md`

**Проверки Stage 0:**
- SHA-256 verification всех spec files
- Нет remote
- Нет API keys/secrets
- Нет production data
- Нет заявлений о реализованных функциях

### First Commit
- `6edc666` — Greenfield bootstrap и Stage 0 complete

---

## Legend

- **Added** — новая функциональность
- **Changed** — изменения в существующей функциональности
- **Deprecated** — функциональность будет удалена в будущем
- **Removed** — удалённая функциональность
- **Fixed** — исправления багов
- **Security** — изменения безопасности
- **Performance** — метрики производительности

---

## References

- Roadmap: `BYBIT_MULTIPROCESS_PLATFORM_ROADMAP.md`
- Status: `ROADMAP_STATUS.md`
- Tasks: `TODO.md`
- Current: `NEXT.md`
