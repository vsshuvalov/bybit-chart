"""
Simulator Engine — event-driven backtesting engine (Roadmap Этап 8.2).

Принципы:
- Deterministic: same data → same result (checksum)
- No lookahead: decisions use only past data
- Conservative fills: maker fills at worse price if book moves
- Realistic latency: 200-500ms p99 (Bybit latency model)
- Clock control: replay at any speed

Architecture:
    SimulatorClock → controls time
    MarketReplay → feeds data events
    OrderMatcher → matches orders against book state
    SimulatorAdapter → implements ExecutionAdapter interface
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator, Optional, Callable

from packages.execution.engine import (
    Order, Fill, OrderUpdate, OrderStatus, OrderSide,
    ExecutionAdapter, OnOrderUpdateCallback, OnFillCallback, OnRejectCallback,
    Position, RejectReason, PositionSide,
)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

class SimulatorClock:
    """Controls simulation time.

    Replay mode: time advances as data events arrive.
    Realtime mode: time follows wall clock.
    """

    def __init__(self, start_time_ms: int = 0):
        self._current_time_ms = start_time_ms
        self._is_replay = True

    def advance(self, timestamp_ms: int):
        """Advance clock to new timestamp (replay mode)."""
        if timestamp_ms > self._current_time_ms:
            self._current_time_ms = timestamp_ms

    def now_ms(self) -> int:
        """Current simulation time in milliseconds."""
        if self._is_replay:
            return self._current_time_ms
        return int(time.time() * 1000)

    def now(self) -> datetime:
        """Current simulation time as datetime."""
        return datetime.fromtimestamp(self.now_ms() / 1000)


# ---------------------------------------------------------------------------
# Market data events
# ---------------------------------------------------------------------------

@dataclass
class TradeEvent:
    """Simulated trade event."""
    timestamp_ms: int
    symbol: str
    side: OrderSide
    price: Decimal
    qty: Decimal


@dataclass
class BookEvent:
    """Simulated orderbook snapshot."""
    timestamp_ms: int
    symbol: str
    bids: list[tuple[Decimal, Decimal]]  # (price, qty)
    asks: list[tuple[Decimal, Decimal]]


# ---------------------------------------------------------------------------
# Latency model
# ---------------------------------------------------------------------------

class LatencyModel:
    """Realistic latency model for order submission.

    Based on Bybit latency statistics:
    - p50: ~100ms
    - p95: ~300ms
    - p99: ~500ms
    """

    def __init__(
        self,
        p50_ms: int = 100,
        p95_ms: int = 300,
        p99_ms: int = 500,
    ):
        self.p50_ms = p50_ms
        self.p95_ms = p95_ms
        self.p99_ms = p99_ms

    def sample_latency_ms(self, rng_seed: int) -> int:
        """Sample latency from distribution (deterministic given seed)."""
        # Use simple deterministic sampling based on seed
        # In reality would use scipy.stats, but keep it simple + deterministic
        v = (rng_seed * 2654435769) & 0xFFFFFFFF  # Knuth hash
        percentile = (v % 100) + 1  # 1-100

        if percentile <= 50:
            return self.p50_ms
        elif percentile <= 95:
            return self.p95_ms
        else:
            return self.p99_ms


# ---------------------------------------------------------------------------
# Order Matcher
# ---------------------------------------------------------------------------

@dataclass
class OrderMatchResult:
    """Result of order matching attempt."""
    filled_qty: Decimal
    avg_price: Decimal
    is_maker: bool


class OrderMatcher:
    """Matches orders against simulated book state.

    Conservative maker scenario:
    - Limit buy at or above best ask → immediate fill (taker)
    - Limit buy below best ask → rests in book (maker, fill when ask drops)
    - Market order → fills at best available price

    No lookahead: only uses book state at submission time + latency.
    """

    def __init__(self, latency_model: LatencyModel):
        self.latency_model = latency_model

    def match_market(
        self,
        order: Order,
        bids: list[tuple[Decimal, Decimal]],
        asks: list[tuple[Decimal, Decimal]],
        seed: int,
    ) -> Optional[OrderMatchResult]:
        """Match market order against book."""
        latency_ms = self.latency_model.sample_latency_ms(seed)
        # After latency, book may have moved — use conservative fill
        # For now: fill at current best price (simplified)

        if order.side == OrderSide.BUY:
            if not asks:
                return None  # No liquidity
            best_ask_price, best_ask_qty = asks[0]
            # Conservative: fill at best ask (taker)
            fill_qty = min(order.qty, best_ask_qty)
            return OrderMatchResult(
                filled_qty=fill_qty,
                avg_price=best_ask_price,
                is_maker=False,
            )
        else:  # SELL
            if not bids:
                return None
            best_bid_price, best_bid_qty = bids[0]
            fill_qty = min(order.qty, best_bid_qty)
            return OrderMatchResult(
                filled_qty=fill_qty,
                avg_price=best_bid_price,
                is_maker=False,
            )

    def match_limit(
        self,
        order: Order,
        bids: list[tuple[Decimal, Decimal]],
        asks: list[tuple[Decimal, Decimal]],
        seed: int,
    ) -> Optional[OrderMatchResult]:
        """Match limit order against book."""
        latency_ms = self.latency_model.sample_latency_ms(seed)

        if order.price is None:
            return None

        if order.side == OrderSide.BUY:
            if not asks:
                return None
            best_ask_price, best_ask_qty = asks[0]
            if order.price >= best_ask_price:
                # Order crosses spread — immediate taker fill
                fill_qty = min(order.qty, best_ask_qty)
                return OrderMatchResult(
                    filled_qty=fill_qty,
                    avg_price=best_ask_price,  # fill at ask, not limit price
                    is_maker=False,
                )
            else:
                # Order rests in book — no fill yet (returns None = pending)
                return None
        else:  # SELL
            if not bids:
                return None
            best_bid_price, best_bid_qty = bids[0]
            if order.price <= best_bid_price:
                fill_qty = min(order.qty, best_bid_qty)
                return OrderMatchResult(
                    filled_qty=fill_qty,
                    avg_price=best_bid_price,
                    is_maker=False,
                )
            else:
                return None


# ---------------------------------------------------------------------------
# Simulator Adapter
# ---------------------------------------------------------------------------

class SimulatorAdapter(ExecutionAdapter):
    """
    ExecutionAdapter implementation for backtesting.

    Пример использования:
        clock = SimulatorClock()
        adapter = SimulatorAdapter(clock)
        engine = ExecutionEngine(adapter)

        # Feed market data
        adapter.on_book_event(BookEvent(...))
        adapter.on_trade_event(TradeEvent(...))

        # Submit orders via engine
        engine.submit_order(...)
    """

    def __init__(self, clock: SimulatorClock, latency_model: Optional[LatencyModel] = None):
        self.clock = clock
        self.matcher = OrderMatcher(latency_model or LatencyModel())

        # Current book state
        self._current_bids: list[tuple[Decimal, Decimal]] = []
        self._current_asks: list[tuple[Decimal, Decimal]] = []
        self._mark_prices: dict[str, Decimal] = {}

        # Pending orders waiting for fill
        self._pending_orders: dict[str, Order] = {}

        # Callbacks
        self._on_order_update: Optional[OnOrderUpdateCallback] = None
        self._on_fill: Optional[OnFillCallback] = None
        self._on_reject: Optional[OnRejectCallback] = None

        # Stats for checksum
        self._fill_log: list[dict] = []
        self._order_counter = 0

    def register_callbacks(self, on_order_update, on_fill, on_reject):
        self._on_order_update = on_order_update
        self._on_fill = on_fill
        self._on_reject = on_reject

    def submit_order(self, order: Order) -> str:
        """Submit order to simulator."""
        self._order_counter += 1
        order_id = f"sim_{self._order_counter}"

        self._pending_orders[order_id] = order

        # Try immediate fill (market orders, crossing limit orders)
        self._try_fill(order_id, order)

        return order_id

    def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order."""
        if order_id in self._pending_orders:
            order = self._pending_orders.pop(order_id)
            update = OrderUpdate(
                order_id=order_id,
                status=OrderStatus.CANCELLED,
                filled_qty=order.filled_qty,
                avg_fill_price=order.avg_fill_price,
                timestamp=self.clock.now(),
            )
            if self._on_order_update:
                self._on_order_update(update)
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
        return self._mark_prices.get(symbol, Decimal(0))

    # ------------------------------------------------------------------
    # Feed market data
    # ------------------------------------------------------------------

    def on_trade_event(self, event: TradeEvent):
        """Process trade event — advance clock and update mark price."""
        self.clock.advance(event.timestamp_ms)
        self._mark_prices[event.symbol] = event.price

        # Try to fill resting limit orders on each trade
        self._try_fill_resting_orders(event.symbol)

    def on_book_event(self, event: BookEvent):
        """Process book snapshot — update book state."""
        self.clock.advance(event.timestamp_ms)
        self._current_bids = event.bids
        self._current_asks = event.asks

        # Update mark price from mid
        if event.bids and event.asks:
            mid = (event.bids[0][0] + event.asks[0][0]) / 2
            self._mark_prices[event.symbol] = mid

        # Try to fill resting orders on book update
        self._try_fill_resting_orders(event.symbol)

    # ------------------------------------------------------------------
    # Determinism / checksum
    # ------------------------------------------------------------------

    def compute_checksum(self) -> str:
        """Compute deterministic checksum of all fills.

        Same market data + same strategy → same checksum.
        Used for regression testing.
        """
        fill_data = json.dumps(self._fill_log, sort_keys=True, default=str)
        return hashlib.sha256(fill_data.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Internal fill logic
    # ------------------------------------------------------------------

    def _try_fill(self, order_id: str, order: Order):
        """Try to fill order immediately (market or crossing limit)."""
        from packages.execution.engine import OrderType

        if order.order_type == OrderType.MARKET:
            result = self.matcher.match_market(
                order, self._current_bids, self._current_asks,
                seed=self._order_counter,
            )
        else:
            result = self.matcher.match_limit(
                order, self._current_bids, self._current_asks,
                seed=self._order_counter,
            )

        if result and result.filled_qty > 0:
            self._execute_fill(order_id, order, result)

    def _try_fill_resting_orders(self, symbol: str):
        """Try to fill resting limit orders on book update."""
        for order_id, order in list(self._pending_orders.items()):
            if order.symbol != symbol or order.is_terminal():
                continue

            from packages.execution.engine import OrderType
            if order.order_type != OrderType.LIMIT:
                continue

            result = self.matcher.match_limit(
                order, self._current_bids, self._current_asks,
                seed=hash(order_id),
            )

            if result and result.filled_qty > 0:
                self._execute_fill(order_id, order, result)

    def _execute_fill(self, order_id: str, order: Order, result: OrderMatchResult):
        """Execute fill and notify callbacks."""
        fee_rate = Decimal("0.00025") if result.is_maker else Decimal("0.00075")
        fee = result.filled_qty * result.avg_price * fee_rate

        fill = Fill(
            fill_id=f"fill_{order_id}_{len(self._fill_log)}",
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            qty=result.filled_qty,
            price=result.avg_price,
            fee=fee,
            fee_currency="USDT",
            timestamp=self.clock.now(),
            is_maker=result.is_maker,
        )

        # Log for checksum
        self._fill_log.append({
            "order_id": order_id,
            "qty": str(result.filled_qty),
            "price": str(result.avg_price),
            "fee": str(fee),
        })

        # Update order
        order.filled_qty += result.filled_qty
        order.avg_fill_price = result.avg_price

        if order.filled_qty >= order.qty:
            order.status = OrderStatus.FILLED
            self._pending_orders.pop(order_id, None)
        else:
            order.status = OrderStatus.PARTIAL_FILLED

        # Callbacks
        # Buffer fills if engine hasn't registered order yet (sync submit pattern)
        if self._on_fill:
            self._on_fill(fill)
        else:
            # Buffer for post-submit replay
            if not hasattr(self, '_pending_fills_buffer'):
                self._pending_fills_buffer: dict = {}
            self._pending_fills_buffer.setdefault(order_id, []).append(fill)

        if self._on_order_update:
            update = OrderUpdate(
                order_id=order_id,
                status=order.status,
                filled_qty=order.filled_qty,
                avg_fill_price=order.avg_fill_price,
                timestamp=self.clock.now(),
            )
            self._on_order_update(update)
