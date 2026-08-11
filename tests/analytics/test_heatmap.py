"""
Tests для heatmap analytics module.

Roadmap §9.2 Этап 6 требования:
- Price-binned aggregation
- Time-series tiles
- Bid/ask volume separation
- Snapshot counting
"""

import pytest

from contracts.heatmap import HeatmapTile, HeatmapQueryParams
from contracts.schemas import RawBookEvent, RawBookLevel
from packages.analytics.heatmap import HeatmapAggregator, compute_heatmap


pytestmark = pytest.mark.analytics


def _make_book_event(timestamp_ms, bids=None, asks=None, event_type="snapshot"):
    """Helper для создания RawBookEvent с минимальными required полями."""
    return RawBookEvent(
        venue="BYBIT",
        symbol="BTCUSDT",
        type=event_type,
        depth=200,
        bids=bids or [],
        asks=asks or [],
        exchange_timestamp_ms=timestamp_ms,
        local_timestamp_ms=timestamp_ms,
        connectionEpoch="1",
        updateId=1000,
        sequence=1,
        outerTimestampMs=timestamp_ms,
        receiveTimestampMs=timestamp_ms,
    )


class TestHeatmapAggregator:
    """Tests для HeatmapAggregator."""

    def test_single_snapshot_single_level(self):
        """Один snapshot с одним bid level создаёт один tile."""
        aggregator = HeatmapAggregator(
            venue="BYBIT",
            symbol="BTCUSDT",
            time_interval_ms=60000,  # 1 minute
            price_bin_size_ticks=10,  # 1.0 USDT
        )

        book_event = _make_book_event(
            timestamp_ms=100000,
            bids=[RawBookLevel(price_ticks=500000, qty_steps=1000)],  # 50000.0 USDT
        )

        aggregator.add_snapshot(book_event)
        tiles = aggregator.build()

        assert len(tiles) == 1
        tile = tiles[0]
        assert tile.venue == "BYBIT"
        assert tile.symbol == "BTCUSDT"
        assert tile.interval_start_ms == 60000  # floor(100000 / 60000) * 60000
        assert tile.interval_end_ms == 120000
        assert tile.price_bin_start_ticks == 500000  # floor(500000 / 10) * 10
        assert tile.price_bin_end_ticks == 500010
        assert tile.bid_volume_sum == 1000
        assert tile.ask_volume_sum == 0
        assert tile.snapshot_count == 1
        assert tile.bid_volume_max == 1000
        assert tile.ask_volume_max == 0

    def test_multiple_snapshots_same_bin(self):
        """Несколько snapshots в одном time+price bin суммируются."""
        aggregator = HeatmapAggregator(
            venue="BYBIT",
            symbol="BTCUSDT",
            time_interval_ms=60000,
            price_bin_size_ticks=10,
        )

        # Два snapshot в одном time bin, одном price bin
        for i in range(2):
            book_event = _make_book_event(
                timestamp_ms=100000 + i * 1000,  # Оба в [60000, 120000)
                bids=[RawBookLevel(price_ticks=500005, qty_steps=1000 + i * 100)],
            )
            aggregator.add_snapshot(book_event)

        tiles = aggregator.build()
        assert len(tiles) == 1
        tile = tiles[0]
        assert tile.bid_volume_sum == 1000 + 1100  # sum
        assert tile.snapshot_count == 2
        assert tile.bid_volume_max == 1100  # max

    def test_different_time_bins(self):
        """Snapshots в разных time bins создают разные tiles."""
        aggregator = HeatmapAggregator(
            venue="BYBIT",
            symbol="BTCUSDT",
            time_interval_ms=60000,
            price_bin_size_ticks=10,
        )

        # Snapshot 1: time bin 1
        book_event1 = _make_book_event(
            timestamp_ms=100000,  # bin 1
            bids=[RawBookLevel(price_ticks=500000, qty_steps=1000)],
        )

        # Snapshot 2: time bin 2
        book_event2 = _make_book_event(
            timestamp_ms=200000,  # bin 3
            bids=[RawBookLevel(price_ticks=500000, qty_steps=2000)],
        )

        aggregator.add_snapshot(book_event1)
        aggregator.add_snapshot(book_event2)
        tiles = aggregator.build()

        assert len(tiles) == 2
        assert tiles[0].interval_start_ms == 60000
        assert tiles[0].bid_volume_sum == 1000
        assert tiles[1].interval_start_ms == 180000
        assert tiles[1].bid_volume_sum == 2000

    def test_different_price_bins(self):
        """Snapshots в разных price bins создают разные tiles."""
        aggregator = HeatmapAggregator(
            venue="BYBIT",
            symbol="BTCUSDT",
            time_interval_ms=60000,
            price_bin_size_ticks=10,
        )

        book_event = _make_book_event(
            timestamp_ms=100000,
            bids=[
                RawBookLevel(price_ticks=500000, qty_steps=1000),  # bin 50000
                RawBookLevel(price_ticks=500010, qty_steps=2000),  # bin 50001
            ],
        )

        aggregator.add_snapshot(book_event)
        tiles = aggregator.build()

        assert len(tiles) == 2
        assert tiles[0].price_bin_start_ticks == 500000
        assert tiles[0].bid_volume_sum == 1000
        assert tiles[1].price_bin_start_ticks == 500010
        assert tiles[1].bid_volume_sum == 2000

    def test_bid_ask_separation(self):
        """Bid и ask volume разделены в tiles."""
        aggregator = HeatmapAggregator(
            venue="BYBIT",
            symbol="BTCUSDT",
            time_interval_ms=60000,
            price_bin_size_ticks=10,
        )

        book_event = _make_book_event(
            timestamp_ms=100000,
            bids=[RawBookLevel(price_ticks=500000, qty_steps=1000)],
            asks=[RawBookLevel(price_ticks=500000, qty_steps=2000)],
        )

        aggregator.add_snapshot(book_event)
        tiles = aggregator.build()

        assert len(tiles) == 1
        tile = tiles[0]
        assert tile.bid_volume_sum == 1000
        assert tile.ask_volume_sum == 2000
        assert tile.bid_volume_max == 1000
        assert tile.ask_volume_max == 2000

    def test_delta_events_ignored(self):
        """Delta events игнорируются (только snapshots)."""
        aggregator = HeatmapAggregator(
            venue="BYBIT",
            symbol="BTCUSDT",
            time_interval_ms=60000,
            price_bin_size_ticks=10,
        )

        delta_event = _make_book_event(
            timestamp_ms=100000,
            bids=[RawBookLevel(price_ticks=500000, qty_steps=1000)],
            event_type="delta",
        )

        aggregator.add_snapshot(delta_event)
        tiles = aggregator.build()

        assert len(tiles) == 0

    def test_tiles_sorted(self):
        """Tiles отсортированы по времени, затем по цене."""
        aggregator = HeatmapAggregator(
            venue="BYBIT",
            symbol="BTCUSDT",
            time_interval_ms=60000,
            price_bin_size_ticks=10,
        )

        # Добавляем в обратном порядке
        events = [
            (200000, 500010),  # time 3, price high
            (200000, 500000),  # time 3, price low
            (100000, 500010),  # time 1, price high
            (100000, 500000),  # time 1, price low
        ]

        for ts, price in events:
            book_event = _make_book_event(
                timestamp_ms=ts,
                bids=[RawBookLevel(price_ticks=price, qty_steps=1000)],
            )
            aggregator.add_snapshot(book_event)

        tiles = aggregator.build()
        assert len(tiles) == 4

        # Проверить сортировку: time asc, price asc
        assert tiles[0].interval_start_ms == 60000
        assert tiles[0].price_bin_start_ticks == 500000
        assert tiles[1].interval_start_ms == 60000
        assert tiles[1].price_bin_start_ticks == 500010
        assert tiles[2].interval_start_ms == 180000
        assert tiles[2].price_bin_start_ticks == 500000
        assert tiles[3].interval_start_ms == 180000
        assert tiles[3].price_bin_start_ticks == 500010


