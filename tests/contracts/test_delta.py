"""
Тесты Delta calculation (Этап 3 / P3-A1).

Проверяют: calculate_delta(), aggregate_delta_by_interval().
"""

import pytest

from packages.analytics.delta import calculate_delta, aggregate_delta_by_interval

pytestmark = pytest.mark.contract


class TestDeltaCalculation:
    """Тесты calculate_delta() для RawTrade events."""

    def test_calculate_delta_only_buys(self):
        """Только buy trades → delta > 0."""
        events = [
            {"eventType": "RawTrade", "qtySteps": 100, "takerSide": "Buy"},
            {"eventType": "RawTrade", "qtySteps": 200, "takerSide": "Buy"},
        ]

        result = calculate_delta(events)

        assert result["buy_volume"] == 300
        assert result["sell_volume"] == 0
        assert result["delta"] == 300
        assert result["total_volume"] == 300
        assert result["trade_count"] == 2
        assert result["buy_count"] == 2
        assert result["sell_count"] == 0

    def test_calculate_delta_only_sells(self):
        """Только sell trades → delta < 0."""
        events = [
            {"eventType": "RawTrade", "qtySteps": 100, "takerSide": "Sell"},
            {"eventType": "RawTrade", "qtySteps": 200, "takerSide": "Sell"},
        ]

        result = calculate_delta(events)

        assert result["buy_volume"] == 0
        assert result["sell_volume"] == 300
        assert result["delta"] == -300
        assert result["total_volume"] == 300
        assert result["trade_count"] == 2
        assert result["buy_count"] == 0
        assert result["sell_count"] == 2

    def test_calculate_delta_mixed_trades(self):
        """Mixed buy/sell → delta = buy - sell."""
        events = [
            {"eventType": "RawTrade", "qtySteps": 100, "takerSide": "Buy"},
            {"eventType": "RawTrade", "qtySteps": 50, "takerSide": "Sell"},
            {"eventType": "RawTrade", "qtySteps": 200, "takerSide": "Buy"},
            {"eventType": "RawTrade", "qtySteps": 150, "takerSide": "Sell"},
        ]

        result = calculate_delta(events)

        assert result["buy_volume"] == 300  # 100 + 200
        assert result["sell_volume"] == 200  # 50 + 150
        assert result["delta"] == 100  # 300 - 200
        assert result["total_volume"] == 500
        assert result["trade_count"] == 4
        assert result["buy_count"] == 2
        assert result["sell_count"] == 2

    def test_calculate_delta_filters_non_trades(self):
        """Фильтрует события не-RawTrade."""
        events = [
            {"eventType": "RawTrade", "qtySteps": 100, "takerSide": "Buy"},
            {"eventType": "BookCheckpoint", "qtySteps": 999, "takerSide": "Buy"},  # игнорируется
            {"eventType": "RawTrade", "qtySteps": 50, "takerSide": "Sell"},
        ]

        result = calculate_delta(events)

        assert result["buy_volume"] == 100
        assert result["sell_volume"] == 50
        assert result["delta"] == 50
        assert result["trade_count"] == 2

    def test_calculate_delta_empty_events(self):
        """Пустой список → нулевая Delta."""
        result = calculate_delta([])

        assert result["buy_volume"] == 0
        assert result["sell_volume"] == 0
        assert result["delta"] == 0
        assert result["total_volume"] == 0
        assert result["trade_count"] == 0


class TestDeltaAggregation:
    """Тесты aggregate_delta_by_interval()."""

    def test_aggregate_delta_single_bar(self):
        """Все события в одном bar."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 1000000, "qtySteps": 100, "takerSide": "Buy"},
            {"eventType": "RawTrade", "timestampUs": 1500000, "qtySteps": 50, "takerSide": "Sell"},
        ]

        bars = aggregate_delta_by_interval(events, interval_us=60_000_000)  # 1m

        assert len(bars) == 1
        bar = bars[0]
        assert bar["timestamp_us"] == 0  # floor(1.5s / 60s) * 60s = 0
        assert bar["buy_volume"] == 100
        assert bar["sell_volume"] == 50
        assert bar["delta"] == 50
        assert bar["trade_count"] == 2

    def test_aggregate_delta_multiple_bars(self):
        """События в разных bars."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 0, "qtySteps": 100, "takerSide": "Buy"},
            {"eventType": "RawTrade", "timestampUs": 60_000_000, "qtySteps": 200, "takerSide": "Buy"},
            {"eventType": "RawTrade", "timestampUs": 120_000_000, "qtySteps": 50, "takerSide": "Sell"},
        ]

        bars = aggregate_delta_by_interval(events, interval_us=60_000_000)  # 1m

        assert len(bars) == 3

        # Bar 0: 0s
        assert bars[0]["timestamp_us"] == 0
        assert bars[0]["delta"] == 100

        # Bar 1: 60s
        assert bars[1]["timestamp_us"] == 60_000_000
        assert bars[1]["delta"] == 200

        # Bar 2: 120s
        assert bars[2]["timestamp_us"] == 120_000_000
        assert bars[2]["delta"] == -50

    def test_aggregate_delta_bars_sorted(self):
        """Bars отсортированы по timestamp."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 120_000_000, "qtySteps": 50, "takerSide": "Sell"},
            {"eventType": "RawTrade", "timestampUs": 0, "qtySteps": 100, "takerSide": "Buy"},
            {"eventType": "RawTrade", "timestampUs": 60_000_000, "qtySteps": 200, "takerSide": "Buy"},
        ]

        bars = aggregate_delta_by_interval(events, interval_us=60_000_000)

        assert len(bars) == 3
        assert bars[0]["timestamp_us"] == 0
        assert bars[1]["timestamp_us"] == 60_000_000
        assert bars[2]["timestamp_us"] == 120_000_000

    def test_aggregate_delta_filters_non_trades(self):
        """Фильтрует BookCheckpoint события."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 0, "qtySteps": 100, "takerSide": "Buy"},
            {"eventType": "BookCheckpoint", "timestampUs": 0, "qtySteps": 999, "takerSide": "Buy"},
            {"eventType": "RawTrade", "timestampUs": 0, "qtySteps": 50, "takerSide": "Sell"},
        ]

        bars = aggregate_delta_by_interval(events, interval_us=60_000_000)

        assert len(bars) == 1
        assert bars[0]["buy_volume"] == 100
        assert bars[0]["sell_volume"] == 50

    def test_aggregate_delta_empty_events(self):
        """Пустой список → пустой результат."""
        bars = aggregate_delta_by_interval([], interval_us=60_000_000)
        assert bars == []

    def test_aggregate_delta_different_intervals(self):
        """Разные intervals работают корректно."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 0, "qtySteps": 100, "takerSide": "Buy"},
            {"eventType": "RawTrade", "timestampUs": 2 * 60_000_000, "qtySteps": 200, "takerSide": "Buy"},
        ]

        # 1m interval (разные bars)
        bars_1m = aggregate_delta_by_interval(events, interval_us=60_000_000)
        assert len(bars_1m) == 2

        # 5m interval (оба события в одном bar: 0-5m)
        bars_5m = aggregate_delta_by_interval(events, interval_us=5 * 60_000_000)
        assert len(bars_5m) == 1
        assert bars_5m[0]["buy_volume"] == 300
