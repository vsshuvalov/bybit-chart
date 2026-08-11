"""
Tests для regime detector.

Roadmap §9.1 Этап 6 требования:
- Regime classification
- Feature importance scoring
- Multi-feature aggregation
"""

import pytest

from contracts.regime import MarketRegime, OrderflowFeature, RegimeState
from packages.analytics.regime import RegimeDetector


pytestmark = pytest.mark.analytics


class TestRegimeDetector:
    """Tests для RegimeDetector."""

    def test_empty_detector_returns_unknown(self):
        """Детектор без features возвращает UNKNOWN режим."""
        detector = RegimeDetector(symbol="BTCUSDT", window_ms=300000)
        state = detector.compute_regime()

        assert state.regime == MarketRegime.UNKNOWN
        assert state.regime_confidence == 0.0
        assert len(state.features) == 0

    def test_add_feature(self):
        """Добавление feature обновляет состояние."""
        detector = RegimeDetector(symbol="BTCUSDT")
        detector.add_feature("obi", active=True, value=0.5, confidence=0.8, timestamp_ms=100000)

        state = detector.compute_regime()
        assert len(state.features) == 1
        assert state.features[0].name == "obi"
        assert state.features[0].active is True
        assert state.features[0].value == 0.5
        assert state.features[0].confidence == 0.8

    def test_buying_pressure_markup_regime(self):
        """Сильное buying pressure → MARKUP режим."""
        detector = RegimeDetector(symbol="BTCUSDT")

        # Добавляем features с высоким buying pressure и imbalance
        detector.add_feature("obi", active=True, value=0.9, confidence=0.95, timestamp_ms=100000)
        detector.add_feature("ofi", active=True, value=0.8, confidence=0.9, timestamp_ms=100000)
        detector.add_feature("walls_bid", active=True, value=50000, confidence=0.8, timestamp_ms=100000, metadata={"side": "bid"})
        detector.add_feature("absorption", active=True, confidence=0.7, timestamp_ms=100000, metadata={"side": "bid"})

        state = detector.compute_regime()
        assert state.regime == MarketRegime.MARKUP
        assert state.regime_confidence > 0.7

    def test_selling_pressure_markdown_regime(self):
        """Сильное selling pressure → MARKDOWN режим."""
        detector = RegimeDetector(symbol="BTCUSDT")

        # Добавляем features с высоким selling pressure и imbalance
        detector.add_feature("obi", active=True, value=-0.9, confidence=0.95, timestamp_ms=100000)
        detector.add_feature("ofi", active=True, value=-0.8, confidence=0.9, timestamp_ms=100000)
        detector.add_feature("walls_ask", active=True, value=50100, confidence=0.8, timestamp_ms=100000, metadata={"side": "ask"})
        detector.add_feature("liquidation_cascade", active=True, confidence=0.8, timestamp_ms=100000, metadata={"direction": "Sell"})

        state = detector.compute_regime()
        assert state.regime == MarketRegime.MARKDOWN
        assert state.regime_confidence > 0.7

    def test_balanced_orderflow_accumulation(self):
        """Balanced orderflow с walls → ACCUMULATION."""
        detector = RegimeDetector(symbol="BTCUSDT")

        detector.add_feature("obi", active=True, value=0.1, confidence=0.6, timestamp_ms=100000)
        detector.add_feature("walls_bid", active=True, value=50000, confidence=0.7, timestamp_ms=100000, metadata={"side": "bid"})
        detector.add_feature("walls_ask", active=True, value=50100, confidence=0.7, timestamp_ms=100000, metadata={"side": "ask"})

        state = detector.compute_regime()
        assert state.regime in (MarketRegime.ACCUMULATION, MarketRegime.NEUTRAL)

    def test_low_activity_neutral(self):
        """Низкая активность → NEUTRAL режим."""
        detector = RegimeDetector(symbol="BTCUSDT")

        # Только неактивные или низкой confidence features
        detector.add_feature("obi", active=False, value=0.0, confidence=0.2, timestamp_ms=100000)
        detector.add_feature("walls_bid", active=False, confidence=0.1, timestamp_ms=100000)

        state = detector.compute_regime()
        assert state.regime == MarketRegime.NEUTRAL

    def test_feature_importance_sorted(self):
        """Feature importance отсортирован по важности."""
        detector = RegimeDetector(symbol="BTCUSDT")

        detector.add_feature("obi", active=True, value=0.8, confidence=0.9, timestamp_ms=100000)
        detector.add_feature("walls_bid", active=True, value=50000, confidence=0.7, timestamp_ms=100000)
        detector.add_feature("absorption", active=False, confidence=0.2, timestamp_ms=100000)

        analysis = detector.analyze()
        importance = analysis.feature_importance

        # Проверить, что отсортировано по убыванию
        assert len(importance) == 3
        assert importance[0].importance >= importance[1].importance
        assert importance[1].importance >= importance[2].importance

        # Самая важная feature должна быть активной
        assert importance[0].importance > 0

    def test_inactive_features_zero_importance(self):
        """Неактивные features имеют нулевую importance."""
        detector = RegimeDetector(symbol="BTCUSDT")

        detector.add_feature("obi", active=False, value=0.0, confidence=0.5, timestamp_ms=100000)

        analysis = detector.analyze()
        obi_importance = next(f for f in analysis.feature_importance if f.name == "obi")

        assert obi_importance.importance == 0.0

    def test_regime_state_contains_window(self):
        """RegimeState содержит window_ms."""
        detector = RegimeDetector(symbol="BTCUSDT", window_ms=600000)
        detector.add_feature("obi", active=True, value=0.5, confidence=0.8, timestamp_ms=100000)

        state = detector.compute_regime()
        assert state.window_ms == 600000

    def test_last_update_timestamp(self):
        """Timestamp состояния = max timestamp features."""
        detector = RegimeDetector(symbol="BTCUSDT")

        detector.add_feature("obi", active=True, value=0.5, confidence=0.8, timestamp_ms=100000)
        detector.add_feature("walls_bid", active=True, value=50000, confidence=0.7, timestamp_ms=200000)

        state = detector.compute_regime()
        assert state.timestamp_ms == 200000

    def test_feature_metadata_preserved(self):
        """Metadata features сохраняется."""
        detector = RegimeDetector(symbol="BTCUSDT")

        metadata = {"side": "bid", "price_level": 50000, "qty": 1000}
        detector.add_feature("walls_bid", active=True, confidence=0.8, timestamp_ms=100000, metadata=metadata)

        state = detector.compute_regime()
        wall_feature = state.features[0]

        assert wall_feature.metadata == metadata
        assert wall_feature.metadata["side"] == "bid"
        assert wall_feature.metadata["price_level"] == 50000


def test_regime_analysis_contains_state_and_importance():
    """RegimeAnalysis содержит state и feature_importance."""
    detector = RegimeDetector(symbol="BTCUSDT")
    detector.add_feature("obi", active=True, value=0.7, confidence=0.9, timestamp_ms=100000)

    analysis = detector.analyze()

    assert isinstance(analysis.state, RegimeState)
    assert len(analysis.feature_importance) == 1
    assert analysis.state.regime != MarketRegime.UNKNOWN
