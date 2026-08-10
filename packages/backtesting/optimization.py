"""
Parameter Optimization для strategy tuning (Roadmap §14 extended).

Источник: Roadmap §14 (parameter optimization, grid search)

Архитектура:
- ParameterOptimizer — grid search через parameter space
- OptimizationResult — результаты для каждой комбинации параметров
- Parallel execution для ускорения
- Multiple objective functions (Sharpe, return, drawdown)

Use Cases:
- Find optimal MA periods
- Tune indicator parameters
- Optimize position sizing
- Balance risk/reward

MVP: Grid search с single metric
Future: Genetic algorithms, Bayesian optimization
"""

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from packages.backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from packages.backtesting.strategy import Strategy

logger = logging.getLogger(__name__)


@dataclass
class ParameterSet:
    """Набор параметров для optimization.

    Roadmap §14: определяет parameter space для поиска.
    """
    name: str
    values: list[Any]

    def __len__(self) -> int:
        return len(self.values)


@dataclass
class OptimizationResult:
    """Результат optimization для одной комбинации параметров.

    Roadmap §14: содержит параметры и performance metrics.
    """
    parameters: dict[str, Any]
    backtest_result: BacktestResult
    objective_value: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "parameters": self.parameters,
            "total_return_pct": self.backtest_result.total_return_pct,
            "sharpe_ratio": self.backtest_result.sharpe_ratio,
            "max_drawdown_pct": self.backtest_result.max_drawdown_pct,
            "win_rate": self.backtest_result.win_rate,
            "total_trades": self.backtest_result.total_trades,
            "objective_value": self.objective_value,
        }


@dataclass
class OptimizationSummary:
    """Сводка результатов optimization.

    Roadmap §14: лучшие параметры и статистика.
    """
    best_parameters: dict[str, Any]
    best_objective: float
    total_combinations: int
    results: list[OptimizationResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "best_parameters": self.best_parameters,
            "best_objective": self.best_objective,
            "total_combinations": self.total_combinations,
            "top_10_results": [r.to_dict() for r in self.results[:10]],
        }


