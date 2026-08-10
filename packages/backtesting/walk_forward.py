"""
Walk-Forward Analysis для strategy validation (Roadmap §14 extended).

Источник: Roadmap §14 (walk-forward, in-sample/out-of-sample validation)

Архитектура:
- WalkForwardAnalyzer — in-sample optimization + out-of-sample testing
- Rolling window через исторические данные
- Prevents overfitting через out-of-sample validation
- Realistic performance estimation

Use Cases:
- Validate strategy robustness
- Detect overfitting
- Estimate real-world performance
- Time-series cross-validation

MVP: Single forward walk
Future: Anchored/rolling windows, re-optimization frequency
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from packages.backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from packages.backtesting.optimization import ParameterOptimizer, ParameterSet
from packages.backtesting.strategy import Strategy

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardPeriod:
    """Один период walk-forward analysis.

    Roadmap §14: in-sample (optimization) + out-of-sample (validation).
    """
    period_id: int
    in_sample_start: int
    in_sample_end: int
    out_sample_start: int
    out_sample_end: int
    best_parameters: dict[str, Any]
    in_sample_result: BacktestResult | None = None
    out_sample_result: BacktestResult | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "period_id": self.period_id,
            "in_sample_bars": self.in_sample_end - self.in_sample_start,
            "out_sample_bars": self.out_sample_end - self.out_sample_start,
            "best_parameters": self.best_parameters,
            "in_sample_return": self.in_sample_result.total_return_pct if self.in_sample_result else None,
            "out_sample_return": self.out_sample_result.total_return_pct if self.out_sample_result else None,
            "in_sample_sharpe": self.in_sample_result.sharpe_ratio if self.in_sample_result else None,
            "out_sample_sharpe": self.out_sample_result.sharpe_ratio if self.out_sample_result else None,
        }


@dataclass
class WalkForwardSummary:
    """Сводка walk-forward analysis.

    Roadmap §14: агрегированные результаты всех периодов.
    """
    total_periods: int
    in_sample_avg_return: float = 0.0
    out_sample_avg_return: float = 0.0
    in_sample_avg_sharpe: float = 0.0
    out_sample_avg_sharpe: float = 0.0
    efficiency_ratio: float = 0.0  # out_sample / in_sample performance
    periods: list[WalkForwardPeriod] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "total_periods": self.total_periods,
            "in_sample_avg_return": self.in_sample_avg_return,
            "out_sample_avg_return": self.out_sample_avg_return,
            "in_sample_avg_sharpe": self.in_sample_avg_sharpe,
            "out_sample_avg_sharpe": self.out_sample_avg_sharpe,
            "efficiency_ratio": self.efficiency_ratio,
            "periods": [p.to_dict() for p in self.periods],
        }


class WalkForwardAnalyzer:
    """Walk-forward analysis для strategy validation.

    Roadmap §14: in-sample optimization → out-of-sample testing.
    """

    def __init__(
        self,
        strategy_class: type[Strategy],
        bars: list[dict[str, Any]],
        config: BacktestConfig | None = None,
        objective: str = "sharpe_ratio",
    ):
        """Initialize walk-forward analyzer.

        Args:
            strategy_class: Strategy class для testing
            bars: полный dataset (исторические данные)
            config: backtest configuration
            objective: objective function для optimization
        """
        self.strategy_class = strategy_class
        self.bars = bars
        self.config = config or BacktestConfig()
        self.objective = objective

    def analyze(
        self,
        parameter_sets: list[ParameterSet],
        in_sample_ratio: float = 0.7,
        num_periods: int = 3,
    ) -> WalkForwardSummary:
        """Запустить walk-forward analysis.

        Args:
            parameter_sets: параметры для optimization
            in_sample_ratio: доля данных для optimization (0.7 = 70%)
            num_periods: количество периодов для анализа

        Returns:
            WalkForwardSummary с результатами

        Roadmap §14: разделяет данные на периоды, оптимизирует на in-sample,
        тестирует на out-of-sample.
        """
        logger.info(
            f"Starting walk-forward analysis: {num_periods} periods, "
            f"in_sample={in_sample_ratio * 100}%"
        )

        periods = []
        total_bars = len(self.bars)
        period_size = total_bars // num_periods

        for i in range(num_periods):
            period_start = i * period_size
            period_end = (i + 1) * period_size if i < num_periods - 1 else total_bars

            # Split in-sample / out-of-sample
            split_point = int(period_start + (period_end - period_start) * in_sample_ratio)

            in_sample_bars = self.bars[period_start:split_point]
            out_sample_bars = self.bars[split_point:period_end]

            logger.info(
                f"Period {i + 1}/{num_periods}: "
                f"in_sample={len(in_sample_bars)} bars, "
                f"out_sample={len(out_sample_bars)} bars"
            )

            # Optimize on in-sample
            optimizer = ParameterOptimizer(
                strategy_class=self.strategy_class,
                bars=in_sample_bars,
                config=self.config,
                objective=self.objective,
            )

            optimization_result = optimizer.optimize(parameter_sets)
            best_params = optimization_result.best_parameters

            # Get in-sample result
            in_sample_result = optimization_result.results[0].backtest_result if optimization_result.results else None

            # Test on out-of-sample
            strategy = self.strategy_class("BTCUSDT", **best_params)
            engine = BacktestEngine(self.config)
            out_sample_result = engine.run(strategy, out_sample_bars)

            period = WalkForwardPeriod(
                period_id=i + 1,
                in_sample_start=period_start,
                in_sample_end=split_point,
                out_sample_start=split_point,
                out_sample_end=period_end,
                best_parameters=best_params,
                in_sample_result=in_sample_result,
                out_sample_result=out_sample_result,
            )

            periods.append(period)

            logger.info(
                f"Period {i + 1} complete: "
                f"in_sample_return={in_sample_result.total_return_pct:.2f}%, "
                f"out_sample_return={out_sample_result.total_return_pct:.2f}%"
            )

        # Calculate summary statistics
        summary = self._calculate_summary(periods)

        logger.info(
            f"Walk-forward complete: "
            f"avg_out_sample_return={summary.out_sample_avg_return:.2f}%, "
            f"efficiency={summary.efficiency_ratio:.2f}"
        )

        return summary

    def _calculate_summary(self, periods: list[WalkForwardPeriod]) -> WalkForwardSummary:
        """Рассчитать summary statistics.

        Args:
            periods: список WalkForwardPeriod

        Returns:
            WalkForwardSummary
        """
        if not periods:
            return WalkForwardSummary(total_periods=0)

        in_sample_returns = [p.in_sample_result.total_return_pct for p in periods if p.in_sample_result]
        out_sample_returns = [p.out_sample_result.total_return_pct for p in periods if p.out_sample_result]

        in_sample_sharpes = [p.in_sample_result.sharpe_ratio for p in periods if p.in_sample_result]
        out_sample_sharpes = [p.out_sample_result.sharpe_ratio for p in periods if p.out_sample_result]

        in_sample_avg_return = sum(in_sample_returns) / len(in_sample_returns) if in_sample_returns else 0.0
        out_sample_avg_return = sum(out_sample_returns) / len(out_sample_returns) if out_sample_returns else 0.0

        in_sample_avg_sharpe = sum(in_sample_sharpes) / len(in_sample_sharpes) if in_sample_sharpes else 0.0
        out_sample_avg_sharpe = sum(out_sample_sharpes) / len(out_sample_sharpes) if out_sample_sharpes else 0.0

        # Efficiency ratio (out-of-sample / in-sample)
        efficiency_ratio = 0.0
        if in_sample_avg_return != 0:
            efficiency_ratio = out_sample_avg_return / in_sample_avg_return

        return WalkForwardSummary(
            total_periods=len(periods),
            in_sample_avg_return=in_sample_avg_return,
            out_sample_avg_return=out_sample_avg_return,
            in_sample_avg_sharpe=in_sample_avg_sharpe,
            out_sample_avg_sharpe=out_sample_avg_sharpe,
            efficiency_ratio=efficiency_ratio,
            periods=periods,
        )


def walk_forward_ma_crossover(
    bars: list[dict[str, Any]],
    fast_periods: list[int] = [5, 10, 15],
    slow_periods: list[int] = [20, 30, 40],
    num_periods: int = 3,
) -> WalkForwardSummary:
    """Helper function для MA crossover walk-forward analysis.

    Args:
        bars: исторические данные
        fast_periods: список fast MA periods
        slow_periods: список slow MA periods
        num_periods: количество walk-forward периодов

    Returns:
        WalkForwardSummary

    Example:
        >>> bars = load_historical_data()
        >>> summary = walk_forward_ma_crossover(bars, num_periods=5)
        >>> print(f"Efficiency: {summary.efficiency_ratio:.2f}")
    """
    from packages.backtesting.strategy import SimpleMovingAverageCrossStrategy

    parameter_sets = [
        ParameterSet("fast_period", fast_periods),
        ParameterSet("slow_period", slow_periods),
    ]

    analyzer = WalkForwardAnalyzer(
        strategy_class=SimpleMovingAverageCrossStrategy,
        bars=bars,
        objective="sharpe_ratio",
    )

    return analyzer.analyze(parameter_sets, num_periods=num_periods)
