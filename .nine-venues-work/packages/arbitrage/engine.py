"""Venue-neutral opportunity discovery for pre-funded spot arbitrage."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import permutations
from typing import Any, Iterable, Mapping, Protocol

from packages.arbitrage.models import (
    ONE,
    ZERO,
    ArbitrageOpportunity,
    OrderBook,
    Side,
    VWAPResult,
    decimal_string,
    decimal_value,
    normalize_symbol,
    normalize_venue,
)


_COMMON_QUOTES = (
    "USDT",
    "USDC",
    "FDUSD",
    "PYUSD",
    "TUSD",
    "BUSD",
    "DAI",
    "USD",
    "EUR",
    "GBP",
    "BTC",
    "ETH",
    "BNB",
)


class BalanceReader(Protocol):
    def balance(self, venue: str, asset: str) -> Decimal: ...


def split_symbol(symbol: str) -> tuple[str, str]:
    """Split a normalized spot symbol into base and quote assets.

    Slash/dash separated symbols are accepted, while compact exchange
    symbols use a conservative list of common quote assets.  Ambiguous
    compact symbols should be supplied in a conventional exchange form such
    as ``BTCUSDT``.
    """

    if not isinstance(symbol, str):
        raise TypeError("symbol must be a string")
    raw = symbol.strip().upper()
    for separator in ("/", "-", "_"):
        if separator in raw:
            parts = [part for part in raw.split(separator) if part]
            if len(parts) != 2:
                raise ValueError(f"cannot split symbol {symbol!r}")
            return parts[0], parts[1]
    normalized = normalize_symbol(raw)
    for quote in _COMMON_QUOTES:
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return normalized[: -len(quote)], quote
    raise ValueError(f"cannot infer base and quote assets from symbol {symbol!r}")


@dataclass(frozen=True, slots=True)
class ArbitrageConfig:
    """Risk and execution assumptions used while scanning order books.

    Rates are fractions: ``Decimal('0.001')`` means 10 basis points.  Missing
    venue fees use ``default_taker_fee``.  ``max_notional`` caps the gross
    quote cost of the buy leg, before fees.
    """

    taker_fees: Mapping[str, Decimal] = field(default_factory=dict)
    min_net_edge: Decimal = Decimal("0")
    risk_buffer: Decimal = Decimal("0")
    max_notional: Decimal = Decimal("1000")
    max_staleness_ms: int | None = 1000
    default_taker_fee: Decimal = Decimal("0")
    quantity_steps: Mapping[str, Decimal] = field(default_factory=dict)
    min_notionals: Mapping[str, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fees: dict[str, Decimal] = {}
        for venue, raw_fee in dict(self.taker_fees).items():
            normalized_venue = normalize_venue(venue)
            fee = decimal_value(raw_fee, name=f"taker fee for {normalized_venue}")
            if fee < ZERO or fee >= ONE:
                raise ValueError("taker fees must be in [0, 1)")
            fees[normalized_venue] = fee

        for name in ("min_net_edge", "risk_buffer", "default_taker_fee"):
            value = decimal_value(getattr(self, name), name=name)
            if value < ZERO or value >= ONE:
                raise ValueError(f"{name} must be in [0, 1)")
            object.__setattr__(self, name, value)

        max_notional = decimal_value(self.max_notional, name="max_notional")
        if max_notional <= ZERO:
            raise ValueError("max_notional must be greater than zero")
        object.__setattr__(self, "max_notional", max_notional)

        if self.max_staleness_ms is not None:
            if isinstance(self.max_staleness_ms, bool):
                raise TypeError("max_staleness_ms must be an integer or None")
            try:
                staleness = int(self.max_staleness_ms)
            except (TypeError, ValueError) as exc:
                raise TypeError("max_staleness_ms must be an integer or None") from exc
            if staleness < 0:
                raise ValueError("max_staleness_ms must not be negative")
            object.__setattr__(self, "max_staleness_ms", staleness)
        object.__setattr__(self, "taker_fees", fees)

        quantity_steps: dict[str, Decimal] = {}
        for symbol, raw_step in dict(self.quantity_steps).items():
            normalized_symbol = normalize_symbol(symbol)
            step = decimal_value(raw_step, name=f"quantity step for {normalized_symbol}")
            if step <= ZERO:
                raise ValueError("quantity steps must be greater than zero")
            quantity_steps[normalized_symbol] = step
        object.__setattr__(self, "quantity_steps", quantity_steps)

        min_notionals: dict[str, Decimal] = {}
        for symbol, raw_minimum in dict(self.min_notionals).items():
            normalized_symbol = normalize_symbol(symbol)
            minimum = decimal_value(raw_minimum, name=f"minimum notional for {normalized_symbol}")
            if minimum < ZERO:
                raise ValueError("minimum notionals must not be negative")
            min_notionals[normalized_symbol] = minimum
        object.__setattr__(self, "min_notionals", min_notionals)

    def fee_for(self, venue: str) -> Decimal:
        return self.taker_fees.get(normalize_venue(venue), self.default_taker_fee)

    def to_dict(self) -> dict[str, Any]:
        return {
            "taker_fees": {
                venue: decimal_string(fee)
                for venue, fee in sorted(self.taker_fees.items())
            },
            "min_net_edge": decimal_string(self.min_net_edge),
            "risk_buffer": decimal_string(self.risk_buffer),
            "max_notional": decimal_string(self.max_notional),
            "max_staleness_ms": self.max_staleness_ms,
            "default_taker_fee": decimal_string(self.default_taker_fee),
            "quantity_steps": {
                symbol: decimal_string(step)
                for symbol, step in sorted(self.quantity_steps.items())
            },
            "min_notionals": {
                symbol: decimal_string(minimum)
                for symbol, minimum in sorted(self.min_notionals.items())
            },
        }


def executable_vwap(
    book: OrderBook,
    side: Side | str,
    quantity: Decimal | str | int | float,
) -> VWAPResult:
    """Public functional form of :meth:`OrderBook.executable_vwap`."""

    return book.executable_vwap(side, quantity)


def _mapping_lookup_case_insensitive(mapping: Mapping[Any, Any], key: str) -> Any:
    if key in mapping:
        return mapping[key]
    normalized = key.lower()
    for candidate, value in mapping.items():
        if isinstance(candidate, str) and candidate.lower() == normalized:
            return value
    return None


def _read_balance(
    balances: BalanceReader | Mapping[Any, Any] | None,
    venue: str,
    asset: str,
) -> Decimal | None:
    if balances is None:
        return None
    if hasattr(balances, "balance") and callable(getattr(balances, "balance")):
        raw = balances.balance(venue, asset)  # type: ignore[union-attr]
    elif isinstance(balances, Mapping):
        tuple_value = balances.get((venue, asset))
        if tuple_value is not None:
            raw = tuple_value
        else:
            venue_balances = _mapping_lookup_case_insensitive(balances, venue)
            if venue_balances is None:
                raw = ZERO
            elif not isinstance(venue_balances, Mapping):
                raise TypeError("balances must map venues to asset mappings")
            else:
                asset_value = _mapping_lookup_case_insensitive(venue_balances, asset)
                raw = ZERO if asset_value is None else asset_value
    else:
        raise TypeError("balances must be a mapping or expose balance(venue, asset)")
    result = decimal_value(raw, name=f"balance {asset}@{venue}")
    if result < ZERO:
        raise ValueError("balances must not be negative")
    return result


class ArbitrageEngine:
    """Compare every directed venue pair and return executable opportunities."""

    def __init__(self, config: ArbitrageConfig | None = None) -> None:
        self.config = config or ArbitrageConfig()

    def scan(
        self,
        order_books: Iterable[OrderBook],
        *,
        now_ms: int | None = None,
        balances: BalanceReader | Mapping[Any, Any] | None = None,
    ) -> list[ArbitrageOpportunity]:
        """Scan all symbols and all directed pairs of fresh venue books.

        If several snapshots exist for one venue/symbol, only the latest is
        used.  With no explicit ``now_ms`` the newest supplied snapshot is the
        reference clock, making historical and deterministic replay natural.
        """

        latest: dict[tuple[str, str], OrderBook] = {}
        for book in order_books:
            if not isinstance(book, OrderBook):
                raise TypeError("order_books must contain OrderBook instances")
            key = (book.symbol, book.venue)
            existing = latest.get(key)
            if existing is None or book.timestamp_ms > existing.timestamp_ms:
                latest[key] = book
        if not latest:
            return []

        if now_ms is None:
            reference_ms = max(book.timestamp_ms for book in latest.values())
        else:
            if isinstance(now_ms, bool):
                raise TypeError("now_ms must be an integer")
            try:
                reference_ms = int(now_ms)
            except (TypeError, ValueError) as exc:
                raise TypeError("now_ms must be an integer") from exc
            if reference_ms < 0:
                raise ValueError("now_ms must not be negative")

        fresh: dict[str, list[OrderBook]] = {}
        for book in latest.values():
            if (
                self.config.max_staleness_ms is not None
                and reference_ms - book.timestamp_ms > self.config.max_staleness_ms
            ):
                continue
            fresh.setdefault(book.symbol, []).append(book)

        opportunities: list[ArbitrageOpportunity] = []
        for symbol in sorted(fresh):
            books = sorted(fresh[symbol], key=lambda item: item.venue)
            for buy_book, sell_book in permutations(books, 2):
                opportunity = self.evaluate_pair(
                    buy_book,
                    sell_book,
                    balances=balances,
                )
                if opportunity is not None:
                    opportunities.append(opportunity)

        return sorted(
            opportunities,
            key=lambda item: (
                -item.net_profit,
                -item.net_edge,
                item.symbol,
                item.buy_venue,
                item.sell_venue,
            ),
        )

    # Explicit name for callers that prefer it over ``scan``.
    scan_opportunities = scan

    def evaluate_pair(
        self,
        buy_book: OrderBook,
        sell_book: OrderBook,
        *,
        balances: BalanceReader | Mapping[Any, Any] | None = None,
    ) -> ArbitrageOpportunity | None:
        """Return the most profitable executable size for one direction."""

        if not isinstance(buy_book, OrderBook) or not isinstance(sell_book, OrderBook):
            raise TypeError("buy_book and sell_book must be OrderBook instances")
        if buy_book.symbol != sell_book.symbol:
            raise ValueError("buy and sell books must have the same symbol")
        if buy_book.venue == sell_book.venue:
            raise ValueError("buy and sell venues must differ")
        if not buy_book.asks or not sell_book.bids:
            return None

        base_asset, quote_asset = split_symbol(buy_book.symbol)
        buy_fee_rate = self.config.fee_for(buy_book.venue)
        sell_fee_rate = self.config.fee_for(sell_book.venue)

        quote_balance = _read_balance(balances, buy_book.venue, quote_asset)
        base_balance = _read_balance(balances, sell_book.venue, base_asset)
        cost_cap = self.config.max_notional
        if quote_balance is not None:
            # The buy fee is charged in quote currency by the paper model.
            affordable = quote_balance / (ONE + buy_fee_rate)
            # Decimal division can round one ULP upward.  Moving to the next
            # representable value below the quotient guarantees that a quote
            # emitted by the scanner is accepted by the atomic paper executor.
            if affordable * (ONE + buy_fee_rate) > quote_balance:
                affordable = affordable.next_minus()
            cost_cap = min(cost_cap, affordable)
        quantity_cap = base_balance
        if cost_cap <= ZERO or (quantity_cap is not None and quantity_cap <= ZERO):
            return None

        buy_index = 0
        sell_index = 0
        buy_remaining = buy_book.asks[0].quantity
        sell_remaining = sell_book.bids[0].quantity
        quantity = ZERO
        buy_notional = ZERO
        sell_notional = ZERO
        best: ArbitrageOpportunity | None = None
        quantity_step = self.config.quantity_steps.get(buy_book.symbol)
        minimum_notional = self.config.min_notionals.get(buy_book.symbol, ZERO)

        def consider_candidate(
            candidate_quantity: Decimal,
            candidate_buy_notional: Decimal,
            candidate_sell_notional: Decimal,
            *,
            threshold_boundary: bool = False,
        ) -> None:
            nonlocal best
            if quantity_step is not None:
                stepped_quantity = (
                    candidate_quantity // quantity_step
                ) * quantity_step
                if stepped_quantity <= ZERO:
                    return
                if stepped_quantity != candidate_quantity:
                    buy_quote = buy_book.executable_vwap(Side.BUY, stepped_quantity)
                    sell_quote = sell_book.executable_vwap(Side.SELL, stepped_quantity)
                    candidate_quantity = stepped_quantity
                    candidate_buy_notional = buy_quote.notional
                    candidate_sell_notional = sell_quote.notional
            if candidate_buy_notional < minimum_notional:
                return
            candidate_buy_fee = candidate_buy_notional * buy_fee_rate
            candidate_sell_fee = candidate_sell_notional * sell_fee_rate
            candidate_risk_cost = candidate_buy_notional * self.config.risk_buffer
            candidate_gross_profit = candidate_sell_notional - candidate_buy_notional
            candidate_net_profit = (
                candidate_gross_profit
                - candidate_buy_fee
                - candidate_sell_fee
                - candidate_risk_cost
            )
            candidate_gross_edge = candidate_gross_profit / candidate_buy_notional
            candidate_net_edge = candidate_net_profit / candidate_buy_notional
            passes_threshold = candidate_net_edge >= self.config.min_net_edge
            # Decimal division at an exact threshold intersection can land one
            # representable value below the boundary.  The algebraic crossing
            # is still a valid minimum-edge candidate.
            if candidate_net_profit <= ZERO or not (passes_threshold or threshold_boundary):
                return
            candidate = ArbitrageOpportunity(
                symbol=buy_book.symbol,
                base_asset=base_asset,
                quote_asset=quote_asset,
                buy_venue=buy_book.venue,
                sell_venue=sell_book.venue,
                buy_timestamp_ms=buy_book.timestamp_ms,
                sell_timestamp_ms=sell_book.timestamp_ms,
                quantity=candidate_quantity,
                buy_vwap=candidate_buy_notional / candidate_quantity,
                sell_vwap=candidate_sell_notional / candidate_quantity,
                buy_notional=candidate_buy_notional,
                sell_notional=candidate_sell_notional,
                buy_fee=candidate_buy_fee,
                sell_fee=candidate_sell_fee,
                risk_buffer_cost=candidate_risk_cost,
                gross_profit=candidate_gross_profit,
                net_profit=candidate_net_profit,
                gross_edge=candidate_gross_edge,
                net_edge=candidate_net_edge,
            )
            if best is None or (candidate.net_profit, candidate.net_edge) > (
                best.net_profit,
                best.net_edge,
            ):
                best = candidate

        while buy_index < len(buy_book.asks) and sell_index < len(sell_book.bids):
            buy_price = buy_book.asks[buy_index].price
            sell_price = sell_book.bids[sell_index].price
            remaining_cost = cost_cap - buy_notional
            if remaining_cost <= ZERO:
                break
            fill = min(buy_remaining, sell_remaining, remaining_cost / buy_price)
            if quantity_cap is not None:
                fill = min(fill, quantity_cap - quantity)
            if fill <= ZERO:
                break

            previous_quantity = quantity
            previous_buy_notional = buy_notional
            previous_sell_notional = sell_notional
            quantity += fill
            buy_notional += fill * buy_price
            sell_notional += fill * sell_price
            buy_remaining -= fill
            sell_remaining -= fill

            consider_candidate(quantity, buy_notional, sell_notional)

            # An edge threshold can be crossed *inside* one price level.  If
            # the marginal fill still earns money but dilutes average edge,
            # retain the exact largest size at the configured threshold rather
            # than falling all the way back to the preceding depth boundary.
            if previous_quantity > ZERO and self.config.min_net_edge > ZERO:
                previous_net = (
                    previous_sell_notional * (ONE - sell_fee_rate)
                    - previous_buy_notional
                    * (ONE + buy_fee_rate + self.config.risk_buffer)
                )
                current_net = (
                    sell_notional * (ONE - sell_fee_rate)
                    - buy_notional * (ONE + buy_fee_rate + self.config.risk_buffer)
                )
                previous_surplus = (
                    previous_net
                    - self.config.min_net_edge * previous_buy_notional
                )
                current_surplus = current_net - self.config.min_net_edge * buy_notional
                marginal_net = (
                    sell_price * (ONE - sell_fee_rate)
                    - buy_price * (ONE + buy_fee_rate + self.config.risk_buffer)
                )
                surplus_slope = marginal_net - self.config.min_net_edge * buy_price
                if (
                    previous_surplus > ZERO
                    and current_surplus < ZERO
                    and marginal_net > ZERO
                    and surplus_slope < ZERO
                ):
                    boundary_fill = previous_surplus / -surplus_slope
                    if ZERO < boundary_fill < fill:
                        consider_candidate(
                            previous_quantity + boundary_fill,
                            previous_buy_notional + boundary_fill * buy_price,
                            previous_sell_notional + boundary_fill * sell_price,
                            threshold_boundary=True,
                        )

            if buy_remaining == ZERO:
                buy_index += 1
                if buy_index < len(buy_book.asks):
                    buy_remaining = buy_book.asks[buy_index].quantity
            if sell_remaining == ZERO:
                sell_index += 1
                if sell_index < len(sell_book.bids):
                    sell_remaining = sell_book.bids[sell_index].quantity

        return best


def scan_opportunities(
    order_books: Iterable[OrderBook],
    config: ArbitrageConfig | None = None,
    *,
    now_ms: int | None = None,
    balances: BalanceReader | Mapping[Any, Any] | None = None,
) -> list[ArbitrageOpportunity]:
    """One-shot convenience wrapper around :class:`ArbitrageEngine`."""

    return ArbitrageEngine(config).scan(order_books, now_ms=now_ms, balances=balances)
