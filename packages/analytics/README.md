# Analytics Modules

**Обновлено:** 2026-08-11  
**Статус:** Этап 5 (100%) + Этап 6 (100%) реализованы

---

## Обзор

Модуль `packages/analytics/` содержит все trade-derived и book-derived analytics для orderflow analysis.

**Всего модулей:** 18  
**Tests:** 66 passed (analytics marker)  
**API endpoints:** 8 analytics endpoints

---

## Trade-Derived Analytics (Этап 5)

### 1. Delta (`delta.py`)

**Описание:** Разница между buy volume и sell volume по временным окнам.

**Usage:**
```python
from packages.analytics.delta import aggregate_delta_by_interval

delta_bars = aggregate_delta_by_interval(trades, interval_us=60_000_000)
for bar in delta_bars:
    print(f"Delta: {bar['buy_volume'] - bar['sell_volume']}")
```

**API:** `GET /api/v1/analytics/delta`

---

### 2. CVD (Cumulative Volume Delta) (`cvd.py`)

**Описание:** Кумулятивная сумма delta для выявления долгосрочного pressure.

**Usage:**
```python
from packages.analytics.cvd import compute_cvd

cvd_values = compute_cvd(delta_bars)
print(f"CVD: {cvd_values[-1]}")  # Current CVD
```

**API:** `GET /api/v1/analytics/cvd`

---

### 3. VWAP (Volume-Weighted Average Price) (`vwap.py`)

**Описание:** Средневзвешенная цена по объёму для справедливой оценки.

**Usage:**
```python
from packages.analytics.vwap import VWAPCalculator

vwap = VWAPCalculator()
for trade in trades:
    vwap.add_trade(trade)

print(f"VWAP: {vwap.get_vwap()}")
```

**API:** `GET /api/v1/analytics/vwap`

---

### 4. Volume Profile (`volume_profile.py`)

**Описание:** Распределение volume по ценовым уровням для определения POC/VAL/VAH.

**Usage:**
```python
from packages.analytics.volume_profile import VolumeProfileCalculator

profile = VolumeProfileCalculator(tick_size=Decimal("0.1"))
for trade in trades:
    profile.add_trade(trade)

result = profile.build()
print(f"POC: {result.poc_price_ticks}, VAL: {result.val_price_ticks}")
```

**API:** `GET /api/v1/analytics/volume-profile`

---

### 5. Footprint (`footprint.py`)

**Описання:** Bid/ask volume aggregation по price levels для footprint chart.

**Usage:**
```python
from packages.analytics.footprint import FootprintAggregator

aggregator = FootprintAggregator(
    venue="BYBIT",
    symbol="BTCUSDT",
    interval_seconds=60,
    tick_size=Decimal("0.1"),
    step_size=Decimal("0.001"),
)

for trade in trades:
    aggregator.add_trade(trade)

footprint = aggregator.build()
for level in footprint.levels:
    print(f"Price: {level.price_ticks}, Bid: {level.bid_volume}, Ask: {level.ask_volume}")
```

**Tests:** `tests/analytics/test_footprint.py` (5 tests)

---

### 6. Sweep Detector (`sweep.py`)

**Описание:** Детектор серий агрессивных сделок через несколько price levels за короткое время.

**Usage:**
```python
from packages.analytics.sweep import SweepDetector

detector = SweepDetector(min_levels=3, window_ms=500)
for trade in trades:
    event = detector.process(trade)
    if event:
        print(f"Sweep: {event.direction}, {event.levels_swept} levels")

# Flush незакрытые chains
for event in detector.flush():
    print(f"Sweep: {event}")
```

**Roadmap:** §9.1 Этап 5, пункт 7  
**Tests:** `tests/analytics/test_sweep.py` (8 tests)

---

### 7. Tape/Bubbles (`tape.py`)

**Описание:** Детектор крупных сделок (bubbles) и их кластеризация.

**Usage:**
```python
from packages.analytics.tape import TapeFilter, BubbleAggregator

# Filter large trades
tape_filter = TapeFilter(min_qty_steps=1000)
for trade in trades:
    entry = tape_filter.process(trade)
    if entry:
        print(f"Large trade: {entry.qty_steps} @ {entry.price_ticks}")

# Aggregate bubbles
bubbles = BubbleAggregator(merge_window_ms=5000)
for trade in trades:
    bubbles.process(trade)

for bubble in bubbles.get_bubbles():
    print(f"Bubble: {bubble.total_qty} @ {bubble.avg_price_ticks}")
```

