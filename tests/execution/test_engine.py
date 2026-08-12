"""
Unit tests для ExecutionEngine (Roadmap Этап 8.1).

Tests:
- Order state transitions
- Position tracking (long/short/flat)
- PNL calculation (realized/unrealized)
- Fee accounting
"""

from datetime import datetime
from decimal import Decimal

import pytest

from packages.execution import (
    ExecutionEngine,
    ExecutionAdapter,
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    Fill,
    OrderUpdate,
    RejectReason,
    Position,
    PositionSide,
)


class MockAdapter(ExecutionAdapter):
    """Mock adapter для тестирования."""

    def __init__(self):
        self.orders = {}
        self.order_counter = 0
        self.on_order_update_cb = None
        self.on_fill_cb = None
        self.on_reject_cb = None

    def submit_order(self, order: Order) -> str:
        self.order_counter += 1
        order_id = f"order_{self.order_counter}"
        self.orders[order_id] = order
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders:
            # Simulate cancel confirmation
            update = OrderUpdate(
                order_id=order_id,
                status=OrderStatus.CANCELLED,
                filled_qty=self.orders[order_id].filled_qty,
                avg_fill_price=self.orders[order_id].avg_fill_price,
                timestamp=datetime.now(),
            )
            if self.on_order_update_cb:
                self.on_order_update_cb(update)
            return True
        return False

    def get_position(self, symbol: str) -> Position:
        return Position(
            symbol=symbol,
            side=PositionSide.NONE,
            qty=Decimal(0),
            avg_entry_price=Decimal(0),
        )

    def get_mark_price(self, symbol: str) -> Decimal:
        return Decimal("50000")

    def register_callbacks(self, on_order_update, on_fill, on_reject):
        self.on_order_update_cb = on_order_update
        self.on_fill_cb = on_fill
        self.on_reject_cb = on_reject

    # Test helpers
    def simulate_fill(self, order_id: str, qty: Decimal, price: Decimal, is_maker: bool = False):
        """Simulate order fill."""
        order = self.orders.get(order_id)
        if not order:
            return

        fill = Fill(
            fill_id=f"fill_{order_id}",
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            qty=qty,
            price=price,
            fee=qty * price * Decimal("0.0005"),  # 0.05% fee
            fee_currency="USDT",
            timestamp=datetime.now(),
            is_maker=is_maker,
        )

        order.filled_qty += qty
        if order.filled_qty >= order.qty:
            order.status = OrderStatus.FILLED
            order.avg_fill_price = price
        else:
            order.status = OrderStatus.PARTIAL_FILLED
            order.avg_fill_price = price  # simplified

        # Send callbacks
        if self.on_fill_cb:
            self.on_fill_cb(fill)

        if self.on_order_update_cb:
            update = OrderUpdate(
                order_id=order_id,
                status=order.status,
                filled_qty=order.filled_qty,
                avg_fill_price=order.avg_fill_price,
                timestamp=datetime.now(),
            )
            self.on_order_update_cb(update)


def test_submit_market_order():
    """Test submitting market order."""
    adapter = MockAdapter()
    engine = ExecutionEngine(adapter)

    order = engine.submit_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        qty=Decimal("1"),
        order_type=OrderType.MARKET,
    )

    assert order.order_id == "order_1"
    assert order.status == OrderStatus.PENDING_NEW
    assert order.symbol == "BTCUSDT"
    assert order.side == OrderSide.BUY
    assert order.qty == Decimal("1")


def test_order_fill():
    """Test order fill updates order status."""
    adapter = MockAdapter()
    engine = ExecutionEngine(adapter)

    order = engine.submit_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        qty=Decimal("1"),
        order_type=OrderType.MARKET,
    )

    # Simulate fill
    adapter.simulate_fill(order.order_id, Decimal("1"), Decimal("50000"))

    # Check order updated
    assert order.status == OrderStatus.FILLED
    assert order.filled_qty == Decimal("1")
    assert order.avg_fill_price == Decimal("50000")


def test_partial_fill():
    """Test partial fill."""
    adapter = MockAdapter()
    engine = ExecutionEngine(adapter)

    order = engine.submit_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        qty=Decimal("2"),
        order_type=OrderType.LIMIT,
        price=Decimal("50000"),
    )

    # Partial fill
    adapter.simulate_fill(order.order_id, Decimal("1"), Decimal("50000"))

    assert order.status == OrderStatus.PARTIAL_FILLED
    assert order.filled_qty == Decimal("1")
    assert order.remaining_qty() == Decimal("1")

    # Complete fill
    adapter.simulate_fill(order.order_id, Decimal("1"), Decimal("50000"))

    assert order.status == OrderStatus.FILLED
    assert order.filled_qty == Decimal("2")
    assert order.remaining_qty() == Decimal("0")


def test_cancel_order():
    """Test order cancellation."""
    adapter = MockAdapter()
    engine = ExecutionEngine(adapter)

    order = engine.submit_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        qty=Decimal("1"),
        order_type=OrderType.LIMIT,
        price=Decimal("50000"),
    )

    # Cancel
    success = engine.cancel_order(order.order_id)

    assert success
    assert order.status == OrderStatus.CANCELLED


def test_position_long():
    """Test long position tracking."""
    adapter = MockAdapter()
    engine = ExecutionEngine(adapter)

    # Buy 1 BTC at 50000
    order = engine.submit_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        qty=Decimal("1"),
    )
    adapter.simulate_fill(order.order_id, Decimal("1"), Decimal("50000"))

    position = engine.get_position("BTCUSDT")
    assert position.side == PositionSide.LONG
    assert position.qty == Decimal("1")
    assert position.avg_entry_price == Decimal("50000")


