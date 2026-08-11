"""
Property-based tests для Heatmap aggregation.

Использует Hypothesis для генерации arbitrary inputs и проверки invariants.
"""

import pytest
from hypothesis import given, strategies as st
from decimal import Decimal

from contracts.schemas import RawBookEvent, RawBookLevel
from packages.analytics.heatmap import HeatmapAggregator, compute_heatmap


pytestmark = [pytest.mark.analytics, pytest.mark.property]


def make_book_event(timestamp_ms, bids, asks):
    """Helper для создания RawBookEvent."""
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


@given(
    timestamps=st.lists(
        st.integers(min_value=0, max_value=1000000000),
        min_size=1,
        max_size=50,
    )
)
def test_heatmap_deterministic_for_same_inputs(timestamps):
    """Одинаковые входные данные → одинаковые tiles."""
    aggregator1 = HeatmapAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        time_interval_ms=60000,
        price_bin_size_ticks=10,
    )

    aggregator2 = HeatmapAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        time_interval_ms=60000,
        price_bin_size_ticks=10,
    )

    # Добавить одинаковые snapshots в оба aggregator
    for ts in timestamps:
        event = make_book_event(
            timestamp_ms=ts,
            bids=[(500000, 1000)],
            asks=[(500010, 2000)],
        )
        aggregator1.add_snapshot(event)
        aggregator2.add_snapshot(event)

    tiles1 = aggregator1.build()
    tiles2 = aggregator2.build()

    # Должны быть идентичны
    assert len(tiles1) == len(tiles2)
    for t1, t2 in zip(tiles1, tiles2):
        assert t1 == t2


@given(
    timestamps=st.lists(
        st.integers(min_value=0, max_value=1000000000),
        min_size=2,
        max_size=20,
    )
)
def test_heatmap_order_independence(timestamps):
    """Порядок snapshots не влияет на tiles (коммутативность)."""
    import random

    shuffled = timestamps.copy()
    random.shuffle(shuffled)

    aggregator1 = HeatmapAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        time_interval_ms=60000,
        price_bin_size_ticks=10,
    )

    aggregator2 = HeatmapAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        time_interval_ms=60000,
        price_bin_size_ticks=10,
    )

    # Original order
    for ts in timestamps:
        event = make_book_event(ts, [(500000, 1000)], [(500010, 2000)])
        aggregator1.add_snapshot(event)

    # Shuffled order
    for ts in shuffled:
        event = make_book_event(ts, [(500000, 1000)], [(500010, 2000)])
        aggregator2.add_snapshot(event)

    tiles1 = aggregator1.build()
    tiles2 = aggregator2.build()

    # Tiles должны быть одинаковыми (порядок не важен для aggregation)
    assert len(tiles1) == len(tiles2)

    # Сортировать для сравнения
    tiles1_sorted = sorted(tiles1, key=lambda t: (t.interval_start_ms, t.price_bin_start_ticks))
    tiles2_sorted = sorted(tiles2, key=lambda t: (t.interval_start_ms, t.price_bin_start_ticks))

    for t1, t2 in zip(tiles1_sorted, tiles2_sorted):
        assert t1 == t2


@given(
    bid_qty=st.integers(min_value=0, max_value=100000),
    ask_qty=st.integers(min_value=0, max_value=100000),
)
def test_heatmap_volume_sum_correct(bid_qty, ask_qty):
    """Sum volumes корректно агрегируются."""
    aggregator = HeatmapAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        time_interval_ms=60000,
        price_bin_size_ticks=10,
    )

    # Один snapshot с заданными volumes
    event = make_book_event(
        timestamp_ms=100000,
        bids=[(500000, bid_qty)] if bid_qty > 0 else [],
        asks=[(500010, ask_qty)] if ask_qty > 0 else [],
    )

    aggregator.add_snapshot(event)
    tiles = aggregator.build()

    if bid_qty == 0 and ask_qty == 0:
        assert len(tiles) == 0
    else:
        # Найти tiles для наших levels
        bid_tile = next((t for t in tiles if t.price_bin_start_ticks == 500000), None)
        ask_tile = next((t for t in tiles if t.price_bin_start_ticks == 500010), None)

        if bid_qty > 0:
            assert bid_tile is not None
            assert bid_tile.bid_volume_sum == bid_qty

        if ask_qty > 0:
            assert ask_tile is not None
            assert ask_tile.ask_volume_sum == ask_qty


@given(
    price_bin_size=st.integers(min_value=1, max_value=100),
    time_interval_ms=st.integers(min_value=1000, max_value=300000),
)
def test_heatmap_arbitrary_bin_sizes(price_bin_size, time_interval_ms):
    """Arbitrary bin sizes работают корректно."""
    aggregator = HeatmapAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        time_interval_ms=time_interval_ms,
        price_bin_size_ticks=price_bin_size,
    )

    event = make_book_event(100000, [(500000, 1000)], [])
    aggregator.add_snapshot(event)
    tiles = aggregator.build()

    assert len(tiles) >= 0

    for tile in tiles:
        # Проверить, что bin boundaries выровнены
        assert tile.price_bin_start_ticks % price_bin_size == 0
        assert tile.interval_start_ms % time_interval_ms == 0

        # Проверить размер bins
        assert tile.price_bin_end_ticks == tile.price_bin_start_ticks + price_bin_size
        assert tile.interval_end_ms == tile.interval_start_ms + time_interval_ms


@given(
    snapshot_count=st.integers(min_value=1, max_value=10),
)
def test_heatmap_snapshot_count_tracked(snapshot_count):
    """snapshot_count корректно отслеживается."""
    aggregator = HeatmapAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        time_interval_ms=60000,
        price_bin_size_ticks=10,
    )

    # Добавить N snapshots в один time/price bin
    for i in range(snapshot_count):
        event = make_book_event(
            timestamp_ms=100000 + i * 100,  # Same time bin
            bids=[(500000, 1000)],  # Same price bin
            asks=[],
        )
        aggregator.add_snapshot(event)

    tiles = aggregator.build()

    assert len(tiles) >= 1
    tile = tiles[0]

    # snapshot_count должен быть >= snapshot_count (может быть больше если несколько levels)
    assert tile.snapshot_count >= snapshot_count


@given(
    max_values=st.lists(
        st.integers(min_value=1, max_value=10000),
        min_size=1,
        max_size=10,
    )
)
def test_heatmap_max_volume_correct(max_values):
    """Max volume корректно отслеживается."""
    aggregator = HeatmapAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        time_interval_ms=60000,
        price_bin_size_ticks=10,
    )

    # Добавить snapshots с разными volumes
    for i, qty in enumerate(max_values):
        event = make_book_event(
            timestamp_ms=100000 + i * 100,
            bids=[(500000, qty)],
            asks=[],
        )
        aggregator.add_snapshot(event)

    tiles = aggregator.build()
    tile = tiles[0]

    # Max должен быть равен максимальному значению
    assert tile.bid_volume_max == max(max_values)