class ParameterOptimizer:
    """Parameter optimization engine для strategy tuning.

    Roadmap §14: grid search через parameter combinations.
    """

    def __init__(
        self,
        strategy_class: type[Strategy],
        bars: list[dict[str, Any]],
        config: BacktestConfig | None = None,
        objective: str = "sharpe_ratio",
    ):
        """Initialize optimizer.

        Args:
            strategy_class: Strategy class для optimization
            bars: исторические данные (OHLC bars)
            config: backtest configuration
            objective: objective function ("sharpe_ratio", "total_return", "win_rate")
        """
        self.strategy_class = strategy_class
        self.bars = bars
        self.config = config or BacktestConfig()
        self.objective = objective

    def optimize(
        self,
        parameter_sets: list[ParameterSet],
        max_workers: int | None = None,
    ) -> OptimizationSummary:
        """Запустить grid search optimization.

        Args:
            parameter_sets: список ParameterSet для optimization
            max_workers: количество параллельных workers (default: CPU count)

        Returns:
            OptimizationSummary с лучшими параметрами

        Roadmap §14: grid search через все комбинации параметров.
        """
        # Generate all parameter combinations
        combinations = self._generate_combinations(parameter_sets)

        logger.info(
            f"Starting optimization: {len(combinations)} combinations, "
            f"objective={self.objective}"
        )

        results = []

        # Run backtests for each combination (sequential for now)
        for i, params in enumerate(combinations):
            try:
                result = self._run_single_backtest(params)
                results.append(result)

                if (i + 1) % 10 == 0:
                    logger.info(f"Progress: {i + 1}/{len(combinations)} combinations completed")

            except Exception as exc:
                logger.error(f"Error in backtest with params {params}: {exc}")

        # Sort by objective value (descending)
        results.sort(key=lambda r: r.objective_value, reverse=True)

        # Create summary
        best = results[0] if results else None

        summary = OptimizationSummary(
            best_parameters=best.parameters if best else {},
            best_objective=best.objective_value if best else 0.0,
            total_combinations=len(combinations),
            results=results,
        )

        logger.info(
            f"Optimization complete: best {self.objective} = {summary.best_objective:.4f}, "
            f"parameters = {summary.best_parameters}"
        )

        return summary

    def _generate_combinations(
        self,
        parameter_sets: list[ParameterSet],
    ) -> list[dict[str, Any]]:
        """Генерировать все комбинации параметров.

        Args:
            parameter_sets: список ParameterSet

        Returns:
            Список dict с комбинациями параметров
        """
        if not parameter_sets:
            return [{}]

        # Recursive generation
        def _generate(sets, index=0):
            if index >= len(sets):
                return [{}]

            param_set = sets[index]
            rest_combinations = _generate(sets, index + 1)

            combinations = []
            for value in param_set.values:
                for rest in rest_combinations:
                    combo = {param_set.name: value}
                    combo.update(rest)
                    combinations.append(combo)

            return combinations

        return _generate(parameter_sets)

    def _run_single_backtest(self, parameters: dict[str, Any]) -> OptimizationResult:
        """Запустить один backtest с заданными параметрами.

        Args:
            parameters: dict параметров для стратегии

        Returns:
            OptimizationResult
        """
        # Create strategy instance with parameters
        # Assumes strategy constructor accepts symbol + kwargs
        symbol = parameters.get("symbol", "BTCUSDT")
        strategy = self.strategy_class(symbol, **parameters)

        # Run backtest
        engine = BacktestEngine(self.config)
        backtest_result = engine.run(strategy, self.bars)

        # Calculate objective value
        objective_value = self._calculate_objective(backtest_result)

        return OptimizationResult(
            parameters=parameters,
            backtest_result=backtest_result,
            objective_value=objective_value,
        )

    def _calculate_objective(self, result: BacktestResult) -> float:
        """Рассчитать objective value.

        Args:
            result: BacktestResult

        Returns:
            Objective value (higher is better)
        """
        if self.objective == "sharpe_ratio":
            return result.sharpe_ratio

        elif self.objective == "total_return":
            return result.total_return_pct

        elif self.objective == "win_rate":
            return result.win_rate

        elif self.objective == "profit_factor":
            return result.profit_factor

        elif self.objective == "calmar_ratio":
            # Return / Max Drawdown
            if result.max_drawdown_pct > 0:
                return result.total_return_pct / result.max_drawdown_pct
            return 0.0

        else:
            logger.warning(f"Unknown objective: {self.objective}, using sharpe_ratio")
            return result.sharpe_ratio


def optimize_ma_crossover(
    bars: list[dict[str, Any]],
    fast_periods: list[int] = [5, 10, 15, 20],
    slow_periods: list[int] = [20, 30, 40, 50],
    objective: str = "sharpe_ratio",
) -> OptimizationSummary:
    """Helper function для MA crossover optimization.

    Args:
        bars: исторические данные
        fast_periods: список fast MA periods
        slow_periods: список slow MA periods
        objective: objective function

    Returns:
        OptimizationSummary

    Example:
        >>> bars = load_historical_data()
        >>> summary = optimize_ma_crossover(bars, fast_periods=[5,10,15], slow_periods=[20,30,40])
        >>> print(summary.best_parameters)
        {'fast_period': 10, 'slow_period': 30}
    """
    from packages.backtesting.strategy import SimpleMovingAverageCrossStrategy

    parameter_sets = [
        ParameterSet("fast_period", fast_periods),
        ParameterSet("slow_period", slow_periods),
    ]

    optimizer = ParameterOptimizer(
        strategy_class=SimpleMovingAverageCrossStrategy,
        bars=bars,
        objective=objective,
    )

    return optimizer.optimize(parameter_sets)
