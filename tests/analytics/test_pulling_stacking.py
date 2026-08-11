"""
Тесты для Pulling/Stacking detector (Roadmap §9.1 Этап 6, пункт 6).
"""

import pytest
from contracts.schemas import BookCheckpoint, RawBookLevel
from packages.analytics.pulling_stacking import PullingStackingDetector

pytestmark = pytest.mark.contract


def make_book(ts_ms, bids, asks):
    return BookCheckpoint(
        venue="BYBIT", category="linear", symbol="BTCUSDT",
        depth=200, connection_epoch="test",
        update_id=ts_ms, sequence=ts_ms,
        exchange_timestamp_ms=ts_ms, outer_timestamp_ms=ts_ms, receive_timestamp_ms=ts_ms,
        bids=[RawBookLevel(priceTicks=p, qtySteps=q) for p, q in bids],
        asks=[RawBookLevel(priceTicks=p, qtySteps=q) for p, q in asks],
        level_count=len(bids)+len(asks), coverage_boundary_ticks=0,
        coverage_bps="0.0000", is_feed_range_complete=True,
    )


class TestPullingStackingDetector:
    def test_pulling_detected_on_fast_disappear(self):
        """Wall исчез быстрее min_pull_ms → pulling."""
        d = PullingStackingDetector(min_wall_qty=5000, min_pull_ms=3000)
        d.process(make_book(1000, [(64000, 8000)], []))
        result = d.process(make_book(1500, [], []))  # 500ms позже → pulling
        assert len(result["pulls"]) == 1
        assert result["pulls"][0]["type"] == "pull"
        assert result["pulls"][0]["lifetime_ms"] == 500

    def test_no_pulling_on_slow_disappear(self):
        """Wall исчез медленно → не pulling."""
        d = PullingStackingDetector(min_wall_qty=5000, min_pull_ms=3000)
        d.process(make_book(1000, [(64000, 8000)], []))
        result = d.process(make_book(5000, [], []))  # 4000ms → не pulling
        assert len(result["pulls"]) == 0

    def test_stacking_detected_on_qty_surge(self):
        """Qty вырос в 2x → stacking."""
        d = PullingStackingDetector(min_wall_qty=5000, stack_ratio=1.5)
        d.process(make_book(1000, [], [(64010, 6000)]))
        result = d.process(make_book(2000, [], [(64010, 13000)]))
        assert len(result["stacks"]) == 1
        assert result["stacks"][0]["type"] == "stack"
        assert result["stacks"][0]["ratio"] > 1.5

    def test_normal_fluctuation_not_stacking(self):
        """Небольшой рост qty → не stacking."""
        d = PullingStackingDetector(min_wall_qty=5000, stack_ratio=1.5)
        d.process(make_book(1000, [], [(64010, 6000)]))
        result = d.process(make_book(2000, [], [(64010, 7000)]))
        assert len(result["stacks"]) == 0

    def test_history_accumulated(self):
        """Pulls и stacks накапливаются в истории."""
        d = PullingStackingDetector(min_wall_qty=5000, min_pull_ms=3000)
        d.process(make_book(1000, [(64000, 8000)], []))
        d.process(make_book(1500, [], []))
        d.process(make_book(2000, [(64000, 8000)], []))
        d.process(make_book(2500, [], []))
        assert len(d.pulls) == 2
