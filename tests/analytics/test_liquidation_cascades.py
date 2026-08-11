"""Тесты для Liquidation cascades (Roadmap §9.1 Этап 6, пункт 7)."""

import pytest
from contracts.schemas import RawTrade, TakerSide
from packages.analytics.liquidation_cascades import LiquidationCascadeDetector

pytestmark = pytest.mark.contract


def make_trade(trade_id, side, price, qty, ts):
    return RawTrade(
        symbol="BTCUSDT", tradeId=trade_id, sequence=int(trade_id),
        exchangeTimestampMs=ts, outerTimestampMs=ts, receiveTimestampMs=ts+10,
        priceTicks=price, qtySteps=qty, takerSide=side,
    )


class TestLiquidationCascadeDetector:
    def test_cascade_detected_on_direction_change(self):
        d = LiquidationCascadeDetector(min_trade_qty=5000, window_ms=2000, min_cascade_count=3)
        d.process(make_trade("1", TakerSide.SELL, 64000, 6000, 100))
        d.process(make_trade("2", TakerSide.SELL, 63990, 7000, 300))
        d.process(make_trade("3", TakerSide.SELL, 63980, 8000, 600))
        event = d.process(make_trade("4", TakerSide.BUY, 64000, 6000, 800))
        assert event is not None
        assert event["direction"] == "Sell"
        assert event["trade_count"] == 3

    def test_no_cascade_below_min_count(self):
        d = LiquidationCascadeDetector(min_trade_qty=5000, window_ms=2000, min_cascade_count=3)
        d.process(make_trade("1", TakerSide.SELL, 64000, 6000, 100))
        d.process(make_trade("2", TakerSide.SELL, 63990, 7000, 300))
        event = d.process(make_trade("3", TakerSide.BUY, 64000, 6000, 500))
        assert event is None

    def test_small_trades_ignored(self):
        d = LiquidationCascadeDetector(min_trade_qty=5000, min_cascade_count=3)
        for i in range(5):
            d.process(make_trade(str(i), TakerSide.SELL, 64000-i*10, 100, i*100))
        events = d.flush()
        assert events is None

    def test_flush_closes_open_cascade(self):
        d = LiquidationCascadeDetector(min_trade_qty=5000, min_cascade_count=3)
        d.process(make_trade("1", TakerSide.BUY, 64000, 6000, 100))
        d.process(make_trade("2", TakerSide.BUY, 64010, 7000, 200))
        d.process(make_trade("3", TakerSide.BUY, 64020, 8000, 300))
        event = d.flush()
        assert event is not None
        assert event["direction"] == "Buy"

    def test_window_timeout_closes_cascade(self):
        d = LiquidationCascadeDetector(min_trade_qty=5000, window_ms=500, min_cascade_count=3)
        d.process(make_trade("1", TakerSide.SELL, 64000, 6000, 100))
        d.process(make_trade("2", TakerSide.SELL, 63990, 7000, 300))
        d.process(make_trade("3", TakerSide.SELL, 63980, 8000, 500))
        # gap 2000ms → window expired
        event = d.process(make_trade("4", TakerSide.SELL, 63970, 9000, 2600))
        assert event is not None
        assert event["trade_count"] == 3
