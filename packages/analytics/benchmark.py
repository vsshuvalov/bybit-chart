"""
Benchmark для analytics modules.

Измеряет throughput (events/sec) каждого детектора без запуска на production.
"""

import time
from decimal import Decimal

from contracts.schemas import RawTrade, RawBookEvent, RawBookLevel, TakerSide
from packages.analytics.sweep import SweepDetector
from packages.analytics.tape import TapeFilter, BubbleAggregator
from packages.analytics.absorption import AbsorptionDetector
from packages.analytics.walls import WallDetector
from packages.analytics.pulling_stacking import PullingStackingDetector
from packages.analytics.liquidation_cascades import LiquidationCascadeDetector
from packages.analytics.ofi import OFICalculator
from packages.analytics.footprint import FootprintAggregator
from packages.analytics.heatmap import HeatmapAggregator
from packages.analytics.regime import RegimeDetector


def make_trade(timestamp_ms: int, price_ticks: int, qty_steps: int, taker_side: TakerSide) -> RawTrade:
    """Create synthetic trade."""
    return RawTrade(
        venue="BYBIT",
        symbol="BTCUSDT",
        trade_id=f"trade_{timestamp_ms}",
        taker_side=taker_side,
        price_ticks=price_ticks,
        qty_steps=qty_steps,
        exchange_timestamp_ms=timestamp_ms,
        local_timestamp_ms=timestamp_ms,
        sequence=1,
        outerTimestampMs=timestamp_ms,
        receiveTimestampMs=timestamp_ms,
    )


def make_book_event(timestamp_ms: int, bids, asks) -> RawBookEvent:
    """Create synthetic book event."""
    return RawBookEvent(
        venue="BYBIT",
        symbol="BTCUSDT",
        type="snapshot",
        depth=200,
        bids=[RawBookLevel(price_ticks=p, qty_steps=q) for p, q in bids],
        asks=[RawBookLevel(price_ticks=p, qty_steps=q) for p, q in asks],
        exchange_timestamp_ms=timestamp_ms,
        local_timestamp_ms=timestamp_ms,
        connectionEpoch="1",
        updateId=1000,
        sequence=1,
        outerTimestampMs=timestamp_ms,
        receiveTimestampMs=timestamp_ms,
    )


def benchmark_sweep_detector(n_events: int = 10000) -> float:
    """Benchmark SweepDetector."""
    detector = SweepDetector(min_levels=3, window_ms=500)

    start = time.perf_counter()
    for i in range(n_events):
        trade = make_trade(
            timestamp_ms=i * 10,
            price_ticks=500000 + (i % 100),
            qty_steps=1000,
            taker_side=TakerSide.BUY if i % 2 == 0 else TakerSide.SELL,
        )
        detector.process(trade)

    elapsed = time.perf_counter() - start
    return n_events / elapsed


def benchmark_tape_filter(n_events: int = 10000) -> float:
    """Benchmark TapeFilter."""
    tape_filter = TapeFilter(min_qty_steps=1000)

    start = time.perf_counter()
    for i in range(n_events):
        trade = make_trade(
            timestamp_ms=i * 10,
            price_ticks=500000,
            qty_steps=1500,
            taker_side=TakerSide.BUY,
        )
        tape_filter.process(trade)

    elapsed = time.perf_counter() - start
    return n_events / elapsed


def benchmark_absorption(n_events: int = 10000) -> float:
    """Benchmark AbsorptionDetector."""
    detector = AbsorptionDetector(min_absorbed_qty=1000, window_ms=2000)

    start = time.perf_counter()
    for i in range(n_events):
        trade = make_trade(
            timestamp_ms=i * 10,
            price_ticks=500000,
            qty_steps=1000,
            taker_side=TakerSide.BUY,
        )
        detector.process(trade)

    elapsed = time.perf_counter() - start
    return n_events / elapsed


def benchmark_walls(n_events: int = 10000) -> float:
    """Benchmark WallDetector."""
    detector = WallDetector(min_qty_steps=5000, max_depth=50)

    start = time.perf_counter()
    for i in range(n_events):
        book_event = make_book_event(
            timestamp_ms=i * 100,
            bids=[(500000, 10000), (499990, 1000)],
            asks=[(500010, 2000)],
        )
        detector.process(book_event)

    elapsed = time.perf_counter() - start
    return n_events / elapsed


