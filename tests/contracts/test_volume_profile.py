"""
Тесты Volume Profile calculation (Этап 3 / P3-A4).

Проверяют: calculate_volume_profile(), find_hvn_lvn().
"""

import pytest

from packages.analytics.volume_profile import calculate_volume_profile, find_hvn_lvn

pytestmark = pytest.mark.contract


class TestVolumeProfile:
    """Тесты calculate_volume_profile()."""

    def test_volume_profile_single_price(self):
        """Все trades на одной цене → POC = эта цена."""
        events = [
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 10, "takerSide": "Buy"},
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 20, "takerSide": "Sell"},
        ]

        profile = calculate_volume_profile(events, price_bin_ticks=100)

        assert len(profile["price_levels"]) == 1
        level = profile["price_levels"][0]
        assert level["price_ticks"] == 100
        assert level["volume_steps"] == 30
        assert level["trade_count"] == 2
        assert level["buy_volume_steps"] == 10
        assert level["sell_volume_steps"] == 20

        # POC = единственный уровень
        assert profile["poc_price_ticks"] == 100

    def test_volume_profile_multiple_prices(self):
        """Несколько ценовых уровней → POC = уровень с max volume."""
        events = [
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 10, "takerSide": "Buy"},
            {"eventType": "RawTrade", "priceTicks": 200, "qtySteps": 50, "takerSide": "Buy"},
            {"eventType": "RawTrade", "priceTicks": 300, "qtySteps": 20, "takerSide": "Buy"},
        ]

        profile = calculate_volume_profile(events, price_bin_ticks=100)

        assert len(profile["price_levels"]) == 3

        # POC = 200 (max volume)
        assert profile["poc_price_ticks"] == 200
        assert profile["total_volume_steps"] == 80

    def test_volume_profile_price_binning(self):
        """Цены группируются в bins."""
        events = [
            {"eventType": "RawTrade", "priceTicks": 105, "qtySteps": 10, "takerSide": "Buy"},
            {"eventType": "RawTrade", "priceTicks": 110, "qtySteps": 20, "takerSide": "Buy"},
            {"eventType": "RawTrade", "priceTicks": 205, "qtySteps": 30, "takerSide": "Buy"},
        ]

        # bin_size = 100 → 105, 110 → bin 100; 205 → bin 200
        profile = calculate_volume_profile(events, price_bin_ticks=100)

        assert len(profile["price_levels"]) == 2
        assert profile["price_levels"][0]["price_ticks"] == 100
        assert profile["price_levels"][0]["volume_steps"] == 30  # 10 + 20
        assert profile["price_levels"][1]["price_ticks"] == 200
        assert profile["price_levels"][1]["volume_steps"] == 30

    def test_volume_profile_value_area(self):
        """Value Area содержит ~70% объёма."""
        events = [
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 10, "takerSide": "Buy"},
            {"eventType": "RawTrade", "priceTicks": 200, "qtySteps": 50, "takerSide": "Buy"},  # POC
            {"eventType": "RawTrade", "priceTicks": 300, "qtySteps": 10, "takerSide": "Buy"},
            {"eventType": "RawTrade", "priceTicks": 400, "qtySteps": 10, "takerSide": "Buy"},
        ]

        profile = calculate_volume_profile(events, price_bin_ticks=100)

        # Total = 80, 70% = 56
        # POC = 200 (50), расширяем до 56+
        assert profile["poc_price_ticks"] == 200
        assert profile["total_volume_steps"] == 80
        assert profile["value_area_volume_steps"] >= 56  # 70%

        # Value Area включает POC
        assert profile["value_area_low_ticks"] <= 200
        assert profile["value_area_high_ticks"] >= 200

    def test_volume_profile_value_area_expands_from_poc(self):
        """Value Area расширяется от POC вверх/вниз."""
        events = [
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 5, "takerSide": "Buy"},
            {"eventType": "RawTrade", "priceTicks": 200, "qtySteps": 20, "takerSide": "Buy"},  # POC
            {"eventType": "RawTrade", "priceTicks": 300, "qtySteps": 15, "takerSide": "Buy"},
            {"eventType": "RawTrade", "priceTicks": 400, "qtySteps": 5, "takerSide": "Buy"},
        ]

        profile = calculate_volume_profile(events, price_bin_ticks=100)

        # Total = 45, 70% = 31.5
        # POC = 200 (20), расширяем: +300 (15) = 35 ≥ 31.5
        assert profile["poc_price_ticks"] == 200
        assert profile["value_area_low_ticks"] == 200
        assert profile["value_area_high_ticks"] == 300

    def test_volume_profile_filters_non_trades(self):
        """Фильтрует BookCheckpoint события."""
        events = [
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 10, "takerSide": "Buy"},
            {"eventType": "BookCheckpoint", "priceTicks": 999, "qtySteps": 999, "takerSide": "Buy"},
            {"eventType": "RawTrade", "priceTicks": 200, "qtySteps": 20, "takerSide": "Buy"},
        ]

        profile = calculate_volume_profile(events, price_bin_ticks=100)

        assert len(profile["price_levels"]) == 2
        assert profile["total_volume_steps"] == 30  # только RawTrade

    def test_volume_profile_empty_events(self):
        """Пустой список → пустой profile."""
        profile = calculate_volume_profile([], price_bin_ticks=100)

        assert profile["price_levels"] == []
        assert profile["poc_price_ticks"] == 0
        assert profile["total_volume_steps"] == 0

    def test_volume_profile_sorted_by_price(self):
        """price_levels отсортированы по цене."""
        events = [
            {"eventType": "RawTrade", "priceTicks": 300, "qtySteps": 10, "takerSide": "Buy"},
            {"eventType": "RawTrade", "priceTicks": 100, "qtySteps": 20, "takerSide": "Buy"},
            {"eventType": "RawTrade", "priceTicks": 200, "qtySteps": 30, "takerSide": "Buy"},
        ]

        profile = calculate_volume_profile(events, price_bin_ticks=100)

        assert len(profile["price_levels"]) == 3
        assert profile["price_levels"][0]["price_ticks"] == 100
        assert profile["price_levels"][1]["price_ticks"] == 200
        assert profile["price_levels"][2]["price_ticks"] == 300


