"""
Тесты Advanced Backtesting (Parameter Optimization, Walk-Forward).

Проверяют: ParameterOptimizer, WalkForwardAnalyzer.
"""

import pytest

from packages.backtesting.optimization import (
    ParameterOptimizer,
    ParameterSet,
    optimize_ma_crossover,
)
from packages.backtesting.strategy import SimpleMovingAverageCrossStrategy
from packages.backtesting.walk_forward import (
    WalkForwardAnalyzer,
    walk_forward_ma_crossover,
)

pytestmark = pytest.mark.contract


# Test data generator
def generate_test_bars(count=100, trend="up"):
    """Generate synthetic bars для testing."""
    bars = []
    base_price = 100.0

    for i in range(count):
        if trend == "up":
            price = base_price + i * 0.5
        elif trend == "down":
            price = base_price - i * 0.5
        else:
            price = base_price + (i % 10) - 5

        bars.append({
            "timestamp_us": i * 60_000_000,
            "open": price - 0.5,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price,
            "volume": 1000.0,
        })

    return bars


class TestParameterOptimizer:
    """Тесты ParameterOptimizer."""

    def test_optimizer_initialization(self):
        """ParameterOptimizer инициализируется корректно."""
        bars = generate_test_bars(50)

        optimizer = ParameterOptimizer(
            strategy_class=SimpleMovingAverageCrossStrategy,
            bars=bars,
            objective="sharpe_ratio",
        )

        assert optimizer.strategy_class == SimpleMovingAverageCrossStrategy
        assert len(optimizer.bars) == 50
        assert optimizer.objective == "sharpe_ratio"

    def test_generate_combinations(self):
        """_generate_combinations() создаёт все комбинации."""
        bars = generate_test_bars(50)
        optimizer = ParameterOptimizer(SimpleMovingAverageCrossStrategy, bars)

        param_sets = [
            ParameterSet("fast_period", [5, 10]),
            ParameterSet("slow_period", [20, 30]),
        ]

        combinations = optimizer._generate_combinations(param_sets)

        # Should have 2 * 2 = 4 combinations
        assert len(combinations) == 4
        assert {"fast_period": 5, "slow_period": 20} in combinations
        assert {"fast_period": 10, "slow_period": 30} in combinations

    def test_optimize_runs(self):
        """optimize() выполняется без ошибок."""
        bars = generate_test_bars(50, trend="up")

        optimizer = ParameterOptimizer(
            strategy_class=SimpleMovingAverageCrossStrategy,
            bars=bars,
            objective="sharpe_ratio",
        )

        param_sets = [
            ParameterSet("fast_period", [5, 10]),
            ParameterSet("slow_period", [20, 25]),
        ]

        summary = optimizer.optimize(param_sets)

        assert summary.total_combinations == 4
        assert summary.best_parameters is not None
        assert "fast_period" in summary.best_parameters
        assert "slow_period" in summary.best_parameters

    def test_optimize_finds_best(self):
        """optimize() находит лучшие параметры."""
        bars = generate_test_bars(100, trend="up")

        optimizer = ParameterOptimizer(
            strategy_class=SimpleMovingAverageCrossStrategy,
            bars=bars,
            objective="total_return",
        )

        param_sets = [
            ParameterSet("fast_period", [5, 10, 15]),
            ParameterSet("slow_period", [20, 30]),
        ]

        summary = optimizer.optimize(param_sets)

        # Should find some parameters
        assert summary.best_parameters["fast_period"] in [5, 10, 15]
        assert summary.best_parameters["slow_period"] in [20, 30]
        assert len(summary.results) == 6  # 3 * 2

    def test_optimize_different_objectives(self):
        """optimize() работает с разными objective functions."""
        bars = generate_test_bars(50)

        for objective in ["sharpe_ratio", "total_return", "win_rate"]:
            optimizer = ParameterOptimizer(
                SimpleMovingAverageCrossStrategy,
                bars,
                objective=objective,
            )

            param_sets = [
                ParameterSet("fast_period", [5]),
                ParameterSet("slow_period", [20]),
            ]

            summary = optimizer.optimize(param_sets)
            assert summary.total_combinations == 1

    def test_optimize_ma_crossover_helper(self):
        """optimize_ma_crossover() helper function работает."""
        bars = generate_test_bars(100, trend="up")

        summary = optimize_ma_crossover(
            bars,
            fast_periods=[5, 10],
            slow_periods=[20, 30],
            objective="sharpe_ratio",
        )

        assert summary.total_combinations == 4
        assert summary.best_parameters is not None