**Roadmap:** §9.1 Этап 5, пункт 2  
**Tests:** `tests/analytics/test_tape.py` (13 tests)

---

## Book-Derived Analytics (Этап 6)

### 8. OBI (Order Book Imbalance) (`obi.py`)

**Описание:** Дисбаланс между bid и ask volume на top of book.

**Usage:**
```python
from packages.analytics.obi import OBICalculator

obi = OBICalculator()
for book_event in book_events:
    result = obi.process(book_event)
    if result:
        print(f"OBI: {result['imbalance']:.2f}")
```

**API:** Часть `/api/v1/analytics/orderflow/features`  
**Tests:** `tests/contracts/test_obi.py`

---

### 9. OFI (Order Flow Imbalance) + Microprice (`ofi.py`)

**Описание:** Изменение bid/ask volume между snapshots + microprice calculation.

**Usage:**
```python
from packages.analytics.ofi import OFICalculator

ofi = OFICalculator()
for book_event in book_events:
    result = ofi.process(book_event)
    if result:
        print(f"OFI: {result.ofi:.2f}, Microprice: {result.microprice}")
```

**Roadmap:** §9.1 Этап 6, пункт 2  
**Tests:** `tests/analytics/test_ofi.py` (9 tests)

---

### 10. Absorption (`absorption.py`)

**Описание:** Детектор поглощения ликвидности на price level.

**Usage:**
```python
from packages.analytics.absorption import AbsorptionDetector

detector = AbsorptionDetector(window_ms=3000, min_qty_threshold=5000)
for trade in trades:
    event = detector.process(trade)
    if event:
        print(f"Absorption at {event.price_ticks}: {event.absorbed_qty} absorbed")
```

**Roadmap:** §9.1 Этап 6, пункт 4  
**Tests:** `tests/analytics/test_absorption.py` (5 tests)

---

### 11. Walls (`walls.py`)

**Описание:** Детектор крупных bid/ask walls в orderbook.

**Usage:**
```python
from packages.analytics.walls import WallDetector

detector = WallDetector(min_qty_ratio=3.0)
for book_event in book_events:
    detector.process(book_event)

for wall in detector.get_active_walls():
    print(f"Wall: {wall.side} @ {wall.price_ticks}, qty: {wall.current_qty}")
```

**Roadmap:** §9.1 Этап 6, пункт 5  
**Tests:** `tests/analytics/test_walls.py` (7 tests)

---

### 12. Pulling/Stacking (`pulling_stacking.py`)

**Описание:** Детектор манипуляций orderbook: pulling (быстрое удаление) и stacking (резкое добавление).

**Usage:**
```python
from packages.analytics.pulling_stacking import PullingStackingDetector

detector = PullingStackingDetector(pulling_window_ms=500, stacking_threshold=2.0)
for book_event in book_events:
    event = detector.process(book_event)
    if event:
        print(f"{event.event_type} at {event.price_ticks}")
```

**Roadmap:** §9.1 Этап 6, пункт 6  
**Tests:** `tests/analytics/test_pulling_stacking.py` (3 tests)

---

### 13. Liquidation Cascades (`liquidation_cascades.py`)

**Описание:** Детектор каскадных ликвидаций (серия крупных сделок в одном направлении).

**Usage:**
```python
from packages.analytics.liquidation_cascades import LiquidationCascadeDetector

detector = LiquidationCascadeDetector(min_trade_qty=5000, window_ms=3000, min_cascade_count=3)
for trade in trades:
    event = detector.process(trade)
    if event:
        print(f"Cascade: {event['direction']}, {event['count']} liquidations")

for event in detector.flush():
    print(f"Cascade: {event}")
```

**Roadmap:** §9.1 Этап 6, пункт 7  
**Tests:** `tests/analytics/test_liquidation_cascades.py` (5 tests)

---

### 14. Heatmap (`heatmap.py`)

**Описание:** Orderbook heatmap с tile aggregation для visualization.

**Usage:**
```python
from packages.analytics.heatmap import HeatmapAggregator

aggregator = HeatmapAggregator(
    venue="BYBIT",
    symbol="BTCUSDT",
    time_interval_ms=60000,  # 1 minute
    price_bin_size_ticks=10,  # 1.0 USDT
)

for book_event in book_events:
    aggregator.add_snapshot(book_event)

tiles = aggregator.build()
for tile in tiles:
    print(f"Tile: time={tile.interval_start_ms}, price={tile.price_bin_start_ticks}, "
          f"bid_vol={tile.bid_volume_sum}, ask_vol={tile.ask_volume_sum}")
```

