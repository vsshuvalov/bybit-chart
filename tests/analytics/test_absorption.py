"""
Тесты для Absorption detector (Roadmap §9.1 Этап 6, пункт 4).
"""

import pytest
from contracts.schemas import BookCheckpoint, RawBookLevel, RawTrade, TakerSide
from packages.analytics.absorption import AbsorptionDetector

pytestmark = pytest.mark.contract


def make_trade(trade_id: str, side: TakerSide, price_ticks: int, qty_steps: int, ts_ms: int) -> RawTrade:
    return RawTrade(
        symbol="BTCUSDT", tradeId=trade_id, sequence=int(trade_id),
        exchangeTimestampMs=ts_ms, outerTimestampMs=ts_ms, receiveTimestampMs=ts_ms + 10,
        priceTicks=price_ticks, qtySteps=qty_steps, takerSide=side,
    )


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


class TestAbsorptionDetector:
    def test_absorption_detected(self):
        """Уровень bid поглощает buy trades и остаётся стабильным."""
        d = AbsorptionDetector(min_absorbed_qty=500, window_ms=2000)

        b1 = make_book(1000, [(64000, 2000)], [(64010, 1000)])
        d.on_book(b1)

        # Агрессивные покупки (taker BUY) поглощаются ASK
        d.on_trade(make_trade("1", TakerSide.BUY, 64010, 600, 1500))

        # Ask уровень 64010 не уменьшился → absorption
        b2 = make_book(2000, [(64000, 2000)], [(64010, 1100)])
        events = d.on_book(b2)

        assert len(events) == 1
        assert events[0].side == "Ask"
        assert events[0].price_ticks == 64010
        assert events[0].absorbed_qty_steps == 600

    def test_no_absorption_level_depleted(self):
        """Уровень уменьшился → не absorption."""
        d = AbsorptionDetector(min_absorbed_qty=500, window_ms=2000, min_replenishment_ratio=0.7)

        d.on_book(make_book(1000, [(64000, 2000)], [(64010, 1000)]))
        d.on_trade(make_trade("1", TakerSide.BUY, 64010, 600, 1500))

        # Ask уровень упал с 1000 до 200 (depleted)
        events = d.on_book(make_book(2000, [(64000, 2000)], [(64010, 200)]))
        assert len(events) == 0

    def test_replenishment_ratio(self):
        """replenishment_ratio отражает восполнение уровня."""
        from contracts.absorption import AbsorptionEvent
        e = AbsorptionEvent(
            timestamp_ms=1000, symbol="BTCUSDT", price_ticks=64000,
            side="Bid", absorbed_qty_steps=1000, duration_ms=500,
            trade_count=5, level_qty_before=1000, level_qty_after=900,
        )
        assert e.replenishment_ratio == pytest.approx(0.9)

    def test_below_min_qty_ignored(self):
        """Маленькие объёмы не триггерят absorption."""
        d = AbsorptionDetector(min_absorbed_qty=1000, window_ms=2000)
        d.on_book(make_book(1000, [(64000, 2000)], [(64010, 500)]))
        d.on_trade(make_trade("1", TakerSide.BUY, 64010, 100, 1500))
        events = d.on_book(make_book(2000, [(64000, 2000)], [(64010, 600)]))
        assert len(events) == 0

    def test_expired_trades_cleared(self):
        """Trades за пределами window_ms игнорируются."""
        d = AbsorptionDetector(min_absorbed_qty=500, window_ms=500)
        d.on_book(make_book(1000, [], [(64010, 1000)]))
        d.on_trade(make_trade("1", TakerSide.BUY, 64010, 600, 1200))
        # window = 500ms → trade в 1200ms истёк к 2000ms
        events = d.on_book(make_book(2000, [], [(64010, 1000)]))
        assert len(events) == 0