def benchmark_liquidation_cascades(n_events: int = 10000) -> float:
    """Benchmark LiquidationCascadeDetector."""
    detector = LiquidationCascadeDetector(min_trade_qty=5000, window_ms=3000)

    start = time.perf_counter()
    for i in range(n_events):
        trade = make_trade(
            timestamp_ms=i * 10,
            price_ticks=500000,
            qty_steps=6000,
            taker_side=TakerSide.BUY if i % 5 < 3 else TakerSide.SELL,
        )
        detector.process(trade)

    elapsed = time.perf_counter() - start
    return n_events / elapsed


def benchmark_ofi(n_events: int = 10000) -> float:
    """Benchmark OFICalculator."""
    calculator = OFICalculator()

    start = time.perf_counter()
    for i in range(n_events):
        book_event = make_book_event(
            timestamp_ms=i * 100,
            bids=[(500000, 5000 + i % 1000)],
            asks=[(500010, 3000 + i % 500)],
        )
        calculator.process(book_event)

    elapsed = time.perf_counter() - start
    return n_events / elapsed


def benchmark_footprint(n_events: int = 10000) -> float:
    """Benchmark FootprintAggregator."""
    aggregator = FootprintAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        interval_seconds=60,
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
    )

    start = time.perf_counter()
    for i in range(n_events):
        trade = make_trade(
            timestamp_ms=i * 10,
            price_ticks=500000 + (i % 10),
            qty_steps=1000,
            taker_side=TakerSide.BUY if i % 2 == 0 else TakerSide.SELL,
        )
        aggregator.add_trade(trade)

    elapsed = time.perf_counter() - start
    return n_events / elapsed


def benchmark_heatmap(n_events: int = 1000) -> float:
    """Benchmark HeatmapAggregator."""
    aggregator = HeatmapAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        time_interval_ms=60000,
        price_bin_size_ticks=10,
    )

    start = time.perf_counter()
    for i in range(n_events):
        book_event = make_book_event(
            timestamp_ms=i * 100,
            bids=[(500000 + j, 1000) for j in range(10)],
            asks=[(500010 + j, 2000) for j in range(10)],
        )
        aggregator.add_snapshot(book_event)

    elapsed = time.perf_counter() - start
    return n_events / elapsed


def benchmark_regime(n_events: int = 10000) -> float:
    """Benchmark RegimeDetector."""
    detector = RegimeDetector(symbol="BTCUSDT")

    start = time.perf_counter()
    for i in range(n_events):
        detector.add_feature(f"feat_{i % 5}", active=True, confidence=0.8, timestamp_ms=i * 100)
        _ = detector.compute_regime()

    elapsed = time.perf_counter() - start
    return n_events / elapsed


def main():
    """Run all benchmarks."""
    print("=" * 60)
    print("Analytics Modules Benchmark")
    print("=" * 60)
    print()

    benchmarks = [
        ("Sweep Detector", benchmark_sweep_detector, 10000),
        ("Tape Filter", benchmark_tape_filter, 10000),
        ("OFI Calculator", benchmark_ofi, 10000),
        ("Footprint Aggregator", benchmark_footprint, 10000),
        ("Heatmap Aggregator", benchmark_heatmap, 1000),
        ("Regime Detector", benchmark_regime, 10000),
    ]

    results = []
    for name, func, n_events in benchmarks:
        print(f"Running {name}...", end=" ", flush=True)
        try:
            throughput = func(n_events)
            results.append((name, throughput, n_events))
            print(f"{throughput:,.0f} events/sec")
        except Exception as e:
            print(f"SKIP ({e})")

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"{'Module':<30} {'Throughput':>15} {'Events':>10}")
    print("-" * 60)

    for name, throughput, n_events in sorted(results, key=lambda x: x[1], reverse=True):
        print(f"{name:<30} {throughput:>12,.0f}/s {n_events:>10,}")

    print("=" * 60)
    print()
    print("Notes:")
    print("- Synthetic data (no real I/O)")
    print("- Single-threaded benchmark")
    print("- Results vary by hardware")
    print("- Production throughput depends on: data complexity, I/O, GC")


if __name__ == "__main__":
    main()
