"""
Тесты VWAP (Volume Weighted Average Price) calculation (Этап 3 / P3-A3).

Проверяют: calculate_vwap(), aggregate_vwap_by_interval(), calculate_cumulative_vwap().
"""

import pytest

from packages.analytics.vwap import (
    calculate_vwap,
    aggregate_vwap_by_interval,
    calculate_cumulative_vwap,
)

pytestmark = pytest.mark.contract


class TestVWAPCalculation:
    """Тесты calculate_vwap() для RawTrade events."""

    def test_calculate_vwap_single_trade(self):
        """Один trade → VWAP = price."""
        events = [
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 10},
        ]

        result = calculate_vwap(events)

        assert result["vwap_ticks"] == 100
        assert result["total_volume_steps"] == 10
        assert result["total_turnover_ticks"] == 1000  # 100 * 10
        assert result["trade_count"] == 1
        assert result["min_price_ticks"] == 100
        assert result["max_price_ticks"] == 100

    def test_calculate_vwap_multiple_trades_same_price(self):
        """Несколько trades с одинаковой ценой → VWAP = price."""
        events = [
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 10},
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 20},
        ]

        result = calculate_vwap(events)

        assert result["vwap_ticks"] == 100
        assert result["total_volume_steps"] == 30
        assert result["trade_count"] == 2

    def test_calculate_vwap_different_prices(self):
        """Разные цены → VWAP взвешен по объёму."""
        events = [
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 10},
            {"eventType": "RawTrade", "priceTicks": 110, "qtySteps": 20},
        ]

        result = calculate_vwap(events)

        # VWAP = (100*10 + 110*20) / (10+20) = 3200 / 30 = 106.67 → 106 (integer division)
        assert result["vwap_ticks"] == 106
        assert result["total_volume_steps"] == 30
        assert result["total_turnover_ticks"] == 3200
        assert result["trade_count"] == 2
        assert result["min_price_ticks"] == 100
        assert result["max_price_ticks"] == 110

    def test_calculate_vwap_weighted_heavily(self):
        """Большой объём на одной цене → VWAP ближе к ней."""
        events = [
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 10},
            {"eventType": "RawTrade", "priceTicks": 200, "qtySteps": 90},
        ]

        result = calculate_vwap(events)

        # VWAP = (100*10 + 200*90) / (10+90) = 19000 / 100 = 190
        assert result["vwap_ticks"] == 190
        assert result["total_volume_steps"] == 100

    def test_calculate_vwap_filters_non_trades(self):
        """Фильтрует BookCheckpoint события."""
        events = [
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 10},
            {"eventType": "BookCheckpoint", "priceTicks": 999, "qtySteps": 999},
            {"eventType": "RawTrade", "priceTicks": 110, "qtySteps": 20},
        ]

        result = calculate_vwap(events)

        assert result["vwap_ticks"] == 106  # только RawTrade
        assert result["trade_count"] == 2

    def test_calculate_vwap_empty_events(self):
        """Пустой список → нулевые значения."""
        result = calculate_vwap([])

        assert result["vwap_ticks"] == 0
        assert result["total_volume_steps"] == 0
        assert result["total_turnover_ticks"] == 0
        assert result["trade_count"] == 0


