"""
Paper Trading Engine для live simulation (Roadmap §14 extended).

Источник: Roadmap §14 (paper trading mode, live simulation)

Архитектура:
- PaperTradingEngine — симуляция торговли на real-time данных
- OrderManager — управление активными ордерами
- Real-time execution через WebSocket feed
- Position tracking в реальном времени
- Trade journal для анализа

Use Cases:
- Test strategies risk-free на live data
- Practice trading без реального капитала
- Strategy validation перед live trading
- Performance tracking в реальных условиях

MVP: Market orders на real-time prices
Future: Limit orders, stop loss, advanced execution
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from packages.backtesting.strategy import (
    Order,
    OrderSide,
    OrderType,
    Position,
    PositionSide,
    Trade,
)

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    """Статус ордера."""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class PaperOrder(Order):
    """Ордер для paper trading (extends базовый Order).

    Roadmap §14: добавляет status, filled_quantity, timestamps.
    """
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    filled_at: datetime | None = None

    def update_fill(self, quantity: float, price: float):
        """Обновить информацию о заполнении ордера.

        Args:
            quantity: заполненное количество
            price: цена исполнения
        """
        self.filled_quantity += quantity

        # Update average fill price
        if self.filled_quantity > 0:
            total_value = self.average_fill_price * (self.filled_quantity - quantity) + price * quantity
            self.average_fill_price = total_value / self.filled_quantity

        # Update status
        if self.filled_quantity >= self.quantity:
            self.status = OrderStatus.FILLED
            self.filled_at = datetime.utcnow()
        elif self.filled_quantity > 0:
            self.status = OrderStatus.PARTIALLY_FILLED

        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        base_dict = super().to_dict()
        base_dict.update({
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "average_fill_price": self.average_fill_price,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
        })
        return base_dict


@dataclass
class PaperAccount:
    """Paper trading account state.

    Roadmap §14: виртуальный счёт для paper trading.
    """
    initial_balance: float
    balance: float
    equity: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    total_commission: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)  # symbol → Position
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    def update_equity(self, symbol: str, current_price: float):
        """Обновить equity на основе текущих позиций.

        Args:
            symbol: символ для обновления
            current_price: текущая рыночная цена
        """
        if symbol in self.positions:
            position = self.positions[symbol]
            position.update_unrealized_pnl(current_price)

        # Calculate total unrealized PnL
        self.unrealized_pnl = sum(pos.unrealized_pnl for pos in self.positions.values())
        self.equity = self.balance + self.unrealized_pnl

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "initial_balance": self.initial_balance,
            "balance": self.balance,
            "equity": self.equity,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "total_commission": self.total_commission,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.winning_trades / self.total_trades if self.total_trades > 0 else 0.0,
            "positions": {symbol: pos.to_dict() for symbol, pos in self.positions.items()},
        }


class PaperTradingEngine:
    """Paper trading engine для live simulation.

    Roadmap §14: симуляция торговли на real-time данных без риска.
    """

    def __init__(
        self,
        initial_balance: float = 100000.0,
        commission_rate: float = 0.0006,
        slippage_rate: float = 0.0001,
    ):
        """Initialize paper trading engine.

        Args:
            initial_balance: начальный капитал
            commission_rate: комиссия (default 0.06%)
            slippage_rate: проскальзывание (default 0.01%)
        """
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate

        # Account state
        self.account = PaperAccount(
            initial_balance=initial_balance,
            balance=initial_balance,
            equity=initial_balance,
        )

        # Order tracking
        self.active_orders: dict[str, PaperOrder] = {}  # order_id → PaperOrder
        self.order_history: list[PaperOrder] = []

        # Trade history
        self.trades: list[Trade] = []
        self.trade_id_counter = 0

    def submit_order(self, order: Order) -> PaperOrder:
        """Отправить ордер в paper trading engine.

        Args:
            order: Order для исполнения

        Returns:
            PaperOrder с tracking info
        """
        paper_order = PaperOrder(
            order_id=order.order_id,
            timestamp_us=order.timestamp_us,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            price=order.price,
            status=OrderStatus.PENDING,
        )

        self.active_orders[order.order_id] = paper_order
        logger.info(f"Order submitted: {order.order_id}, {order.side.value} {order.quantity} {order.symbol}")

        return paper_order

    def process_market_data(self, symbol: str, price: float, timestamp_us: int):
        """Обработать market data и исполнить ордера.

        Args:
            symbol: торговый инструмент
            price: текущая рыночная цена
            timestamp_us: timestamp данных
        """
        # Execute pending market orders
        for order_id, order in list(self.active_orders.items()):
            if order.symbol == symbol and order.order_type == OrderType.MARKET:
                self._execute_order(order, price, timestamp_us)

        # Update positions unrealized PnL
        self.account.update_equity(symbol, price)

    def _execute_order(self, order: PaperOrder, market_price: float, timestamp_us: int):
        """Исполнить ордер по market price.

        Args:
            order: ордер для исполнения
            market_price: текущая рыночная цена
            timestamp_us: timestamp исполнения
        """
        # Apply slippage
        if order.side == OrderSide.BUY:
            execution_price = market_price * (1 + self.slippage_rate)
        else:
            execution_price = market_price * (1 - self.slippage_rate)

        # Calculate commission
        trade_value = order.quantity * execution_price
        commission = trade_value * self.commission_rate

        # Update order
        order.update_fill(order.quantity, execution_price)

        # Remove from active orders
        if order.order_id in self.active_orders:
            del self.active_orders[order.order_id]

        # Add to history
        self.order_history.append(order)

        # Create trade record
        self.trade_id_counter += 1
        trade = Trade(
            trade_id=f"paper_{self.trade_id_counter}",
            order_id=order.order_id,
            timestamp_us=timestamp_us,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=execution_price,
            commission=commission,
        )

        self.trades.append(trade)
        self.account.total_commission += commission

        # Update position
        self._update_position(trade)

        logger.info(
            f"Order executed: {order.order_id}, {order.side.value} {order.quantity} @ {execution_price:.2f}, "
            f"commission={commission:.2f}"
        )

    def _update_position(self, trade: Trade):
        """Обновить позицию после исполнения trade.

        Args:
            trade: исполненная сделка
        """
        symbol = trade.symbol

        if symbol not in self.account.positions:
            self.account.positions[symbol] = Position(symbol=symbol, side=PositionSide.FLAT)

        position = self.account.positions[symbol]

        if trade.side == OrderSide.BUY:
            self._process_buy(position, trade)
        else:
            self._process_sell(position, trade)

    def _process_buy(self, position: Position, trade: Trade):
        """Обработать BUY trade."""
        cost = trade.value + trade.commission

        if position.side == PositionSide.FLAT:
            # Open LONG
            if self.account.balance >= cost:
                self.account.balance -= cost
                position.side = PositionSide.LONG
                position.quantity = trade.quantity
                position.entry_price = trade.price
                position.entry_timestamp_us = trade.timestamp_us
            else:
                logger.warning(f"Insufficient balance: required={cost}, available={self.account.balance}")

        elif position.side == PositionSide.SHORT:
            # Close SHORT
            realized_pnl = (position.entry_price - trade.price) * trade.quantity - trade.commission
            self.account.balance += position.entry_price * position.quantity
            self.account.balance -= trade.value + trade.commission
            self.account.realized_pnl += realized_pnl

            # Track win/loss
            self.account.total_trades += 1
            if realized_pnl > 0:
                self.account.winning_trades += 1
            else:
                self.account.losing_trades += 1

            position.side = PositionSide.FLAT
            position.quantity = 0.0

        elif position.side == PositionSide.LONG:
            # Add to LONG
            total_cost = position.quantity * position.entry_price + cost
            position.quantity += trade.quantity
            position.entry_price = total_cost / position.quantity

    def _process_sell(self, position: Position, trade: Trade):
        """Обработать SELL trade."""
        if position.side == PositionSide.FLAT:
            # Open SHORT
            proceeds = trade.value - trade.commission
            self.account.balance += proceeds
            position.side = PositionSide.SHORT
            position.quantity = trade.quantity
            position.entry_price = trade.price
            position.entry_timestamp_us = trade.timestamp_us

        elif position.side == PositionSide.LONG:
            # Close LONG
            proceeds = trade.value - trade.commission
            self.account.balance += proceeds
            realized_pnl = (trade.price - position.entry_price) * trade.quantity - trade.commission
            self.account.realized_pnl += realized_pnl

            # Track win/loss
            self.account.total_trades += 1
            if realized_pnl > 0:
                self.account.winning_trades += 1
            else:
                self.account.losing_trades += 1

            position.side = PositionSide.FLAT
            position.quantity = 0.0

        elif position.side == PositionSide.SHORT:
            # Add to SHORT
            total_proceeds = position.quantity * position.entry_price + trade.value - trade.commission
            position.quantity += trade.quantity
            position.entry_price = total_proceeds / position.quantity

    def cancel_order(self, order_id: str) -> bool:
        """Отменить активный ордер.

        Args:
            order_id: ID ордера для отмены

        Returns:
            True если успешно отменён
        """
        if order_id in self.active_orders:
            order = self.active_orders[order_id]
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.utcnow()

            del self.active_orders[order_id]
            self.order_history.append(order)

            logger.info(f"Order cancelled: {order_id}")
            return True

        return False

    def get_account_state(self) -> dict[str, Any]:
        """Получить текущее состояние account.

        Returns:
            Account state dict
        """
        return self.account.to_dict()

    def get_active_orders(self, symbol: str | None = None) -> list[PaperOrder]:
        """Получить активные ордера.

        Args:
            symbol: фильтр по символу (optional)

        Returns:
            Список активных ордеров
        """
        orders = list(self.active_orders.values())

        if symbol:
            orders = [o for o in orders if o.symbol == symbol]

        return orders

    def get_trade_history(self, symbol: str | None = None, limit: int = 100) -> list[Trade]:
        """Получить историю сделок.

        Args:
            symbol: фильтр по символу (optional)
            limit: максимум записей

        Returns:
            Список сделок (newest first)
        """
        trades = self.trades

        if symbol:
            trades = [t for t in trades if t.symbol == symbol]

        return list(reversed(trades[-limit:]))
