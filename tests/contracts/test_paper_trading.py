"""
Тесты Paper Trading Engine (Roadmap §14 extended).

Проверяют: PaperTradingEngine, order execution, position tracking.
"""

import pytest

from packages.backtesting.paper_trading import (
    OrderStatus,
    PaperAccount,
    PaperOrder,
    PaperTradingEngine,
)
from packages.backtesting.strategy import Order, OrderSide, OrderType

pytestmark = pytest.mark.contract


class TestPaperTradingEngine:
    """Тесты PaperTradingEngine."""

    def test_engine_initialization(self):
        """PaperTradingEngine инициализируется корректно."""
        engine = PaperTradingEngine(initial_balance=50000.0)

        assert engine.account.initial_balance == 50000.0
        assert engine.account.balance == 50000.0
        assert engine.account.equity == 50000.0
        assert len(engine.active_orders) == 0
        assert len(engine.trades) == 0

    def test_submit_order(self):
        """submit_order() добавляет ордер в active_orders."""
        engine = PaperTradingEngine()

        order = Order(
            order_id="test_1",
            timestamp_us=1000,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )

        paper_order = engine.submit_order(order)

        assert paper_order.order_id == "test_1"
        assert paper_order.status == OrderStatus.PENDING
        assert "test_1" in engine.active_orders

    def test_execute_market_buy_order(self):
        """Market BUY order исполняется при process_market_data."""
        engine = PaperTradingEngine(initial_balance=100000.0, commission_rate=0.0, slippage_rate=0.0)

        order = Order(
            order_id="buy_1",
            timestamp_us=1000,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )

        engine.submit_order(order)
        engine.process_market_data("BTCUSDT", 50000.0, 1000)

        # Order should be filled
        assert "buy_1" not in engine.active_orders
        assert len(engine.trades) == 1
        assert len(engine.order_history) == 1

        # Position should be LONG
        assert "BTCUSDT" in engine.account.positions
        position = engine.account.positions["BTCUSDT"]
        assert position.side.value == "long"
        assert position.quantity == 1.0

        # Balance should decrease
        assert engine.account.balance < 100000.0

    def test_execute_market_sell_order(self):
        """Market SELL order исполняется корректно."""
        engine = PaperTradingEngine(initial_balance=100000.0, commission_rate=0.0, slippage_rate=0.0)

        # Buy first
        buy_order = Order("buy_1", 1000, "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 1.0)
        engine.submit_order(buy_order)
        engine.process_market_data("BTCUSDT", 50000.0, 1000)

        # Then sell
        sell_order = Order("sell_1", 2000, "BTCUSDT", OrderSide.SELL, OrderType.MARKET, 1.0)
        engine.submit_order(sell_order)
        engine.process_market_data("BTCUSDT", 55000.0, 2000)

        # Position should be FLAT
        position = engine.account.positions["BTCUSDT"]
        assert position.side.value == "flat"

        # Should have profit
        assert engine.account.realized_pnl > 0
        assert engine.account.total_trades == 1
        assert engine.account.winning_trades == 1

    def test_commission_applied(self):
        """Комиссия корректно вычитается."""
        engine = PaperTradingEngine(initial_balance=100000.0, commission_rate=0.001, slippage_rate=0.0)

        order = Order("buy_1", 1000, "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 1.0)
        engine.submit_order(order)
        engine.process_market_data("BTCUSDT", 50000.0, 1000)

        # Commission should be 50000 * 0.001 = 50
        assert engine.account.total_commission == pytest.approx(50.0, rel=0.01)

    def test_slippage_applied(self):
        """Проскальзывание применяется к execution price."""
        engine = PaperTradingEngine(initial_balance=100000.0, commission_rate=0.0, slippage_rate=0.001)

        order = Order("buy_1", 1000, "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 1.0)
        engine.submit_order(order)
        engine.process_market_data("BTCUSDT", 50000.0, 1000)

        # Execution price should be 50000 * 1.001 = 50050
        trade = engine.trades[0]
        assert trade.price == pytest.approx(50050.0, rel=0.01)

    def test_unrealized_pnl_updates(self):
        """Unrealized PnL обновляется с market data."""
        engine = PaperTradingEngine(initial_balance=100000.0, commission_rate=0.0, slippage_rate=0.0)

        # Open LONG
        order = Order("buy_1", 1000, "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 1.0)
        engine.submit_order(order)
        engine.process_market_data("BTCUSDT", 50000.0, 1000)

        # Balance after buy: 100000 - 50000 = 50000
        assert engine.account.balance == pytest.approx(50000.0)

        # Price goes up
        engine.process_market_data("BTCUSDT", 55000.0, 2000)

        # Unrealized PnL should be 5000 (55000 - 50000)
        assert engine.account.unrealized_pnl == pytest.approx(5000.0)
        # Equity = balance + unrealized = 50000 + 5000 = 55000
        assert engine.account.equity == pytest.approx(55000.0)

    def test_cancel_order(self):
        """cancel_order() отменяет активный ордер."""
        engine = PaperTradingEngine()

        order = Order("test_1", 1000, "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 1.0)
        engine.submit_order(order)

        result = engine.cancel_order("test_1")

        assert result is True
        assert "test_1" not in engine.active_orders
        assert len(engine.order_history) == 1
        assert engine.order_history[0].status == OrderStatus.CANCELLED

    def test_get_active_orders(self):
        """get_active_orders() возвращает активные ордера."""
        engine = PaperTradingEngine()

        order1 = Order("order_1", 1000, "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 1.0)
        order2 = Order("order_2", 2000, "ETHUSDT", OrderSide.BUY, OrderType.MARKET, 1.0)

        engine.submit_order(order1)
        engine.submit_order(order2)

        # All orders
        all_orders = engine.get_active_orders()
        assert len(all_orders) == 2

        # Filter by symbol
        btc_orders = engine.get_active_orders(symbol="BTCUSDT")
        assert len(btc_orders) == 1
        assert btc_orders[0].symbol == "BTCUSDT"

    def test_get_trade_history(self):
        """get_trade_history() возвращает историю сделок."""
        engine = PaperTradingEngine(initial_balance=100000.0, commission_rate=0.0, slippage_rate=0.0)

        # Execute 2 trades
        order1 = Order("buy_1", 1000, "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 1.0)
        engine.submit_order(order1)
        engine.process_market_data("BTCUSDT", 50000.0, 1000)

        order2 = Order("sell_1", 2000, "BTCUSDT", OrderSide.SELL, OrderType.MARKET, 1.0)
        engine.submit_order(order2)
        engine.process_market_data("BTCUSDT", 55000.0, 2000)

        history = engine.get_trade_history()

        assert len(history) == 2
        assert history[0].trade_id == "paper_2"  # newest first

    def test_get_account_state(self):
        """get_account_state() возвращает состояние счёта."""
        engine = PaperTradingEngine(initial_balance=100000.0)

        state = engine.get_account_state()

        assert state["initial_balance"] == 100000.0
        assert state["balance"] == 100000.0
        assert state["equity"] == 100000.0
        assert state["total_trades"] == 0
        assert "win_rate" in state


class TestPaperOrder:
    """Тесты PaperOrder."""

    def test_order_update_fill(self):
        """update_fill() корректно обновляет filled quantity."""
        order = PaperOrder(
            order_id="test",
            timestamp_us=1000,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=2.0,
        )

        order.update_fill(1.0, 50000.0)

        assert order.filled_quantity == 1.0
        assert order.average_fill_price == 50000.0
        assert order.status == OrderStatus.PARTIALLY_FILLED

        order.update_fill(1.0, 51000.0)

        assert order.filled_quantity == 2.0
        assert order.average_fill_price == 50500.0
        assert order.status == OrderStatus.FILLED
        assert order.filled_at is not None


class TestPaperAccount:
    """Тесты PaperAccount."""

    def test_account_update_equity(self):
        """update_equity() обновляет equity с unrealized PnL."""
        from packages.backtesting.strategy import Position, PositionSide

        account = PaperAccount(
            initial_balance=100000.0,
            balance=50000.0,
            equity=50000.0,
        )

        # Add position
        account.positions["BTCUSDT"] = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
        )

        # Update with current price
        account.update_equity("BTCUSDT", 55000.0)

        assert account.unrealized_pnl == 5000.0
        assert account.equity == 55000.0
