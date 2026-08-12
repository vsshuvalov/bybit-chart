"""
Order и Execution state machine для simulator/live trading (Roadmap Этап 8).

Архитектура:
- Order: состояние одного ордера (NEW → FILLED/CANCELLED)
- Position: текущая позиция (qty, avg_price, pnl)
- ExecutionAdapter: abstract interface для simulator/live execution
- ExecutionEngine: управляет orders и positions

State transitions:
    NEW → PENDING_NEW → ACTIVE → FILLED
                               → CANCELLED
                               → REJECTED
                               → PARTIAL_FILLED → FILLED
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable
from decimal import Decimal


class OrderSide(str, Enum):
    """Order side."""
    BUY = "Buy"
    SELL = "Sell"


class OrderType(str, Enum):
    """Order type."""
    MARKET = "Market"
    LIMIT = "Limit"


class TimeInForce(str, Enum):
    """Time in force."""
    GTC = "GoodTillCancel"  # остаётся пока не filled/cancelled
    IOC = "ImmediateOrCancel"  # fill immediately или cancel
    FOK = "FillOrKill"  # fill полностью сразу или cancel


class OrderStatus(str, Enum):
    """Order status."""
    NEW = "New"  # создан, но ещё не отправлен
    PENDING_NEW = "PendingNew"  # отправлен, ждём подтверждения
    ACTIVE = "Active"  # активен в orderbook (limit orders)
    PARTIAL_FILLED = "PartiallyFilled"  # частично заполнен
    FILLED = "Filled"  # полностью заполнен
    CANCELLED = "Cancelled"  # отменён
    REJECTED = "Rejected"  # отклонён exchange
    PENDING_CANCEL = "PendingCancel"  # ждём подтверждения cancel


class PositionSide(str, Enum):
    """Position side."""
    LONG = "Long"
    SHORT = "Short"
    NONE = "None"


class RejectReason(str, Enum):
    """Reject reason codes."""
    INSUFFICIENT_BALANCE = "InsufficientBalance"
    INVALID_PRICE = "InvalidPrice"
    INVALID_QTY = "InvalidQuantity"
    RISK_LIMIT = "RiskLimit"
    DUPLICATE_ORDER_ID = "DuplicateOrderId"
    UNKNOWN = "Unknown"


@dataclass
class Order:
    """Order state."""

    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    qty: Decimal
    price: Optional[Decimal] = None  # None for market orders
    time_in_force: TimeInForce = TimeInForce.GTC

    status: OrderStatus = OrderStatus.NEW
    filled_qty: Decimal = Decimal(0)
    avg_fill_price: Optional[Decimal] = None

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    submitted_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None

    # Stop loss / Take profit
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None

    # Metadata
    reject_reason: Optional[RejectReason] = None
    client_order_id: Optional[str] = None

    def remaining_qty(self) -> Decimal:
        """Remaining unfilled quantity."""
        return self.qty - self.filled_qty

    def is_terminal(self) -> bool:
        """Check if order is in terminal state (no more updates expected)."""
        return self.status in [
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        ]

    def is_active(self) -> bool:
        """Check if order is active (can be filled)."""
        return self.status in [
            OrderStatus.ACTIVE,
            OrderStatus.PARTIAL_FILLED,
        ]


@dataclass
class Fill:
    """Fill event (partial or full)."""

    fill_id: str
    order_id: str
    symbol: str
    side: OrderSide
    qty: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    timestamp: datetime
    is_maker: bool  # maker or taker fill


@dataclass
class Position:
    """Position state."""

    symbol: str
    side: PositionSide
    qty: Decimal  # положительное для long/short
    avg_entry_price: Decimal

    # PNL
    realized_pnl: Decimal = Decimal(0)
    unrealized_pnl: Decimal = Decimal(0)

    # Fees
    total_fees: Decimal = Decimal(0)

    # Timestamps
    opened_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def update_unrealized_pnl(self, mark_price: Decimal):
        """Update unrealized PNL based on current mark price."""
        if self.side == PositionSide.NONE or self.qty == 0:
            self.unrealized_pnl = Decimal(0)
            return

        pnl_per_contract = mark_price - self.avg_entry_price
        if self.side == PositionSide.SHORT:
            pnl_per_contract = -pnl_per_contract

        self.unrealized_pnl = pnl_per_contract * self.qty

    def total_pnl(self) -> Decimal:
        """Total PNL (realized + unrealized - fees)."""
        return self.realized_pnl + self.unrealized_pnl - self.total_fees


@dataclass
class OrderUpdate:
    """Order update event."""

    order_id: str
    status: OrderStatus
    filled_qty: Decimal
    avg_fill_price: Optional[Decimal]
    timestamp: datetime
    reject_reason: Optional[RejectReason] = None


# Callbacks
OnOrderUpdateCallback = Callable[[OrderUpdate], None]
OnFillCallback = Callable[[Fill], None]
OnRejectCallback = Callable[[Order, RejectReason], None]


class ExecutionAdapter:
    """Abstract interface для execution (simulator или live)."""

    def submit_order(self, order: Order) -> str:
        """
        Submit order to exchange/simulator.
        Returns order_id.
        """
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel order.
        Returns True if cancel request successful.
        """
        raise NotImplementedError

    def get_position(self, symbol: str) -> Position:
        """Get current position for symbol."""
        raise NotImplementedError

    def get_mark_price(self, symbol: str) -> Decimal:
        """Get current mark price."""
        raise NotImplementedError

    def register_callbacks(
        self,
        on_order_update: OnOrderUpdateCallback,
        on_fill: OnFillCallback,
        on_reject: OnRejectCallback,
    ):
        """Register callbacks for order/fill events."""
        raise NotImplementedError


