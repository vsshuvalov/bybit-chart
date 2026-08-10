"""
Backtesting Framework для strategy testing (Roadmap §14).

Источник: Roadmap §14 (backtesting, strategy evaluation)

Архитектура:
- Strategy interface — базовый класс для стратегий
- Backtest engine — walk-forward через исторические данные
- Performance metrics — Sharpe, drawdown, win rate
- Trade journal — история всех сделок

Use Cases:
- Strategy development and testing
- Parameter optimization
- Risk management validation
- Performance analysis

MVP: Simple backtesting на OHLC + analytics
Future: Advanced features (slippage, commissions, portfolio)
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class OrderSide(Enum):
    """Сторона ордера."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Тип ордера."""
    MARKET = "market"
    LIMIT = "limit"


class PositionSide(Enum):
    """Сторона позиции."""
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass
class Order:
    """Ордер для исполнения."""
    order_id: str
    timestamp_us: int
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None  # для LIMIT orders

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "order_id": self.order_id,
            "timestamp_us": self.timestamp_us,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "price": self.price,
        }


@dataclass
class Trade:
    """Исполненная сделка."""
    trade_id: str
    order_id: str
    timestamp_us: int
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    commission: float = 0.0

    @property
    def value(self) -> float:
        """Стоимость сделки."""
        return self.quantity * self.price

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "timestamp_us": self.timestamp_us,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": self.price,
            "commission": self.commission,
            "value": self.value,
        }


@dataclass
class Position:
    """Текущая позиция."""
    symbol: str
    side: PositionSide = PositionSide.FLAT
    quantity: float = 0.0
    entry_price: float = 0.0
    entry_timestamp_us: int = 0
    unrealized_pnl: float = 0.0

    def update_unrealized_pnl(self, current_price: float):
        """Обновить unrealized PnL.

        Args:
            current_price: текущая рыночная цена
        """
        if self.side == PositionSide.FLAT:
            self.unrealized_pnl = 0.0
        elif self.side == PositionSide.LONG:
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
        elif self.side == PositionSide.SHORT:
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "entry_timestamp_us": self.entry_timestamp_us,
            "unrealized_pnl": self.unrealized_pnl,
        }


@dataclass
class StrategyContext:
    """Контекст для стратегии (данные и состояние).

    Roadmap §14: стратегия получает OHLC, analytics, position info.
    """
    timestamp_us: int
    symbol: str

    # Market data
    open: float
    high: float
    low: float
    close: float
    volume: float

    # Analytics (optional)
    delta: float | None = None
    cvd: float | None = None
    vwap: float | None = None

    # Position info
    position: Position | None = None

    # Account info
    cash: float = 0.0
    equity: float = 0.0


class Strategy(ABC):
    """Базовый класс для торговых стратегий.

    Roadmap §14: стратегия реализует on_bar() для генерации сигналов.
    """

    def __init__(self, symbol: str):
        """Initialize strategy.

        Args:
            symbol: торговый инструмент (BTCUSDT, ETHUSDT, ...)
        """
        self.symbol = symbol
        self.name = self.__class__.__name__

    @abstractmethod
    def on_bar(self, context: StrategyContext) -> list[Order]:
        """Обработать новый bar и сгенерировать ордера.

        Args:
            context: текущий контекст (OHLC, analytics, position)

        Returns:
            Список ордеров для исполнения (может быть пустым)

        Roadmap §14: стратегия анализирует контекст и возвращает ордера.
        """
        pass

    def on_start(self):
        """Вызывается в начале backtesting."""
        pass

    def on_finish(self):
        """Вызывается в конце backtesting."""
        pass


class SimpleMovingAverageCrossStrategy(Strategy):
    """Пример стратегии: MA crossover.

    Entry:
    - Long: fast MA crosses above slow MA
    - Short: fast MA crosses below slow MA

    Exit:
    - Opposite signal
    """

    def __init__(
        self,
        symbol: str,
        fast_period: int = 10,
        slow_period: int = 20,
        position_size: float = 1.0,
    ):
        """Initialize MA crossover strategy.

        Args:
            symbol: торговый инструмент
            fast_period: период быстрой MA
            slow_period: период медленной MA
            position_size: размер позиции (в единицах инструмента)
        """
        super().__init__(symbol)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.position_size = position_size

        self.prices: list[float] = []
        self.fast_ma: float | None = None
        self.slow_ma: float | None = None
        self.prev_fast_ma: float | None = None
        self.prev_slow_ma: float | None = None

    def on_bar(self, context: StrategyContext) -> list[Order]:
        """Generate signals based on MA crossover."""
        self.prices.append(context.close)

        # Trim prices history
        if len(self.prices) > self.slow_period:
            self.prices = self.prices[-self.slow_period:]

        # Calculate MAs
        if len(self.prices) >= self.fast_period:
            self.fast_ma = sum(self.prices[-self.fast_period:]) / self.fast_period

        if len(self.prices) >= self.slow_period:
            self.slow_ma = sum(self.prices[-self.slow_period:]) / self.slow_period

        orders = []

        # Check crossover
        if (self.fast_ma is not None and self.slow_ma is not None and
            self.prev_fast_ma is not None and self.prev_slow_ma is not None):

            # Golden cross (fast crosses above slow) → LONG
            if self.prev_fast_ma <= self.prev_slow_ma and self.fast_ma > self.slow_ma:
                # Close SHORT if exists
                if context.position and context.position.side == PositionSide.SHORT:
                    orders.append(Order(
                        order_id=f"close_{context.timestamp_us}",
                        timestamp_us=context.timestamp_us,
                        symbol=self.symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=context.position.quantity,
                    ))

                # Open LONG
                orders.append(Order(
                    order_id=f"long_{context.timestamp_us}",
                    timestamp_us=context.timestamp_us,
                    symbol=self.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=self.position_size,
                ))

            # Death cross (fast crosses below slow) → SHORT
            elif self.prev_fast_ma >= self.prev_slow_ma and self.fast_ma < self.slow_ma:
                # Close LONG if exists
                if context.position and context.position.side == PositionSide.LONG:
                    orders.append(Order(
                        order_id=f"close_{context.timestamp_us}",
                        timestamp_us=context.timestamp_us,
                        symbol=self.symbol,
                        side=OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        quantity=context.position.quantity,
                    ))

                # Open SHORT
                orders.append(Order(
                    order_id=f"short_{context.timestamp_us}",
                    timestamp_us=context.timestamp_us,
                    symbol=self.symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=self.position_size,
                ))

        # Update prev MAs
        self.prev_fast_ma = self.fast_ma
        self.prev_slow_ma = self.slow_ma

        return orders