class TestHVNLVN:
    """Тесты find_hvn_lvn()."""

    def test_find_hvn_lvn_identifies_nodes(self):
        """Корректно определяет HVN и LVN."""
        profile = {
            "price_levels": [
                {"price_ticks": 100, "volume_steps": 10},  # LVN
                {"price_ticks": 200, "volume_steps": 50},  # HVN
                {"price_ticks": 300, "volume_steps": 20},  # mid
                {"price_ticks": 400, "volume_steps": 60},  # HVN
            ],
        }

        result = find_hvn_lvn(profile, hvn_threshold_percentile=0.75, lvn_threshold_percentile=0.25)

        # HVN: volumes ≥ 75th percentile
        assert len(result["hvn_levels"]) >= 1
        hvn_volumes = [level["volume_steps"] for level in result["hvn_levels"]]
        assert 50 in hvn_volumes or 60 in hvn_volumes

        # LVN: volumes ≤ 25th percentile
        assert len(result["lvn_levels"]) >= 1
        lvn_volumes = [level["volume_steps"] for level in result["lvn_levels"]]
        assert 10 in lvn_volumes

    def test_find_hvn_lvn_thresholds(self):
        """Пороги HVN/LVN рассчитываются корректно."""
        profile = {
            "price_levels": [
                {"price_ticks": 100, "volume_steps": 10},
                {"price_ticks": 200, "volume_steps": 20},
                {"price_ticks": 300, "volume_steps": 30},
                {"price_ticks": 400, "volume_steps": 40},
            ],
        }

        result = find_hvn_lvn(profile, hvn_threshold_percentile=0.75, lvn_threshold_percentile=0.25)

        # Sorted volumes: [10, 20, 30, 40]
        # 75th percentile index: int(4 * 0.75) = 3 → volumes[3] = 40
        # 25th percentile index: int(4 * 0.25) = 1 → volumes[1] = 20
        assert result["hvn_threshold"] == 40
        assert result["lvn_threshold"] == 20

    def test_find_hvn_lvn_empty_profile(self):
        """Пустой profile → пустые HVN/LVN."""
        profile = {"price_levels": []}

        result = find_hvn_lvn(profile)

        assert result["hvn_levels"] == []
        assert result["lvn_levels"] == []
        assert result["hvn_threshold"] == 0
        assert result["lvn_threshold"] == 0

    def test_find_hvn_lvn_single_level(self):
        """Один уровень → и HVN, и LVN."""
        profile = {
            "price_levels": [
                {"price_ticks": 100, "volume_steps": 50},
            ],
        }

        result = find_hvn_lvn(profile)

        # Единственный уровень удовлетворяет обоим порогам
        assert len(result["hvn_levels"]) == 1
        assert len(result["lvn_levels"]) == 1
