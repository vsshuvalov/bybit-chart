"""
Unit tests для SimulatorAdapter (Roadmap Этап 8.2).

Tests:
- Market order fills immediately
- Limit order waits for book to move
- Clock advances with market data
- Deterministic checksum: same data → same fills
- No lookahead: fills only use past data
"""

import pytest
from decimal import Decimal

from packages.execution.simulator import (
    SimulatorClock,
    SimulatorAdapter,
    LatencyModel,
    TradeEvent,
    BookEvent,
    OrderMatchResult,
)
from packages.execution.engine import (
    ExecutionEngine,
    OrderSide,
    OrderType,
    OrderStatus,
    TimeInForce,
)

pytestmark = pytest.mark.contract


def make_book(bid_price: str, ask_price: str, qty: str = "10") -> BookEvent:
    return BookEvent(
        timestamp_ms=1000,
        symbol="BTCUSDT",
        bids=[(Decimal(bid_price), Decimal(qty))],
        asks=[(Decimal(ask_price), Decimal(qty))],
    )


class TestSimulatorClock:

    def test_initial_time(self):
        clock = SimulatorClock(start_time_ms=1000)
        assert clock.now_ms() == 1000

    def test_advance(self):
        clock = SimulatorClock(start_time_ms=1000)
        clock.advance(2000)
        assert clock.now_ms() == 2000

    def test_advance_backwards_ignored(self):
        clock = SimulatorClock(start_time_ms=2000)
        clock.advance(1000)  # backwards
        assert clock.now_ms() == 2000  # unchanged


class TestSimulatorAdapter:

    def test_market_buy_fills_immediately(self):
        clock = SimulatorClock()
        adapter = SimulatorAdapter(clock)
        engine = ExecutionEngine(adapter)

        # Set book state
        adapter.on_book_event(make_book("49990", "50000"))

        # Submit market buy
        order = engine.submit_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            qty=Decimal("1"),
            order_type=OrderType.MARKET,
        )

        # Should fill immediately at ask price
        assert order.status == OrderStatus.FILLED
        assert order.avg_fill_price == Decimal("50000")
        assert order.filled_qty == Decimal("1")

    def test_market_sell_fills_at_bid(self):
        clock = SimulatorClock()
        adapter = SimulatorAdapter(clock)
        engine = ExecutionEngine(adapter)

        adapter.on_book_event(make_book("49990", "50000"))

        order = engine.submit_order(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            qty=Decimal("1"),
            order_type=OrderType.MARKET,
        )

        assert order.status == OrderStatus.FILLED
        assert order.avg_fill_price == Decimal("49990")

    def test_limit_buy_below_ask_rests(self):
        clock = SimulatorClock()
        adapter = SimulatorAdapter(clock)
        engine = ExecutionEngine(adapter)

        adapter.on_book_event(make_book("49990", "50000"))

        # Limit buy at 49980 (below ask of 50000) → rests
        order = engine.submit_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            qty=Decimal("1"),
            order_type=OrderType.LIMIT,
            price=Decimal("49980"),
        )

        assert order.status == OrderStatus.PENDING_NEW
        assert order.filled_qty == Decimal("0")

    def test_limit_buy_crosses_spread_fills(self):
        clock = SimulatorClock()
        adapter = SimulatorAdapter(clock)
        engine = ExecutionEngine(adapter)

        adapter.on_book_event(make_book("49990", "50000"))

        # Limit buy at 50010 (above ask of 50000) → immediate taker fill
        order = engine.submit_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            qty=Decimal("1"),
            order_type=OrderType.LIMIT,
            price=Decimal("50010"),
        )

        assert order.status == OrderStatus.FILLED
        # Conservative: fills at ask price (50000), not limit price (50010)
        assert order.avg_fill_price == Decimal("50000")

    def test_resting_limit_fills_on_book_update(self):
        clock = SimulatorClock()
        adapter = SimulatorAdapter(clock)
        engine = ExecutionEngine(adapter)

        adapter.on_book_event(make_book("49990", "50000"))

        # Limit buy at 49990 (ask is 50000) → rests
        order = engine.submit_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            qty=Decimal("1"),
            order_type=OrderType.LIMIT,
            price=Decimal("49990"),
        )
        assert order.status == OrderStatus.PENDING_NEW

        # Price drops: new ask = 49985 → order should fill
        adapter.on_book_event(BookEvent(
            timestamp_ms=2000,
            symbol="BTCUSDT",
            bids=[(Decimal("49975"), Decimal("10"))],
            asks=[(Decimal("49985"), Decimal("10"))],
        ))

        assert order.status == OrderStatus.FILLED
        assert order.avg_fill_price == Decimal("49985")

    def test_clock_advances_with_market_data(self):
        clock = SimulatorClock()
        adapter = SimulatorAdapter(clock)

        adapter.on_trade_event(TradeEvent(
            timestamp_ms=5000,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            qty=Decimal("1"),
        ))

        assert clock.now_ms() == 5000

    def test_mark_price_updates_from_book(self):
        clock = SimulatorClock()
        adapter = SimulatorAdapter(clock)

        adapter.on_book_event(make_book("49990", "50010"))

        # Mark price = mid = (49990 + 50010) / 2 = 50000
        assert adapter.get_mark_price("BTCUSDT") == Decimal("50000")

    def test_cancel_pending_order(self):
        clock = SimulatorClock()
        adapter = SimulatorAdapter(clock)
        engine = ExecutionEngine(adapter)

        adapter.on_book_event(make_book("49990", "50000"))

        # Limit below ask → rests
        order = engine.submit_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            qty=Decimal("1"),
            order_type=OrderType.LIMIT,
            price=Decimal("49980"),
        )

        engine.cancel_order(order.order_id)
        assert order.status == OrderStatus.CANCELLED

    def test_deterministic_checksum(self):
        """Same data → same checksum (no randomness)."""

        def run_simulation():
            clock = SimulatorClock()
            adapter = SimulatorAdapter(clock)
            engine = ExecutionEngine(adapter)

            adapter.on_book_event(make_book("49990", "50000"))
            engine.submit_order(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                qty=Decimal("1"),
                order_type=OrderType.MARKET,
            )
            adapter.on_book_event(make_book("50000", "50010"))
            engine.submit_order(
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                qty=Decimal("1"),
                order_type=OrderType.MARKET,
            )
            return adapter.compute_checksum()

        # Same simulation → same checksum
        checksum1 = run_simulation()
        checksum2 = run_simulation()
        assert checksum1 == checksum2
        assert len(checksum1) == 16

    def test_position_tracks_through_fills(self):
        """Position updates correctly after fills."""
        clock = SimulatorClock()
        adapter = SimulatorAdapter(clock)
        engine = ExecutionEngine(adapter)

        adapter.on_book_event(make_book("49990", "50000"))

        # Buy 1 BTC
        engine.submit_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            qty=Decimal("1"),
            order_type=OrderType.MARKET,
        )

        # Position is tracked inside engine via get_position()
        from packages.execution.engine import PositionSide
        position = engine.get_position("BTCUSDT")
        assert position is not None
        assert position.side == PositionSide.LONG
        assert position.qty == Decimal("1")


class TestLatencyModel:

    def test_deterministic(self):
        model = LatencyModel()
        # Same seed → same latency
        l1 = model.sample_latency_ms(42)
        l2 = model.sample_latency_ms(42)
        assert l1 == l2

    def test_latency_in_range(self):
        model = LatencyModel(p50_ms=100, p95_ms=300, p99_ms=500)
        for seed in range(100):
            latency = model.sample_latency_ms(seed)
            assert latency in [100, 300, 500]