class ExecutionEngine:
    """
    Manages orders и positions.
    Works with ExecutionAdapter для actual execution.
    """

    def __init__(self, adapter: ExecutionAdapter):
        self.adapter = adapter
        self.orders: dict[str, Order] = {}
        self.positions: dict[str, Position] = {}

        # Register callbacks
        self.adapter.register_callbacks(
            on_order_update=self._on_order_update,
            on_fill=self._on_fill,
            on_reject=self._on_reject,
        )

    def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        qty: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[Decimal] = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
    ) -> Order:
        """Submit new order."""

        order = Order(
            order_id="",  # will be assigned by adapter
            symbol=symbol,
            side=side,
            order_type=order_type,
            qty=qty,
            price=price,
            time_in_force=time_in_force,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        order.status = OrderStatus.PENDING_NEW
        order.submitted_at = datetime.now()

        order_id = self.adapter.submit_order(order)
        order.order_id = order_id

        # Сохраняем order сразу после получения order_id.
        # Примечание: adapter может синхронно вызвать fill callback внутри submit_order
        # (simulator). В этом случае engine._on_fill получит fill с order_id="sim_N"
        # но orders ещё не содержит этот id. Workaround: принимаем pending fills post-hoc.
        self.orders[order_id] = order

        # Replay any fills that arrived during submit (simulator pattern)
        if order_id in self.adapter._pending_fills_buffer if hasattr(self.adapter, '_pending_fills_buffer') else False:
            for fill in self.adapter._pending_fills_buffer.pop(order_id, []):
                self._on_fill(fill)

        return order

    def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        order = self.orders.get(order_id)
        if not order:
            return False

        if order.is_terminal():
            return False

        order.status = OrderStatus.PENDING_CANCEL
        order.updated_at = datetime.now()

        return self.adapter.cancel_order(order_id)

    def get_position(self, symbol: str) -> Position:
        """Get current position."""
        if symbol not in self.positions:
            self.positions[symbol] = Position(
                symbol=symbol,
                side=PositionSide.NONE,
                qty=Decimal(0),
                avg_entry_price=Decimal(0),
            )

        return self.positions[symbol]

    def _on_order_update(self, update: OrderUpdate):
        """Handle order update from adapter."""
        order = self.orders.get(update.order_id)
        if not order:
            return

        order.status = update.status
        order.filled_qty = update.filled_qty
        order.avg_fill_price = update.avg_fill_price
        order.updated_at = update.timestamp
        order.reject_reason = update.reject_reason

        if order.status == OrderStatus.FILLED:
            order.filled_at = update.timestamp

    def _on_fill(self, fill: Fill):
        """Handle fill event.

        Note: fill may arrive synchronously during adapter.submit_order (simulator
        pattern), before the order is stored in self.orders. Position update
        only needs fill fields — it does not require the order object.
        """
        # Update position unconditionally — _update_position only uses fill fields.
        position = self.get_position(fill.symbol)
        self._update_position(position, fill)

        # Update order state if already registered (async / post-submit path).
        order = self.orders.get(fill.order_id)
        if order:
            order.filled_qty = fill.qty if order.filled_qty == Decimal(0) else order.filled_qty
            order.avg_fill_price = fill.price

    def _on_reject(self, order: Order, reason: RejectReason):
        """Handle order rejection."""
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason
        order.updated_at = datetime.now()

    def _update_position(self, position: Position, fill: Fill):
        """Update position based on fill."""
        fill_qty = fill.qty
        fill_price = fill.price

        # Same side as position → increase
        if fill.side == OrderSide.BUY:
            if position.side == PositionSide.LONG or position.side == PositionSide.NONE:
                # Increase long
                total_qty = position.qty + fill_qty
                weighted_price = (
                    position.avg_entry_price * position.qty + fill_price * fill_qty
                ) / total_qty

                position.side = PositionSide.LONG
                position.qty = total_qty
                position.avg_entry_price = weighted_price

            elif position.side == PositionSide.SHORT:
                # Reduce short (close partially or fully)
                if fill_qty >= position.qty:
                    # Close short completely
                    pnl = (position.avg_entry_price - fill_price) * position.qty
                    position.realized_pnl += pnl

                    remaining = fill_qty - position.qty
                    if remaining > 0:
                        # Flip to long
                        position.side = PositionSide.LONG
                        position.qty = remaining
                        position.avg_entry_price = fill_price
                    else:
                        # Flat
                        position.side = PositionSide.NONE
                        position.qty = Decimal(0)
                else:
                    # Partial close
                    pnl = (position.avg_entry_price - fill_price) * fill_qty
                    position.realized_pnl += pnl
                    position.qty -= fill_qty

        elif fill.side == OrderSide.SELL:
            if position.side == PositionSide.SHORT or position.side == PositionSide.NONE:
                # Increase short
                total_qty = position.qty + fill_qty
                weighted_price = (
                    position.avg_entry_price * position.qty + fill_price * fill_qty
                ) / total_qty

                position.side = PositionSide.SHORT
                position.qty = total_qty
                position.avg_entry_price = weighted_price

            elif position.side == PositionSide.LONG:
                # Reduce long (close partially or fully)
                if fill_qty >= position.qty:
                    # Close long completely
                    pnl = (fill_price - position.avg_entry_price) * position.qty
                    position.realized_pnl += pnl

                    remaining = fill_qty - position.qty
                    if remaining > 0:
                        # Flip to short
                        position.side = PositionSide.SHORT
                        position.qty = remaining
                        position.avg_entry_price = fill_price
                    else:
                        # Flat
                        position.side = PositionSide.NONE
                        position.qty = Decimal(0)
                else:
                    # Partial close
                    pnl = (fill_price - position.avg_entry_price) * fill_qty
                    position.realized_pnl += pnl
                    position.qty -= fill_qty

        # Add fees
        position.total_fees += fill.fee
        position.updated_at = datetime.now()