def test_compute_heatmap_convenience():
    """Convenience function compute_heatmap() работает."""
    book_events = [
        _make_book_event(
            timestamp_ms=100000,
            bids=[RawBookLevel(price_ticks=500000, qty_steps=1000)],
        ),
    ]

    tiles = compute_heatmap(
        book_events=book_events,
        venue="BYBIT",
        symbol="BTCUSDT",
        time_interval_ms=60000,
        price_bin_size_ticks=10,
    )

    assert len(tiles) == 1
    assert tiles[0].bid_volume_sum == 1000


class TestHeatmapQueryParams:
    """Tests для HeatmapQueryParams validation."""

    def test_valid_params(self):
        """Валидные параметры проходят."""
        params = HeatmapQueryParams(
            start_ms=1000,
            end_ms=2000,
            price_bin_size=10,
            time_interval_ms=60000,
        )
        params.validate_range()  # should not raise

    def test_invalid_range(self):
        """end_ms <= start_ms вызывает ошибку."""
        params = HeatmapQueryParams(
            start_ms=2000,
            end_ms=1000,
            price_bin_size=10,
            time_interval_ms=60000,
        )
        with pytest.raises(ValueError, match="end_ms must be greater than start_ms"):
            params.validate_range()

    def test_defaults(self):
        """Default значения установлены."""
        params = HeatmapQueryParams(start_ms=1000, end_ms=2000)
        assert params.price_bin_size == 10
        assert params.time_interval_ms == 60000
