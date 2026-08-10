"""
Тесты Footprint Chart (Roadmap §9).

Проверяют: FootprintChart, volume distribution, absorption detection.
"""

import pytest

from packages.analytics.footprint import FootprintChart, FootprintCell, create_footprint_from_trades

pytestmark = pytest.mark.contract


class TestFootprintChart:
    """Тесты FootprintChart engine."""

    def test_add_trade_creates_candle(self):
        """add_trade() создаёт новую свечу."""
        footprint = FootprintChart(interval_us=60_000_000)  # 1m

        footprint.add_trade(
            timestamp_us=1000,
            price_ticks=10000,
            qty_steps=100,
            aggressor_side="Buy",
        )

        assert len(footprint.candles) == 1
        assert 0 in footprint.candles

    def test_add_trade_updates_cell(self):
        """add_trade() обновляет cell для price level."""
        footprint = FootprintChart(interval_us=60_000_000)

        footprint.add_trade(1000, 10000, 100, "Buy")
        footprint.add_trade(2000, 10000, 50, "Sell")

        candle = footprint.candles[0]
        cell = candle.cells[10000]

        assert cell.buy_volume == 100
        assert cell.sell_volume == 50
        assert cell.delta == 50
        assert cell.total_volume == 150

    def test_multiple_price_levels(self):
        """Footprint хранит volume на разных price levels."""
        footprint = FootprintChart(interval_us=60_000_000)

        footprint.add_trade(1000, 10000, 100, "Buy")
        footprint.add_trade(2000, 10001, 50, "Sell")
        footprint.add_trade(3000, 10002, 75, "Buy")

        candle = footprint.candles[0]

        assert len(candle.cells) == 3
        assert 10000 in candle.cells
        assert 10001 in candle.cells
        assert 10002 in candle.cells

    def test_ohlc_updates(self):
        """OHLC обновляется корректно."""
        footprint = FootprintChart(interval_us=60_000_000)

        footprint.add_trade(1000, 10000, 100, "Buy")  # open
        footprint.add_trade(2000, 10010, 50, "Buy")   # high
        footprint.add_trade(3000, 9995, 75, "Sell")   # low
        footprint.add_trade(4000, 10005, 25, "Buy")   # close

        candle = footprint.candles[0]

        assert candle.open_ticks == 10000
        assert candle.high_ticks == 10010
        assert candle.low_ticks == 9995
        assert candle.close_ticks == 10005

    def test_get_poc_price(self):
        """get_poc_price() возвращает level с максимальным volume."""
        footprint = FootprintChart(interval_us=60_000_000)

        footprint.add_trade(1000, 10000, 100, "Buy")
        footprint.add_trade(2000, 10001, 500, "Buy")  # POC
        footprint.add_trade(3000, 10002, 50, "Buy")

        candle = footprint.candles[0]
        poc = candle.get_poc_price()

        assert poc == 10001

    def test_get_imbalance_levels(self):
        """get_imbalance_levels() находит уровни с сильным imbalance."""
        footprint = FootprintChart(interval_us=60_000_000)

        # Balanced
        footprint.add_trade(1000, 10000, 100, "Buy")
        footprint.add_trade(2000, 10000, 100, "Sell")

        # Strong buy imbalance
        footprint.add_trade(3000, 10001, 300, "Buy")
        footprint.add_trade(4000, 10001, 100, "Sell")

        # Strong sell imbalance
        footprint.add_trade(5000, 10002, 100, "Buy")
        footprint.add_trade(6000, 10002, 300, "Sell")

        candle = footprint.candles[0]
        imbalance_levels = candle.get_imbalance_levels(threshold=0.5)

        assert len(imbalance_levels) == 2
        # 10001: (300-100)/(400) = 0.5
        # 10002: (100-300)/(400) = -0.5

    def test_footprint_cell_imbalance(self):
        """FootprintCell.get_imbalance() рассчитывает imbalance."""
        cell = FootprintCell(
            price_ticks=10000,
            buy_volume=300,
            sell_volume=100,
            delta=200,
            total_volume=400,
        )

        imbalance = cell.get_imbalance()
        assert imbalance == 0.5  # (300-100)/400

    def test_multiple_candles(self):
        """Footprint создаёт несколько свечей для разных time bins."""
        footprint = FootprintChart(interval_us=60_000_000)

        footprint.add_trade(0, 10000, 100, "Buy")
        footprint.add_trade(60_000_000, 10001, 50, "Sell")
        footprint.add_trade(120_000_000, 10002, 75, "Buy")

        assert len(footprint.candles) == 3

    def test_get_candles_range(self):
        """get_candles_range() возвращает свечи в диапазоне."""
        footprint = FootprintChart(interval_us=60_000_000)

        footprint.add_trade(0, 10000, 100, "Buy")
        footprint.add_trade(60_000_000, 10001, 50, "Sell")
        footprint.add_trade(120_000_000, 10002, 75, "Buy")
        footprint.add_trade(180_000_000, 10003, 25, "Buy")

        candles = footprint.get_candles_range(60_000_000, 180_000_000)

        assert len(candles) == 2
        assert candles[0].timestamp_us == 60_000_000
        assert candles[1].timestamp_us == 120_000_000

    def test_detect_absorption(self):
        """detect_absorption() находит absorption patterns."""
        footprint = FootprintChart(interval_us=60_000_000)

        # Buy absorption (3:1 ratio)
        footprint.add_trade(1000, 10000, 300, "Buy")
        footprint.add_trade(2000, 10000, 100, "Sell")

        # Sell absorption (1:3 ratio)
        footprint.add_trade(3000, 10001, 100, "Buy")
        footprint.add_trade(4000, 10001, 300, "Sell")

        candle = footprint.candles[0]
        absorptions = footprint.detect_absorption(candle, min_volume_ratio=3.0)

        assert len(absorptions) == 2
        assert (10000, "buy_absorption") in absorptions
        assert (10001, "sell_absorption") in absorptions

    def test_create_footprint_from_trades(self):
        """create_footprint_from_trades() создаёт footprint из RawTrade list."""
        trades = [
            {"timestampUs": 1000, "priceTicks": 10000, "qtySteps": 100, "takerSide": "Buy"},
            {"timestampUs": 2000, "priceTicks": 10000, "qtySteps": 50, "takerSide": "Sell"},
            {"timestampUs": 3000, "priceTicks": 10001, "qtySteps": 75, "takerSide": "Buy"},
        ]

        footprint = create_footprint_from_trades(trades, interval_us=60_000_000)

        assert len(footprint.candles) == 1
        candle = footprint.candles[0]
        assert len(candle.cells) == 2

    def test_footprint_to_dict(self):
        """FootprintCandle.to_dict() сериализует в JSON."""
        footprint = FootprintChart(interval_us=60_000_000)

        footprint.add_trade(1000, 10000, 100, "Buy")
        footprint.add_trade(2000, 10001, 50, "Sell")

        candle = footprint.candles[0]
        data = candle.to_dict()

        assert "timestamp_us" in data
        assert "open_ticks" in data
        assert "cells" in data
        assert len(data["cells"]) == 2
        assert data["cells"][0]["price_ticks"] in [10000, 10001]
