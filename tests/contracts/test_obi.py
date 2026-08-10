"""
Тесты OBI (Order Book Imbalance) Engine (Roadmap §6).

Проверяют: OBI calculation, level aggregation, extreme detection.
"""

import pytest

from packages.analytics.obi import OBIEngine, OBISnapshot
from packages.analytics.orderbook import OrderBookSnapshot, OrderBookLevel

pytestmark = pytest.mark.contract


def create_test_book(timestamp_us: int, bid_volumes: list[float], ask_volumes: list[float]) -> OrderBookSnapshot:
    """Create test book snapshot."""
    bids = [
        OrderBookLevel(price_ticks=50000 - i, qty_steps=int(vol))
        for i, vol in enumerate(bid_volumes)
    ]
    asks = [
        OrderBookLevel(price_ticks=50001 + i, qty_steps=int(vol))
        for i, vol in enumerate(ask_volumes)
    ]

    return OrderBookSnapshot(
        timestamp_us=timestamp_us,
        bids=bids,
        asks=asks,
        depth=len(bids),
        update_id=1,
    )


class TestOBIEngine:
    """Тесты OBIEngine."""

    def test_engine_initialization(self):
        """OBIEngine инициализируется корректно."""
        engine = OBIEngine(near_levels=5, mid_levels=20, far_levels=50)

        assert engine.near_levels == 5
        assert engine.mid_levels == 20
        assert engine.far_levels == 50
        assert len(engine.snapshots) == 0

    def test_calculate_balanced_obi(self):
        """calculate_obi() для balanced book возвращает ~0."""
        engine = OBIEngine()

        # Balanced book (equal volumes)
        book = create_test_book(
            timestamp_us=1000,
            bid_volumes=[100] * 50,
            ask_volumes=[100] * 50,
        )

        snapshot = engine.calculate_obi(book, symbol="BTCUSDT")

        assert snapshot.overall_obi == pytest.approx(0.0, abs=0.01)
        assert snapshot.near_obi == pytest.approx(0.0, abs=0.01)
        assert snapshot.mid_obi == pytest.approx(0.0, abs=0.01)

    def test_calculate_bullish_obi(self):
        """calculate_obi() для bullish book возвращает positive OBI."""
        engine = OBIEngine()

        # More bids than asks
        book = create_test_book(
            timestamp_us=1000,
            bid_volumes=[200] * 50,  # More bid volume
            ask_volumes=[100] * 50,
        )

        snapshot = engine.calculate_obi(book)

        # OBI = (200-100) / (200+100) = 100/300 = 0.333
        assert snapshot.overall_obi == pytest.approx(0.333, abs=0.01)
        assert snapshot.near_obi > 0
        assert snapshot.mid_obi > 0

    def test_calculate_bearish_obi(self):
        """calculate_obi() для bearish book возвращает negative OBI."""
        engine = OBIEngine()

        # More asks than bids
        book = create_test_book(
            timestamp_us=1000,
            bid_volumes=[100] * 50,
            ask_volumes=[200] * 50,  # More ask volume
        )

        snapshot = engine.calculate_obi(book)

        # OBI = (100-200) / (100+200) = -100/300 = -0.333
        assert snapshot.overall_obi == pytest.approx(-0.333, abs=0.01)
        assert snapshot.near_obi < 0
        assert snapshot.mid_obi < 0

    def test_level_aggregation(self):
        """OBI корректно агрегируется по уровням (near/mid/far)."""
        engine = OBIEngine(near_levels=5, mid_levels=20)

        # Create book with different volumes по уровням
        bid_volumes = [1000] * 5 + [500] * 15 + [100] * 30  # Strong near, weaker far
        ask_volumes = [100] * 5 + [500] * 15 + [1000] * 30  # Weak near, stronger far

        book = create_test_book(1000, bid_volumes, ask_volumes)
        snapshot = engine.calculate_obi(book)

        # Near should be strongly bullish
        assert snapshot.near_obi > 0.8

        # Mid should be balanced
        assert -0.2 < snapshot.mid_obi < 0.2

        # Far should be bearish
        assert snapshot.far_obi < -0.5

    def test_per_level_obi(self):
        """Per-level OBI calculation работает."""
        engine = OBIEngine()

        book = create_test_book(
            timestamp_us=1000,
            bid_volumes=[200, 150, 100],
            ask_volumes=[100, 150, 200],
        )

        snapshot = engine.calculate_obi(book)

        assert snapshot.level_obis is not None
        assert len(snapshot.level_obis) == 3

        # Level 0: bid=200, ask=100 → OBI = (200-100)/(200+100) = 0.333
        assert snapshot.level_obis[0] == pytest.approx(0.333, abs=0.01)

        # Level 1: bid=150, ask=150 → OBI = 0
        assert snapshot.level_obis[1] == pytest.approx(0.0, abs=0.01)

        # Level 2: bid=100, ask=200 → OBI = -0.333
        assert snapshot.level_obis[2] == pytest.approx(-0.333, abs=0.01)

    def test_get_latest(self):
        """get_latest() возвращает последний snapshot."""
        engine = OBIEngine()

        book1 = create_test_book(1000, [100] * 50, [100] * 50)
        book2 = create_test_book(2000, [200] * 50, [100] * 50)

        engine.calculate_obi(book1)
        engine.calculate_obi(book2)

        latest = engine.get_latest()

        assert latest is not None
        assert latest.timestamp_us == 2000

    def test_get_history(self):
        """get_history() возвращает snapshots в range."""
        engine = OBIEngine()

        for i in range(5):
            book = create_test_book(1000 + i * 1000, [100] * 50, [100] * 50)
            engine.calculate_obi(book)

        history = engine.get_history(1500, 3500)

        assert len(history) == 2
        assert history[0].timestamp_us == 2000
        assert history[1].timestamp_us == 3000

    def test_detect_extreme_bullish(self):
        """detect_extreme_imbalance() обнаруживает extreme bullish."""
        engine = OBIEngine()

        # Strong bullish book
        book = create_test_book(
            timestamp_us=1000,
            bid_volumes=[1000] * 50,
            ask_volumes=[100] * 50,
        )

        engine.calculate_obi(book)

        is_extreme, direction = engine.detect_extreme_imbalance(threshold=0.7)

        assert is_extreme is True
        assert direction == "bullish"

    def test_detect_extreme_bearish(self):
        """detect_extreme_imbalance() обнаруживает extreme bearish."""
        engine = OBIEngine()

        # Strong bearish book
        book = create_test_book(
            timestamp_us=1000,
            bid_volumes=[100] * 50,
            ask_volumes=[1000] * 50,
        )

        engine.calculate_obi(book)

        is_extreme, direction = engine.detect_extreme_imbalance(threshold=0.7)

        assert is_extreme is True
        assert direction == "bearish"

    def test_no_extreme_imbalance(self):
        """detect_extreme_imbalance() для balanced book возвращает False."""
        engine = OBIEngine()

        book = create_test_book(1000, [100] * 50, [100] * 50)
        engine.calculate_obi(book)

        is_extreme, direction = engine.detect_extreme_imbalance()

        assert is_extreme is False
        assert direction is None

    def test_to_dict_list(self):
        """to_dict_list() serialization работает."""
        engine = OBIEngine()

        for i in range(3):
            book = create_test_book(1000 + i * 1000, [100] * 50, [100] * 50)
            engine.calculate_obi(book)

        dicts = engine.to_dict_list(1000, 4000)

        assert len(dicts) == 3
        assert all("overall_obi" in d for d in dicts)
        assert all("near_obi" in d for d in dicts)


class TestOBISnapshot:
    """Тесты OBISnapshot."""

    def test_snapshot_to_dict(self):
        """OBISnapshot.to_dict() serialization."""
        snapshot = OBISnapshot(
            timestamp_us=1000,
            symbol="BTCUSDT",
            overall_obi=0.5,
            near_obi=0.7,
            mid_obi=0.3,
            far_obi=0.1,
            total_bid_volume=1000.0,
            total_ask_volume=500.0,
        )

        d = snapshot.to_dict()

        assert d["timestamp_us"] == 1000
        assert d["symbol"] == "BTCUSDT"
        assert d["overall_obi"] == 0.5
        assert d["near_obi"] == 0.7
        assert d["total_bid_volume"] == 1000.0
