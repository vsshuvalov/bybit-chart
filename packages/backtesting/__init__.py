"""
Backtesting Framework (Roadmap §14).

Modules:
- strategy: Strategy interface, базовые стратегии
- engine: BacktestEngine для strategy execution
"""

from packages.backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from packages.backtesting.strategy import (
    Order,
    OrderSide,
    OrderType,
    Position,
    PositionSide,
    SimpleMovingAverageCrossStrategy,
    Strategy,
    StrategyContext,
    Trade,
)

__all__ = [
    # Strategy
    "Strategy",
    "StrategyContext",
    "Order",
    "OrderSide",
    "OrderType",
    "Trade",
    "Position",
    "PositionSide",
    "SimpleMovingAverageCrossStrategy",
    # Engine
    "BacktestEngine",
    "BacktestConfig",
    "BacktestResult",
]
