"""
Тесты для Walls detector (Roadmap §9.1 Этап 6, пункт 5).
"""

import pytest
from contracts.schemas import BookCheckpoint, RawBookLevel
from contracts.walls import WallStatus
from packages.analytics.walls import WallDetector

pytestmark = pytest.mark.contract


def make_book(ts_ms: int, bids: list, asks: list) -> BookCheckpoint:
    return BookCheckpoint(
        venue="BYBIT", category="linear", symbol="BTCUSDT",
        depth=200, connection_epoch="test",
        update_id=ts_ms, sequence=ts_ms,
        exchange_timestamp_ms=ts_ms, outer_timestamp_ms=ts_ms, receive_timestamp_ms=ts_ms,
        bids=[RawBookLevel(priceTicks=p, qtySteps=q) for p, q in bids],
        asks=[RawBookLevel(priceTicks=p, qtySteps=q) for p, q in asks],
        level_count=len(bids) + len(asks),
        coverage_boundary_ticks=0, coverage_bps="0.0000", is_feed_range_complete=True,
    )


class TestWallDetector:
    def test_wall_detected_on_large_bid(self):
        """Большой bid уровень → wall."""
        d = WallDetector(min_qty_steps=5000)
        changed = d.process(make_book(1000, [(64000, 8000)], [(64010, 100)]))
        active = d.get_active_walls()
        assert len(active) == 1
        assert active[0].side == "Bid"
        assert active[0].price_ticks == 64000

    def test_wall_consumed_when_qty_drops(self):
        """Qty упал ниже порога → CONSUMED."""
        d = WallDetector(min_qty_steps=5000)
        d.process(make_book(1000, [(64000, 8000)], []))
        changed = d.process(make_book(2000, [(64000, 100)], []))
        consumed = [w for w in changed if w.status == WallStatus.CONSUMED]
        assert len(consumed) == 1

    def test_wall_out_of_view_when_disappears(self):
        """Уровень исчез из стакана → OUT_OF_VIEW."""
        d = WallDetector(min_qty_steps=5000)
        d.process(make_book(1000, [(64000, 8000)], []))
        changed = d.process(make_book(2000, [], []))
        oov = [w for w in changed if w.status == WallStatus.OUT_OF_VIEW]
        assert len(oov) == 1

    def test_wall_lifetime_tracked(self):
        """Lifetime wall = last_seen - first_seen."""
        d = WallDetector(min_qty_steps=5000)
        d.process(make_book(1000, [(64000, 8000)], []))
        d.process(make_book(2000, [(64000, 8000)], []))
        d.process(make_book(3500, [(64000, 8000)], []))
        active = d.get_active_walls()
        assert active[0].lifetime_ms == 2500

    def test_peak_qty_tracked(self):
        """peak_qty_steps отражает максимум."""
        d = WallDetector(min_qty_steps=5000)
        d.process(make_book(1000, [(64000, 6000)], []))
        d.process(make_book(2000, [(64000, 9000)], []))
        d.process(make_book(3000, [(64000, 7000)], []))
        active = d.get_active_walls()
        assert active[0].peak_qty_steps == 9000

    def test_small_level_not_a_wall(self):
        """Маленький уровень не является wall."""
        d = WallDetector(min_qty_steps=5000)
        d.process(make_book(1000, [(64000, 1000)], []))
        assert len(d.get_active_walls()) == 0

    def test_history_preserves_consumed_walls(self):
        """История хранит закрытые walls."""
        d = WallDetector(min_qty_steps=5000)
        d.process(make_book(1000, [(64000, 8000)], []))
        d.process(make_book(2000, [], []))   # OUT_OF_VIEW
        assert len(d.get_history()) == 1