def test_position_short():
    """Test short position tracking."""
    adapter = MockAdapter()
    engine = ExecutionEngine(adapter)

    # Sell 1 BTC at 50000
    order = engine.submit_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        qty=Decimal("1"),
    )
    adapter.simulate_fill(order.order_id, Decimal("1"), Decimal("50000"))

    position = engine.get_position("BTCUSDT")
    assert position.side == PositionSide.SHORT
    assert position.qty == Decimal("1")
    assert position.avg_entry_price == Decimal("50000")


def test_position_close_long():
    """Test closing long position."""
    adapter = MockAdapter()
    engine = ExecutionEngine(adapter)

    # Open long: buy 1 at 50000
    order1 = engine.submit_order(symbol="BTCUSDT", side=OrderSide.BUY, qty=Decimal("1"))
    adapter.simulate_fill(order1.order_id, Decimal("1"), Decimal("50000"))

    # Close long: sell 1 at 51000
    order2 = engine.submit_order(symbol="BTCUSDT", side=OrderSide.SELL, qty=Decimal("1"))
    adapter.simulate_fill(order2.order_id, Decimal("1"), Decimal("51000"))

    position = engine.get_position("BTCUSDT")
    assert position.side == PositionSide.NONE
    assert position.qty == Decimal("0")

    # Realized PNL = (51000 - 50000) * 1 = 1000 USDT
    assert position.realized_pnl == Decimal("1000")


def test_position_close_short():
    """Test closing short position."""
    adapter = MockAdapter()
    engine = ExecutionEngine(adapter)

    # Open short: sell 1 at 50000
    order1 = engine.submit_order(symbol="BTCUSDT", side=OrderSide.SELL, qty=Decimal("1"))
    adapter.simulate_fill(order1.order_id, Decimal("1"), Decimal("50000"))

    # Close short: buy 1 at 49000
    order2 = engine.submit_order(symbol="BTCUSDT", side=OrderSide.BUY, qty=Decimal("1"))
    adapter.simulate_fill(order2.order_id, Decimal("1"), Decimal("49000"))

    position = engine.get_position("BTCUSDT")
    assert position.side == PositionSide.NONE
    assert position.qty == Decimal("0")

    # Realized PNL = (50000 - 49000) * 1 = 1000 USDT
    assert position.realized_pnl == Decimal("1000")


def test_position_increase():
    """Test increasing position."""
    adapter = MockAdapter()
    engine = ExecutionEngine(adapter)

    # Buy 1 at 50000
    order1 = engine.submit_order(symbol="BTCUSDT", side=OrderSide.BUY, qty=Decimal("1"))
    adapter.simulate_fill(order1.order_id, Decimal("1"), Decimal("50000"))

    # Buy 1 at 51000
    order2 = engine.submit_order(symbol="BTCUSDT", side=OrderSide.BUY, qty=Decimal("1"))
    adapter.simulate_fill(order2.order_id, Decimal("1"), Decimal("51000"))

    position = engine.get_position("BTCUSDT")
    assert position.side == PositionSide.LONG
    assert position.qty == Decimal("2")

    # Average entry = (50000 + 51000) / 2 = 50500
    assert position.avg_entry_price == Decimal("50500")


def test_position_flip():
    """Test flipping position from long to short."""
    adapter = MockAdapter()
    engine = ExecutionEngine(adapter)

    # Open long: buy 1 at 50000
    order1 = engine.submit_order(symbol="BTCUSDT", side=OrderSide.BUY, qty=Decimal("1"))
    adapter.simulate_fill(order1.order_id, Decimal("1"), Decimal("50000"))

    # Flip to short: sell 2 at 51000
    order2 = engine.submit_order(symbol="BTCUSDT", side=OrderSide.SELL, qty=Decimal("2"))
    adapter.simulate_fill(order2.order_id, Decimal("2"), Decimal("51000"))

    position = engine.get_position("BTCUSDT")
    assert position.side == PositionSide.SHORT
    assert position.qty == Decimal("1")
    assert position.avg_entry_price == Decimal("51000")

    # Realized PNL from closing long: (51000 - 50000) * 1 = 1000
    assert position.realized_pnl == Decimal("1000")


def test_fee_tracking():
    """Test fee tracking."""
    adapter = MockAdapter()
    engine = ExecutionEngine(adapter)

    order = engine.submit_order(symbol="BTCUSDT", side=OrderSide.BUY, qty=Decimal("1"))
    adapter.simulate_fill(order.order_id, Decimal("1"), Decimal("50000"))

    position = engine.get_position("BTCUSDT")

    # Fee = 1 * 50000 * 0.0005 = 25 USDT
    assert position.total_fees == Decimal("25")


def test_unrealized_pnl():
    """Test unrealized PNL calculation."""
    adapter = MockAdapter()
    engine = ExecutionEngine(adapter)

    # Open long at 50000
    order = engine.submit_order(symbol="BTCUSDT", side=OrderSide.BUY, qty=Decimal("1"))
    adapter.simulate_fill(order.order_id, Decimal("1"), Decimal("50000"))

    position = engine.get_position("BTCUSDT")

    # Mark price = 51000
    position.update_unrealized_pnl(Decimal("51000"))

    # Unrealized PNL = (51000 - 50000) * 1 = 1000
    assert position.unrealized_pnl == Decimal("1000")

    # Total PNL = unrealized - fees = 1000 - 25 = 975
    assert position.total_pnl() == Decimal("975")