class TestWalkForwardAnalyzer:
    """Тесты WalkForwardAnalyzer."""

    def test_analyzer_initialization(self):
        """WalkForwardAnalyzer инициализируется корректно."""
        bars = generate_test_bars(100)

        analyzer = WalkForwardAnalyzer(
            strategy_class=SimpleMovingAverageCrossStrategy,
            bars=bars,
            objective="sharpe_ratio",
        )

        assert analyzer.strategy_class == SimpleMovingAverageCrossStrategy
        assert len(analyzer.bars) == 100

    def test_analyze_runs(self):
        """analyze() выполняется без ошибок."""
        bars = generate_test_bars(100, trend="up")

        analyzer = WalkForwardAnalyzer(
            strategy_class=SimpleMovingAverageCrossStrategy,
            bars=bars,
        )

        param_sets = [
            ParameterSet("fast_period", [5, 10]),
            ParameterSet("slow_period", [20]),
        ]

        summary = analyzer.analyze(param_sets, num_periods=2)

        assert summary.total_periods == 2
        assert len(summary.periods) == 2

    def test_analyze_splits_data(self):
        """analyze() корректно разделяет данные на in-sample/out-sample."""
        bars = generate_test_bars(100)

        analyzer = WalkForwardAnalyzer(
            SimpleMovingAverageCrossStrategy,
            bars,
        )

        param_sets = [
            ParameterSet("fast_period", [5]),
            ParameterSet("slow_period", [20]),
        ]

        summary = analyzer.analyze(param_sets, in_sample_ratio=0.7, num_periods=2)

        # Check first period
        period = summary.periods[0]
        in_sample_size = period.in_sample_end - period.in_sample_start
        out_sample_size = period.out_sample_end - period.out_sample_start

        # Should be roughly 70/30 split
        total_size = in_sample_size + out_sample_size
        ratio = in_sample_size / total_size
        assert 0.6 < ratio < 0.8  # Allow some rounding

    def test_analyze_calculates_efficiency(self):
        """analyze() рассчитывает efficiency ratio."""
        bars = generate_test_bars(100, trend="up")

        analyzer = WalkForwardAnalyzer(
            SimpleMovingAverageCrossStrategy,
            bars,
        )

        param_sets = [
            ParameterSet("fast_period", [5]),
            ParameterSet("slow_period", [20]),
        ]

        summary = analyzer.analyze(param_sets, num_periods=2)

        # Efficiency should be calculated (out-of-sample / in-sample)
        assert hasattr(summary, 'efficiency_ratio')

    def test_walk_forward_ma_crossover_helper(self):
        """walk_forward_ma_crossover() helper function работает."""
        bars = generate_test_bars(150, trend="up")

        summary = walk_forward_ma_crossover(
            bars,
            fast_periods=[5, 10],
            slow_periods=[20],
            num_periods=2,
        )

        assert summary.total_periods == 2
        assert len(summary.periods) == 2

    def test_walk_forward_each_period_has_results(self):
        """Каждый период walk-forward имеет in-sample и out-sample результаты."""
        bars = generate_test_bars(120, trend="up")

        analyzer = WalkForwardAnalyzer(
            SimpleMovingAverageCrossStrategy,
            bars,
        )

        param_sets = [
            ParameterSet("fast_period", [5]),
            ParameterSet("slow_period", [20]),
        ]

        summary = analyzer.analyze(param_sets, num_periods=2)

        for period in summary.periods:
            assert period.in_sample_result is not None
            assert period.out_sample_result is not None
            assert period.best_parameters is not None
