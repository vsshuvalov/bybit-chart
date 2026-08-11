"""
Property-based tests для Regime classification.

Использует Hypothesis для проверки invariants классификации режима.
"""

import pytest
from hypothesis import given, strategies as st, assume

from contracts.regime import MarketRegime
from packages.analytics.regime import RegimeDetector


pytestmark = [pytest.mark.analytics, pytest.mark.property]


@given(
    features=st.lists(
        st.tuples(
            st.text(min_size=1, max_size=20),  # name
            st.booleans(),  # active
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False),  # confidence
        ),
        min_size=0,
        max_size=10,
    )
)
def test_regime_deterministic(features):
    """Одинаковые features → одинаковый regime."""
    detector1 = RegimeDetector(symbol="BTCUSDT")
    detector2 = RegimeDetector(symbol="BTCUSDT")

    # Добавить одинаковые features
    for name, active, confidence in features:
        detector1.add_feature(name, active=active, confidence=confidence, timestamp_ms=100000)
        detector2.add_feature(name, active=active, confidence=confidence, timestamp_ms=100000)

    state1 = detector1.compute_regime()
    state2 = detector2.compute_regime()

    assert state1.regime == state2.regime
    assert state1.regime_confidence == state2.regime_confidence


@given(
    features=st.lists(
        st.tuples(
            st.text(min_size=1, max_size=20),
            st.booleans(),
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        ),
        min_size=1,
        max_size=10,
    )
)
def test_regime_order_independence(features):
    """Порядок добавления features не влияет на классификацию."""
    import random

    shuffled = features.copy()
    random.shuffle(shuffled)

    detector1 = RegimeDetector(symbol="BTCUSDT")
    detector2 = RegimeDetector(symbol="BTCUSDT")

    # Original order
    for name, active, confidence in features:
        detector1.add_feature(name, active=active, confidence=confidence, timestamp_ms=100000)

    # Shuffled order
    for name, active, confidence in shuffled:
        detector2.add_feature(name, active=active, confidence=confidence, timestamp_ms=100000)

    state1 = detector1.compute_regime()
    state2 = detector2.compute_regime()

    # Должны быть одинаковыми
    assert state1.regime == state2.regime
    assert abs(state1.regime_confidence - state2.regime_confidence) < 0.01


@given(
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
def test_regime_confidence_always_in_range(confidence):
    """Regime confidence всегда в [0.0, 1.0]."""
    detector = RegimeDetector(symbol="BTCUSDT")
    detector.add_feature("test", active=True, confidence=confidence, timestamp_ms=100000)

    state = detector.compute_regime()

    assert 0.0 <= state.regime_confidence <= 1.0


def test_regime_empty_detector_unknown():
    """Пустой detector → UNKNOWN regime."""
    detector = RegimeDetector(symbol="BTCUSDT")
    state = detector.compute_regime()

    assert state.regime == MarketRegime.UNKNOWN
    assert state.regime_confidence == 0.0


@given(
    active_count=st.integers(min_value=0, max_value=10),
    inactive_count=st.integers(min_value=0, max_value=10),
)
def test_regime_inactive_features_ignored(active_count, inactive_count):
    """Неактивные features не влияют на классификацию."""
    detector = RegimeDetector(symbol="BTCUSDT")

    # Добавить active features
    for i in range(active_count):
        detector.add_feature(f"active_{i}", active=True, confidence=0.8, timestamp_ms=100000)

    # Добавить inactive features
    for i in range(inactive_count):
        detector.add_feature(f"inactive_{i}", active=False, confidence=0.9, timestamp_ms=100000)

    analysis = detector.analyze()

    # Inactive features должны иметь importance=0
    for fi in analysis.feature_importance:
        if not any(f.name == fi.name and f.active for f in analysis.state.features):
            assert fi.importance == 0.0


@given(
    value=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
def test_regime_contribution_proportional(value, confidence):
    """Contribution пропорционален value * confidence."""
    detector = RegimeDetector(symbol="BTCUSDT")
    detector.add_feature("test", active=True, value=value, confidence=confidence, timestamp_ms=100000)

    analysis = detector.analyze()
    test_fi = next(fi for fi in analysis.feature_importance if fi.name == "test")

    expected_contribution = value * confidence
    assert abs(test_fi.contribution - expected_contribution) < 0.01


@given(
    timestamp=st.integers(min_value=0, max_value=2000000000000),
)
def test_regime_timestamp_tracked(timestamp):
    """Timestamp корректно отслеживается."""
    detector = RegimeDetector(symbol="BTCUSDT")
    detector.add_feature("test", active=True, confidence=0.8, timestamp_ms=timestamp)

    state = detector.compute_regime()

    # State timestamp должен быть >= feature timestamp
    assert state.timestamp_ms >= timestamp


@given(
    window_ms=st.integers(min_value=60000, max_value=3600000),
)
def test_regime_window_preserved(window_ms):
    """Window размер сохраняется в state."""
    detector = RegimeDetector(symbol="BTCUSDT", window_ms=window_ms)
    detector.add_feature("test", active=True, confidence=0.8, timestamp_ms=100000)

    state = detector.compute_regime()

    assert state.window_ms == window_ms


@given(
    metadata_keys=st.lists(
        st.tuples(st.text(min_size=1, max_size=10), st.integers()),
        min_size=0,
        max_size=5,
    )
)
def test_regime_metadata_preserved(metadata_keys):
    """Metadata features сохраняется."""
    detector = RegimeDetector(symbol="BTCUSDT")

    metadata = {key: value for key, value in metadata_keys}
    detector.add_feature("test", active=True, confidence=0.8, timestamp_ms=100000, metadata=metadata)

    state = detector.compute_regime()
    test_feature = next(f for f in state.features if f.name == "test")

    assert test_feature.metadata == metadata


def test_regime_types_valid():
    """Все возможные regime types валидны."""
    valid_regimes = {
        MarketRegime.MARKUP,
        MarketRegime.MARKDOWN,
        MarketRegime.ACCUMULATION,
        MarketRegime.DISTRIBUTION,
        MarketRegime.NEUTRAL,
        MarketRegime.UNKNOWN,
    }

    # Различные configurations features
    configs = [
        [],  # Empty
        [("obi", True, 0.9, 0.8)],  # Strong buying
        [("obi", True, 0.9, -0.8)],  # Strong selling
        [("obi", True, 0.5, 0.1), ("walls_bid", True, 0.7, None)],  # Balanced
        [("obi", False, 0.1, 0.0)],  # Low activity
    ]

    for config in configs:
        detector = RegimeDetector(symbol="BTCUSDT")

        for name, active, confidence, value in config:
            detector.add_feature(name, active=active, value=value, confidence=confidence, timestamp_ms=100000)

        state = detector.compute_regime()

        # Должен быть один из валидных regime
        assert state.regime in valid_regimes


@given(
    feature_count=st.integers(min_value=1, max_value=20),
)
def test_regime_feature_importance_sorted(feature_count):
    """Feature importance отсортирован по убыванию."""
    detector = RegimeDetector(symbol="BTCUSDT")

    # Добавить features с разными confidence
    for i in range(feature_count):
        confidence = (i % 10) / 10.0  # 0.0, 0.1, ..., 0.9
        detector.add_feature(f"feat_{i}", active=True, confidence=confidence, timestamp_ms=100000)

    analysis = detector.analyze()
    importance_list = analysis.feature_importance

    # Проверить сортировку
    for i in range(len(importance_list) - 1):
        assert importance_list[i].importance >= importance_list[i + 1].importance
