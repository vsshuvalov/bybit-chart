"""
Тесты для Tape/Bubbles analytics module (Roadmap §9.1 Этап 5).
"""

import pytest
from contracts.schemas import RawTrade, TakerSide
from contracts.tape import TradeSizeCategory
from packages.analytics.tape import BubbleAggregator, TapeFilter

pytestmark = pytest.mark.contract


def make_trade(trade_id: str, side: TakerSide, price_ticks: int, qty_steps: int, ts_ms: int) -> RawTrade:
    return RawTrade(
        symbol="BTCUSDT", tradeId=trade_id, sequence=int(trade_id),
        exchangeTimestampMs=ts_ms, outerTimestampMs=ts_ms, receiveTimestampMs=ts_ms + 10,
        priceTicks=price_ticks, qtySteps=qty_steps, takerSide=side,
    )


class TestTapeFilter:
    def test_small_trade_filtered_out(self):
        tape = TapeFilter(min_qty_steps=1000)
        entry = tape.process(make_trade("1", TakerSide.BUY, 64000, 100, 1000))
        assert entry is None

    def test_large_trade_passes(self):
        tape = TapeFilter(min_qty_steps=1000)
        entry = tape.process(make_trade("1", TakerSide.BUY, 64000, 2000, 1000))
        assert entry is not None
        assert entry.qty_steps == 2000
        assert entry.taker_side == "Buy"

    def test_size_categories(self):
        tape = TapeFilter(
            min_qty_steps=0,
            whale_threshold=10000,
            large_threshold=5000,
            medium_threshold=1000,
        )
        assert tape.process(make_trade("1", TakerSide.BUY, 64000, 500, 1000)).size_category == TradeSizeCategory.SMALL
        assert tape.process(make_trade("2", TakerSide.BUY, 64000, 2000, 1001)).size_category == TradeSizeCategory.MEDIUM
        assert tape.process(make_trade("3", TakerSide.BUY, 64000, 6000, 1002)).size_category == TradeSizeCategory.LARGE
        assert tape.process(make_trade("4", TakerSide.BUY, 64000, 15000, 1003)).size_category == TradeSizeCategory.WHALE

    def test_get_entries_time_filter(self):
        tape = TapeFilter(min_qty_steps=0)
        tape.process(make_trade("1", TakerSide.BUY, 64000, 1000, 1000))
        tape.process(make_trade("2", TakerSide.BUY, 64000, 1000, 2000))
        tape.process(make_trade("3", TakerSide.BUY, 64000, 1000, 3000))

        entries = tape.get_entries(start_ms=1500, end_ms=2500)
        assert len(entries) == 1
        assert entries[0].trade_id == "2"

    def test_block_trade_flagged(self):
        tape = TapeFilter(min_qty_steps=0)
        trade = RawTrade(
            symbol="BTCUSDT", tradeId="1", sequence=1,
            exchangeTimestampMs=1000, outerTimestampMs=1000, receiveTimestampMs=1010,
            priceTicks=64000, qtySteps=5000, takerSide=TakerSide.BUY,
            isBlockTrade=True,
        )
        entry = tape.process(trade)
        assert entry.is_block_trade is True


class TestBubbleAggregator:
    def test_same_price_same_window_merged(self):
        agg = BubbleAggregator(cluster_window_ms=1000)
        agg.add_trade(make_trade("1", TakerSide.BUY, 64000, 1000, 100))
        agg.add_trade(make_trade("2", TakerSide.BUY, 64000, 2000, 500))

        bubbles = agg.flush("BTCUSDT")
        assert len(bubbles) == 1
        assert bubbles[0].total_qty_steps == 3000
        assert bubbles[0].buy_qty_steps == 3000
        assert bubbles[0].trade_count == 2

    def test_different_price_separate_bubbles(self):
        agg = BubbleAggregator(cluster_window_ms=1000)
        agg.add_trade(make_trade("1", TakerSide.BUY, 64000, 1000, 100))
        agg.add_trade(make_trade("2", TakerSide.SELL, 64010, 1000, 200))

        bubbles = agg.flush("BTCUSDT")
        assert len(bubbles) == 2

    def test_window_expired_creates_new_cluster(self):
        agg = BubbleAggregator(cluster_window_ms=500)
        agg.add_trade(make_trade("1", TakerSide.BUY, 64000, 1000, 100))
        completed = agg.add_trade(make_trade("2", TakerSide.BUY, 64000, 2000, 700))

        assert completed is not None
        assert completed.total_qty_steps == 1000  # первый кластер закрыт

        remaining = agg.flush("BTCUSDT")
        assert len(remaining) == 1
        assert remaining[0].total_qty_steps == 2000  # второй кластер

    def test_dominant_side_buy(self):
        agg = BubbleAggregator(cluster_window_ms=1000)
        agg.add_trade(make_trade("1", TakerSide.BUY, 64000, 9000, 100))
        agg.add_trade(make_trade("2", TakerSide.SELL, 64000, 1000, 200))
        bubbles = agg.flush("BTCUSDT")
        assert bubbles[0].dominant_side == "Buy"

    def test_dominant_side_neutral(self):
        agg = BubbleAggregator(cluster_window_ms=1000)
        agg.add_trade(make_trade("1", TakerSide.BUY, 64000, 5000, 100))
        agg.add_trade(make_trade("2", TakerSide.SELL, 64000, 5000, 200))
        bubbles = agg.flush("BTCUSDT")
        assert bubbles[0].dominant_side == "Neutral"

    def test_get_bubbles_filter_by_category(self):
        agg = BubbleAggregator(cluster_window_ms=500, large_threshold=5000)
        agg.add_trade(make_trade("1", TakerSide.BUY, 64000, 1000, 100))
        agg.add_trade(make_trade("2", TakerSide.BUY, 64010, 8000, 200))
        agg.flush("BTCUSDT")

        large_only = agg.get_bubbles(min_category=TradeSizeCategory.LARGE)
        assert all(b.size_category in (TradeSizeCategory.LARGE, TradeSizeCategory.WHALE) for b in large_only)
