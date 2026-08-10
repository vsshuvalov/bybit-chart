"""
Тесты CVD (Cumulative Volume Delta) calculation (Этап 3 / P3-A2).

Проверяют: calculate_cvd(), aggregate_cvd_by_interval(), reset_cvd_at_index().
"""

import pytest

from packages.analytics.cvd import (
    calculate_cvd,
    aggregate_cvd_by_interval,
    reset_cvd_at_index,
)

pytestmark = pytest.mark.contract


class TestCVDCalculation:
    """Тесты calculate_cvd() для кумулятивной суммы Delta."""

    def test_calculate_cvd_positive_deltas(self):
        """Положительные deltas → растущий CVD."""
        delta_bars = [
            {"timestamp_us": 0, "delta": 100},
            {"timestamp_us": 60_000_000, "delta": 50},
            {"timestamp_us": 120_000_000, "delta": 75},
        ]

        cvd_bars = calculate_cvd(delta_bars)

        assert len(cvd_bars) == 3
        assert cvd_bars[0]["cvd"] == 100
        assert cvd_bars[1]["cvd"] == 150  # 100 + 50
        assert cvd_bars[2]["cvd"] == 225  # 150 + 75

    def test_calculate_cvd_negative_deltas(self):
        """Отрицательные deltas → падающий CVD."""
        delta_bars = [
            {"timestamp_us": 0, "delta": 100},
            {"timestamp_us": 60_000_000, "delta": -50},
            {"timestamp_us": 120_000_000, "delta": -30},
        ]

        cvd_bars = calculate_cvd(delta_bars)

        assert len(cvd_bars) == 3
        assert cvd_bars[0]["cvd"] == 100
        assert cvd_bars[1]["cvd"] == 50  # 100 - 50
        assert cvd_bars[2]["cvd"] == 20  # 50 - 30

    def test_calculate_cvd_mixed_deltas(self):
        """Смешанные deltas → CVD растёт/падает."""
        delta_bars = [
            {"timestamp_us": 0, "delta": 100},
            {"timestamp_us": 60_000_000, "delta": -150},  # CVD падает
            {"timestamp_us": 120_000_000, "delta": 200},  # CVD растёт
        ]

        cvd_bars = calculate_cvd(delta_bars)

        assert len(cvd_bars) == 3
        assert cvd_bars[0]["cvd"] == 100
        assert cvd_bars[1]["cvd"] == -50  # 100 - 150
        assert cvd_bars[2]["cvd"] == 150  # -50 + 200

    def test_calculate_cvd_preserves_original_fields(self):
        """CVD сохраняет оригинальные поля из delta_bars."""
        delta_bars = [
            {
                "timestamp_us": 0,
                "delta": 100,
                "buy_volume": 150,
                "sell_volume": 50,
                "trade_count": 10,
            },
        ]

        cvd_bars = calculate_cvd(delta_bars)

        assert cvd_bars[0]["cvd"] == 100
        assert cvd_bars[0]["buy_volume"] == 150
        assert cvd_bars[0]["sell_volume"] == 50
        assert cvd_bars[0]["trade_count"] == 10

    def test_calculate_cvd_empty_bars(self):
        """Пустой список → пустой результат."""
        cvd_bars = calculate_cvd([])
        assert cvd_bars == []

    def test_calculate_cvd_single_bar(self):
        """Один bar → CVD = delta."""
        delta_bars = [{"timestamp_us": 0, "delta": 100}]
        cvd_bars = calculate_cvd(delta_bars)

        assert len(cvd_bars) == 1
        assert cvd_bars[0]["cvd"] == 100


