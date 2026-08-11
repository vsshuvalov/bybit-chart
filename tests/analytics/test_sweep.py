"""
Тесты для Sweep detector (Roadmap §9.1 Этап 5, пункт 7).
"""

import pytest
from contracts.schemas import RawTrade, TakerSide
from packages.analytics.sweep import SweepDetector

pytestmark = pytest.mark.contract


def make_trade(trade_id: str, side: TakerSide, price_ticks: int, qty_steps: int, ts_ms: int) -> RawTrade:
    return RawTrade(
        symbol="BTCUSDT", tradeId=trade_id, sequence=int(trade_id),
        exchangeTimestampMs=ts_ms, outerTimestampMs=ts_ms, receiveTimestampMs=ts_ms + 10,
        priceTicks=price_ticks, qtySteps=qty_steps, takerSide=side,
    )


class TestSweepDetector:
    def test_sweep_detected_on_direction_change(self):
        """3+ уровня в одном направлении → sweep при смене направления."""
        d = SweepDetector(min_levels=3, window_ms=500)
        d.process(make_trade("1", TakerSide.BUY, 64000, 100, 100))
        d.process(make_trade("2", TakerSide.BUY, 64010, 100, 200))
        d.process(make_trade("3", TakerSide.BUY, 64020, 100, 300))
        event = d.process(make_trade("4", TakerSide.SELL, 64000, 100, 400))

        assert event is not None
        assert event.direction == "Buy"
        assert event.levels_swept == 3

    def test_no_sweep_below_min_levels(self):
        """2 уровня — не sweep (min_levels=3)."""
        d = SweepDetector(min_levels=3, window_ms=500)
        d.process(make_trade("1", TakerSide.BUY, 64000, 100, 100))
        d.process(make_trade("2", TakerSide.BUY, 64010, 100, 200))
        event = d.process(make_trade("3", TakerSide.SELL, 64000, 100, 300))

        assert event is None

    def test_sweep_on_window_expiry(self):
        """Таймаут окна закрывает chain."""
        d = SweepDetector(min_levels=3, window_ms=200)
        d.process(make_trade("1", TakerSide.BUY, 64000, 100, 100))
        d.process(make_trade("2", TakerSide.BUY, 64010, 100, 200))
        d.process(make_trade("3", TakerSide.BUY, 64020, 100, 300))
        # 500ms пауза — окно expired
        event = d.process(make_trade("4", TakerSide.BUY, 64030, 100, 800))

        assert event is not None
        assert event.levels_swept == 3

    def test_flush_closes_open_chain(self):
        """flush() закрывает незакрытую chain."""
        d = SweepDetector(min_levels=3, window_ms=500)
        d.process(make_trade("1", TakerSide.SELL, 64000, 100, 100))
        d.process(make_trade("2", TakerSide.SELL, 63990, 100, 200))
        d.process(make_trade("3", TakerSide.SELL, 63980, 100, 300))

        events = d.flush()
        assert len(events) == 1
        assert events[0].direction == "Sell"

    def test_price_move_calculated(self):
        """price_move_ticks = |end - start|."""
        d = SweepDetector(min_levels=3, window_ms=500)
        d.process(make_trade("1", TakerSide.BUY, 64000, 100, 100))
        d.process(make_trade("2", TakerSide.BUY, 64010, 100, 200))
        d.process(make_trade("3", TakerSide.BUY, 64030, 100, 300))
        events = d.flush()

        assert events[0].price_move_ticks == 30

    def test_same_price_level_not_double_counted(self):
        """Повторная цена не увеличивает levels_swept."""
        d = SweepDetector(min_levels=3, window_ms=500)
        d.process(make_trade("1", TakerSide.BUY, 64000, 100, 100))
        d.process(make_trade("2", TakerSide.BUY, 64000, 100, 150))  # та же цена
        d.process(make_trade("3", TakerSide.BUY, 64010, 100, 200))
        d.process(make_trade("4", TakerSide.BUY, 64020, 100, 300))
        events = d.flush()

        assert events[0].levels_swept == 3   # не 4

    def test_chunk_boundary_independence(self):
        """Chain переносится между вызовами process() — нет зависимости от batch."""
        d = SweepDetector(min_levels=3, window_ms=1000)
        # Batch 1
        for t in [
            make_trade("1", TakerSide.BUY, 64000, 100, 100),
            make_trade("2", TakerSide.BUY, 64010, 100, 200),
        ]:
            d.process(t)
        # Batch 2 — chain продолжается
        for t in [
            make_trade("3", TakerSide.BUY, 64020, 100, 300),
        ]:
            d.process(t)

        events = d.flush()
        assert len(events) == 1
        assert events[0].levels_swept == 3
        assert events[0].trade_count == 3

    def test_get_events_filter(self):
        """Фильтрация событий по времени и направлению."""
        d = SweepDetector(min_levels=3, window_ms=200)
        for t in [
            make_trade("1", TakerSide.BUY, 64000, 100, 100),
            make_trade("2", TakerSide.BUY, 64010, 100, 150),
            make_trade("3", TakerSide.BUY, 64020, 100, 200),
            make_trade("4", TakerSide.SELL, 63990, 100, 600),  # gap → closes BUY chain
            make_trade("5", TakerSide.SELL, 63980, 100, 650),
            make_trade("6", TakerSide.SELL, 63970, 100, 700),
        ]:
            d.process(t)
        d.flush()

        buy_events = d.get_events(direction="Buy")
        sell_events = d.get_events(direction="Sell")
        assert len(buy_events) == 1
        assert len(sell_events) == 1