class TestVWAPAggregation:
    """Тесты aggregate_vwap_by_interval()."""

    def test_aggregate_vwap_single_bar(self):
        """Все события в одном bar."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 1000000, "priceTicks": 100, "qtySteps": 10},
            {"eventType": "RawTrade", "timestampUs": 1500000, "priceTicks": 110, "qtySteps": 20},
        ]

        bars = aggregate_vwap_by_interval(events, interval_us=60_000_000)  # 1m

        assert len(bars) == 1
        bar = bars[0]
        assert bar["timestamp_us"] == 0
        assert bar["vwap_ticks"] == 106
        assert bar["total_volume_steps"] == 30

    def test_aggregate_vwap_multiple_bars(self):
        """События в разных bars."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 0, "priceTicks": 100, "qtySteps": 10},
            {"eventType": "RawTrade", "timestampUs": 60_000_000, "priceTicks": 200, "qtySteps": 20},
        ]

        bars = aggregate_vwap_by_interval(events, interval_us=60_000_000)

        assert len(bars) == 2
        assert bars[0]["vwap_ticks"] == 100
        assert bars[1]["vwap_ticks"] == 200

    def test_aggregate_vwap_bars_sorted(self):
        """Bars отсортированы по timestamp."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 120_000_000, "priceTicks": 300, "qtySteps": 30},
            {"eventType": "RawTrade", "timestampUs": 0, "priceTicks": 100, "qtySteps": 10},
            {"eventType": "RawTrade", "timestampUs": 60_000_000, "priceTicks": 200, "qtySteps": 20},
        ]

        bars = aggregate_vwap_by_interval(events, interval_us=60_000_000)

        assert len(bars) == 3
        assert bars[0]["timestamp_us"] == 0
        assert bars[1]["timestamp_us"] == 60_000_000
        assert bars[2]["timestamp_us"] == 120_000_000

    def test_aggregate_vwap_empty_events(self):
        """Пустой список → пустой результат."""
        bars = aggregate_vwap_by_interval([], interval_us=60_000_000)
        assert bars == []


class TestCumulativeVWAP:
    """Тесты calculate_cumulative_vwap()."""

    def test_cumulative_vwap_single_trade(self):
        """Один trade → cumulative VWAP = price."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 1000, "priceTicks": 100, "qtySteps": 10},
        ]

        points = calculate_cumulative_vwap(events)

        assert len(points) == 1
        assert points[0]["timestamp_us"] == 1000
        assert points[0]["vwap_ticks"] == 100
        assert points[0]["total_volume_steps"] == 10

    def test_cumulative_vwap_accumulates(self):
        """Cumulative VWAP накапливает turnover и volume."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 1000, "priceTicks": 100, "qtySteps": 10},
            {"eventType": "RawTrade", "timestampUs": 2000, "priceTicks": 110, "qtySteps": 20},
        ]

        points = calculate_cumulative_vwap(events)

        assert len(points) == 2

        # Point 0: VWAP = 100
        assert points[0]["vwap_ticks"] == 100
        assert points[0]["total_volume_steps"] == 10

        # Point 1: VWAP = (100*10 + 110*20) / 30 = 106
        assert points[1]["vwap_ticks"] == 106
        assert points[1]["total_volume_steps"] == 30

    def test_cumulative_vwap_running_average(self):
        """Cumulative VWAP корректно пересчитывается на каждом trade."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 1000, "priceTicks": 100, "qtySteps": 10},
            {"eventType": "RawTrade", "timestampUs": 2000, "priceTicks": 200, "qtySteps": 10},
            {"eventType": "RawTrade", "timestampUs": 3000, "priceTicks": 300, "qtySteps": 10},
        ]

        points = calculate_cumulative_vwap(events)

        assert len(points) == 3

        # VWAP[0] = 100
        assert points[0]["vwap_ticks"] == 100

        # VWAP[1] = (100*10 + 200*10) / 20 = 150
        assert points[1]["vwap_ticks"] == 150

        # VWAP[2] = (100*10 + 200*10 + 300*10) / 30 = 200
        assert points[2]["vwap_ticks"] == 200

    def test_cumulative_vwap_filters_non_trades(self):
        """Фильтрует BookCheckpoint события."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 1000, "priceTicks": 100, "qtySteps": 10},
            {"eventType": "BookCheckpoint", "timestampUs": 1500, "priceTicks": 999, "qtySteps": 999},
            {"eventType": "RawTrade", "timestampUs": 2000, "priceTicks": 200, "qtySteps": 10},
        ]

        points = calculate_cumulative_vwap(events)

        assert len(points) == 2  # только RawTrade
        assert points[1]["vwap_ticks"] == 150

    def test_cumulative_vwap_empty_events(self):
        """Пустой список → пустой результат."""
        points = calculate_cumulative_vwap([])
        assert points == []