class TestCVDAggregation:
    """Тесты aggregate_cvd_by_interval() (Delta + CVD в одном вызове)."""

    def test_aggregate_cvd_from_trades(self):
        """Агрегация CVD напрямую из RawTrade событий."""
        events = [
            {"eventType": "RawTrade", "timestampUs": 0, "qtySteps": 100, "takerSide": "Buy"},
            {"eventType": "RawTrade", "timestampUs": 0, "qtySteps": 50, "takerSide": "Sell"},
            {"eventType": "RawTrade", "timestampUs": 60_000_000, "qtySteps": 200, "takerSide": "Buy"},
        ]

        cvd_bars = aggregate_cvd_by_interval(events, interval_us=60_000_000)

        assert len(cvd_bars) == 2

        # Bar 0: delta = 100 - 50 = 50, cvd = 50
        assert cvd_bars[0]["delta"] == 50
        assert cvd_bars[0]["cvd"] == 50

        # Bar 1: delta = 200, cvd = 50 + 200 = 250
        assert cvd_bars[1]["delta"] == 200
        assert cvd_bars[1]["cvd"] == 250

    def test_aggregate_cvd_empty_events(self):
        """Пустой список событий → пустой результат."""
        cvd_bars = aggregate_cvd_by_interval([], interval_us=60_000_000)
        assert cvd_bars == []


class TestCVDReset:
    """Тесты reset_cvd_at_index() для сброса CVD."""

    def test_reset_cvd_at_middle_index(self):
        """Сброс CVD в середине → пересчёт после reset."""
        cvd_bars = [
            {"timestamp_us": 0, "cvd": 100, "delta": 100},
            {"timestamp_us": 60_000_000, "cvd": 150, "delta": 50},
            {"timestamp_us": 120_000_000, "cvd": 125, "delta": -25},
            {"timestamp_us": 180_000_000, "cvd": 175, "delta": 50},
        ]

        reset_bars = reset_cvd_at_index(cvd_bars, reset_index=2)

        assert len(reset_bars) == 4

        # Bars до reset — без изменений
        assert reset_bars[0]["cvd"] == 100
        assert reset_bars[1]["cvd"] == 150

        # Bars после reset — пересчитаны
        assert reset_bars[2]["cvd"] == -25  # reset: cvd = delta
        assert reset_bars[3]["cvd"] == 25  # cvd = -25 + 50

    def test_reset_cvd_at_first_index(self):
        """Сброс с первого bar → весь CVD пересчитан."""
        cvd_bars = [
            {"cvd": 100, "delta": 100},
            {"cvd": 150, "delta": 50},
            {"cvd": 125, "delta": -25},
        ]

        reset_bars = reset_cvd_at_index(cvd_bars, reset_index=0)

        assert reset_bars[0]["cvd"] == 100  # cvd = delta
        assert reset_bars[1]["cvd"] == 150  # cvd = 100 + 50
        assert reset_bars[2]["cvd"] == 125  # cvd = 150 - 25

    def test_reset_cvd_at_last_index(self):
        """Сброс на последнем bar → только последний пересчитан."""
        cvd_bars = [
            {"cvd": 100, "delta": 100},
            {"cvd": 150, "delta": 50},
            {"cvd": 125, "delta": -25},
        ]

        reset_bars = reset_cvd_at_index(cvd_bars, reset_index=2)

        assert reset_bars[0]["cvd"] == 100  # без изменений
        assert reset_bars[1]["cvd"] == 150  # без изменений
        assert reset_bars[2]["cvd"] == -25  # reset: cvd = delta

    def test_reset_cvd_out_of_bounds(self):
        """reset_index >= len → нет изменений."""
        cvd_bars = [
            {"cvd": 100, "delta": 100},
            {"cvd": 150, "delta": 50},
        ]

        reset_bars = reset_cvd_at_index(cvd_bars, reset_index=10)

        assert len(reset_bars) == 2
        assert reset_bars[0]["cvd"] == 100
        assert reset_bars[1]["cvd"] == 150

    def test_reset_cvd_empty_bars(self):
        """Пустой список → пустой результат."""
        reset_bars = reset_cvd_at_index([], reset_index=0)
        assert reset_bars == []

    def test_reset_cvd_preserves_fields(self):
        """reset_cvd_at_index() сохраняет оригинальные поля."""
        cvd_bars = [
            {"timestamp_us": 0, "cvd": 100, "delta": 100, "buy_volume": 150},
            {"timestamp_us": 60_000_000, "cvd": 150, "delta": 50, "buy_volume": 200},
        ]

        reset_bars = reset_cvd_at_index(cvd_bars, reset_index=1)

        assert reset_bars[1]["cvd"] == 50  # пересчитан
        assert reset_bars[1]["buy_volume"] == 200  # сохранён
        assert reset_bars[1]["timestamp_us"] == 60_000_000  # сохранён