**API:** `GET /api/v1/analytics/heatmap`  
**Roadmap:** §9.2 Этап 6  
**Tests:** `tests/analytics/test_heatmap.py` (11 tests)

---

### 15. Regime Detector (`regime.py`)

**Описание:** Классификатор market regime на основе всех orderflow features.

**Usage:**
```python
from packages.analytics.regime import RegimeDetector

detector = RegimeDetector(symbol="BTCUSDT", window_ms=300000)

# Add features from other detectors
detector.add_feature("obi", active=True, value=0.65, confidence=0.8)
detector.add_feature("walls_bid", active=True, value=50000, confidence=0.9)

# Compute regime
state = detector.compute_regime()
print(f"Regime: {state.regime}, confidence: {state.regime_confidence}")

# Get feature importance
analysis = detector.analyze()
for fi in analysis.feature_importance:
    print(f"{fi.name}: importance={fi.importance:.2f}, contribution={fi.contribution:.2f}")
```

**API:**
- `GET /api/v1/analytics/orderflow/regime`
- `GET /api/v1/analytics/orderflow/features`

**Roadmap:** §9.1 Этап 6  
**Tests:** `tests/analytics/test_regime.py` (12 tests)

**Regime types:**
- `MARKUP` — восходящий тренд, buying pressure
- `MARKDOWN` — нисходящий тренд, selling pressure
- `ACCUMULATION` — низкая волатильность, balanced orderflow
- `DISTRIBUTION` — высокая волатильность, imbalanced orderflow
- `NEUTRAL` — нет выраженного режима
- `UNKNOWN` — недостаточно данных

---

## Дополнительные модули

### 16. OHLCV Aggregation (`aggregation.py` в api/)

**Описание:** Canonical OHLCV candles из RawTrade.

**API:** `GET /api/v1/ohlc`

---

## Testing

Все модули покрыты тестами:

```bash
# Запустить все analytics tests
pytest tests/analytics/ -v

# Запустить конкретный модуль
pytest tests/analytics/test_sweep.py -v

# С coverage
pytest tests/analytics/ --cov=packages/analytics
```

**Markers:**
- `@pytest.mark.analytics` — все analytics tests
- `@pytest.mark.property` — property-based tests (Hypothesis)
- `@pytest.mark.integration` — integration tests

---

## Roadmap Compliance

| Этап | Статус | Модули |
|------|--------|--------|
| Этап 5 (Trade-derived) | ✅ 100% | Delta, CVD, VWAP, Volume Profile, Footprint, Sweep, Tape |
| Этап 6 (Book-derived) | ✅ 100% | OBI, OFI, Absorption, Walls, Pulling/Stacking, Liquidation, Heatmap, Regime |

**Gaps:**
- Orderbook feeds не подключены (только publicTrade) — требует P1-S3-002
- Deterministic cache/revision не реализован (§9.6)
- Historical regime tracking не реализован

---

## Contributing

При добавлении нового analytics модуля:

1. **Contract:** Создать Pydantic schema в `contracts/`
2. **Implementation:** Добавить detector/calculator в `packages/analytics/`
3. **Tests:** Минимум 5 tests covering edge cases
4. **API:** Добавить endpoint в `packages/api/app.py`
5. **Documentation:** Обновить этот README

**Template:**
```python
class MyDetector:
    """One-line description (Roadmap §X.Y)."""
    
    def __init__(self, ...):
        """Initialize detector."""
        pass
    
    def process(self, event) -> Event | None:
        """Process single event — return result if ready."""
        pass
    
    def flush(self) -> list[Event]:
        """Flush pending state (для chunk boundaries)."""
        pass
```

---

## Performance Notes

- **Chunk-boundary independence:** Все детекторы сохраняют state между вызовами `process()` для корректной работы на streaming data
- **Memory:** Detectors ограничивают history window (например, `window_ms`)
- **CPU:** O(1) для большинства `process()` calls

---

## References

- Roadmap: `BYBIT_MULTIPROCESS_PLATFORM_ROADMAP.md` §9
- Tests: `tests/analytics/`
- API: `packages/api/app.py`
- Contracts: `contracts/`
