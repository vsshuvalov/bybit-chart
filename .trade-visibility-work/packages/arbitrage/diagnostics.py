"""Transparent top-of-book diagnostics for venue-neutral arbitrage scans.

The execution engine deliberately returns only executable opportunities.  A
scanner UI needs the complementary view as well: every directed venue pair,
including the routes rejected by market-data, liquidity, fee, or edge gates.
This module provides that read-only assessment without depending on the
service, API, or paper portfolio.

Rates supplied to :func:`assess_pairs` are fractions.  For example,
``Decimal("0.001")`` is a 10 basis-point taker fee.  Monetary values and rates
remain :class:`~decimal.Decimal` internally, while :meth:`PairAssessment.to_dict`
serializes every Decimal as a fixed-point string.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import permutations
from typing import Any, Iterable, Mapping

from packages.arbitrage.models import (
    ONE,
    ZERO,
    OrderBook,
    decimal_string,
    decimal_value,
    normalize_symbol,
    normalize_venue,
)


BPS = Decimal("10000")

PAIR_SKEW = "pair_skew"
INSUFFICIENT_DEPTH = "insufficient_depth"
NON_POSITIVE_GROSS = "non_positive_gross"
NON_POSITIVE_AFTER_COSTS = "non_positive_after_costs"
BELOW_NET_THRESHOLD = "below_net_threshold"

REJECTION_REASONS = (
    PAIR_SKEW,
    INSUFFICIENT_DEPTH,
    NON_POSITIVE_GROSS,
    NON_POSITIVE_AFTER_COSTS,
    BELOW_NET_THRESHOLD,
)


@dataclass(frozen=True, slots=True)
class PairAssessment:
    """One directed same-symbol route assessed at the public BBO.

    ``notional`` is the gross quote cost of the buy leg before fees.  Depths
    are the complete best-level quote notionals, not just the amount consumed
    by this assessment.  Fee and risk-buffer fields are quote-currency costs;
    their rate/bps representations are exposed as properties and in
    :meth:`to_dict`.
    """

    symbol: str
    buy_venue: str
    sell_venue: str
    buy_timestamp_ms: int
    sell_timestamp_ms: int
    quantity: Decimal
    buy_price: Decimal
    sell_price: Decimal
    notional: Decimal
    buy_depth: Decimal
    sell_depth: Decimal
    buy_fee: Decimal
    sell_fee: Decimal
    risk_buffer_cost: Decimal
    gross_edge: Decimal
    net_edge: Decimal
    threshold_gap: Decimal
    primary_rejection: str | None
    reasons: tuple[str, ...]
    eligible: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        object.__setattr__(self, "buy_venue", normalize_venue(self.buy_venue))
        object.__setattr__(self, "sell_venue", normalize_venue(self.sell_venue))
        if self.buy_venue == self.sell_venue:
            raise ValueError("buy and sell venues must differ")

        for name in ("buy_timestamp_ms", "sell_timestamp_ms"):
            raw = getattr(self, name)
            if isinstance(raw, bool):
                raise TypeError(f"{name} must be an integer")
            try:
                value = int(raw)
            except (TypeError, ValueError) as exc:
                raise TypeError(f"{name} must be an integer") from exc
            if value < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)

        decimal_fields = (
            "quantity",
            "buy_price",
            "sell_price",
            "notional",
            "buy_depth",
            "sell_depth",
            "buy_fee",
            "sell_fee",
            "risk_buffer_cost",
            "gross_edge",
            "net_edge",
            "threshold_gap",
        )
        for name in decimal_fields:
            object.__setattr__(
                self,
                name,
                decimal_value(getattr(self, name), name=name),
            )
        if (
            self.quantity <= ZERO
            or self.buy_price <= ZERO
            or self.sell_price <= ZERO
            or self.notional <= ZERO
        ):
            raise ValueError("quantity, prices, and notional must be greater than zero")
        if self.buy_depth <= ZERO or self.sell_depth <= ZERO:
            raise ValueError("BBO depths must be greater than zero")
        if self.buy_fee < ZERO or self.sell_fee < ZERO or self.risk_buffer_cost < ZERO:
            raise ValueError("fees and risk buffer cost must not be negative")

        reasons = tuple(self.reasons)
        unknown = tuple(reason for reason in reasons if reason not in REJECTION_REASONS)
        if unknown:
            raise ValueError(f"unknown rejection reason(s): {', '.join(unknown)}")
        if len(reasons) != len(set(reasons)):
            raise ValueError("rejection reasons must be unique")
        object.__setattr__(self, "reasons", reasons)

        expected_primary = reasons[0] if reasons else None
        if self.primary_rejection != expected_primary:
            raise ValueError("primary_rejection must be the first rejection reason")
        if self.eligible != (not reasons):
            raise ValueError("eligible must be true exactly when reasons is empty")

    @property
    def route(self) -> str:
        return f"{self.buy_venue}->{self.sell_venue}"

    @property
    def pair_skew_ms(self) -> int:
        return abs(self.buy_timestamp_ms - self.sell_timestamp_ms)

    @property
    def buy_notional(self) -> Decimal:
        return self.notional

    @property
    def sell_notional(self) -> Decimal:
        return self.quantity * self.sell_price

    @property
    def gross_profit(self) -> Decimal:
        return self.sell_notional - self.notional

    @property
    def net_profit(self) -> Decimal:
        return (
            self.gross_profit
            - self.buy_fee
            - self.sell_fee
            - self.risk_buffer_cost
        )

    @property
    def buy_fee_rate(self) -> Decimal:
        return self.buy_fee / self.notional

    @property
    def sell_fee_rate(self) -> Decimal:
        return self.sell_fee / self.sell_notional

    @property
    def risk_buffer_rate(self) -> Decimal:
        return self.risk_buffer_cost / self.notional

    def to_dict(self) -> dict[str, Any]:
        """Return an API-safe representation with exact Decimal strings."""

        decimal_values = {
            "quantity": self.quantity,
            "buy_price": self.buy_price,
            "sell_price": self.sell_price,
            "notional": self.notional,
            "buy_notional": self.buy_notional,
            "sell_notional": self.sell_notional,
            "buy_depth": self.buy_depth,
            "sell_depth": self.sell_depth,
            "buy_fee": self.buy_fee,
            "sell_fee": self.sell_fee,
            "risk_buffer_cost": self.risk_buffer_cost,
            # Readable alias for clients that present the cost breakdown.
            "risk_buffer": self.risk_buffer_cost,
            "gross_profit": self.gross_profit,
            "net_profit": self.net_profit,
            "gross_edge": self.gross_edge,
            "net_edge": self.net_edge,
            "threshold_gap": self.threshold_gap,
            "buy_fee_rate": self.buy_fee_rate,
            "sell_fee_rate": self.sell_fee_rate,
            "risk_buffer_rate": self.risk_buffer_rate,
            "gross_edge_bps": self.gross_edge * BPS,
            "net_edge_bps": self.net_edge * BPS,
            "threshold_gap_bps": self.threshold_gap * BPS,
            "buy_fee_bps": self.buy_fee_rate * BPS,
            "sell_fee_bps": self.sell_fee_rate * BPS,
            "risk_buffer_bps": self.risk_buffer_rate * BPS,
        }
        result: dict[str, Any] = {
            "symbol": self.symbol,
            "buy_venue": self.buy_venue,
            "sell_venue": self.sell_venue,
            "route": self.route,
            "buy_timestamp_ms": self.buy_timestamp_ms,
            "sell_timestamp_ms": self.sell_timestamp_ms,
            "pair_skew_ms": self.pair_skew_ms,
            "primary_rejection": self.primary_rejection,
            "reasons": list(self.reasons),
            "eligible": self.eligible,
        }
        result.update(
            {name: decimal_string(value) for name, value in decimal_values.items()}
        )
        return result


def _rate(
    value: Decimal | str | int | float,
    *,
    name: str,
) -> Decimal:
    result = decimal_value(value, name=name)
    if result < ZERO or result >= ONE:
        raise ValueError(f"{name} must be in [0, 1)")
    return result


def assess_pairs(
    books: Iterable[OrderBook],
    *,
    taker_fees: Mapping[str, Decimal | str | int | float] | None = None,
    default_taker_fee: Decimal | str | int | float = Decimal("0"),
    risk_buffer: Decimal | str | int | float = Decimal("0"),
    min_net_edge: Decimal | str | int | float = Decimal("0"),
    max_notional: Decimal | str | int | float = Decimal("25"),
    min_notional: Decimal | str | int | float = Decimal("0"),
    max_pair_skew_ms: int = 2_000,
) -> list[PairAssessment]:
    """Assess every directed, BBO-defined pair without filtering rejections.

    The newest supplied snapshot is used for each ``(symbol, venue)`` key,
    matching :class:`packages.arbitrage.engine.ArbitrageEngine`.  Sizing is
    capped by ``max_notional`` and both best-level quantities.  Consequently,
    ``insufficient_depth`` means the common BBO fill falls below
    ``min_notional``; partial top-level size at or above that minimum remains
    a valid assessment, just as it does in the execution engine.

    Books missing the required ask or bid do not define a directed BBO route
    and are omitted.  Results are sorted by net edge (best first), then by
    stable symbol/venue keys.
    """

    fee_by_venue: dict[str, Decimal] = {}
    for venue, raw_fee in (taker_fees or {}).items():
        normalized = normalize_venue(venue)
        fee_by_venue[normalized] = _rate(
            raw_fee,
            name=f"taker fee for {normalized}",
        )
    fallback_fee = _rate(default_taker_fee, name="default_taker_fee")
    risk_rate = _rate(risk_buffer, name="risk_buffer")
    threshold = _rate(min_net_edge, name="min_net_edge")

    maximum = decimal_value(max_notional, name="max_notional")
    minimum = decimal_value(min_notional, name="min_notional")
    if maximum <= ZERO:
        raise ValueError("max_notional must be greater than zero")
    if minimum < ZERO:
        raise ValueError("min_notional must not be negative")
    if isinstance(max_pair_skew_ms, bool):
        raise TypeError("max_pair_skew_ms must be an integer")
    try:
        skew_limit = int(max_pair_skew_ms)
    except (TypeError, ValueError) as exc:
        raise TypeError("max_pair_skew_ms must be an integer") from exc
    if skew_limit < 0:
        raise ValueError("max_pair_skew_ms must not be negative")

    latest: dict[tuple[str, str], OrderBook] = {}
    for book in books:
        if not isinstance(book, OrderBook):
            raise TypeError("books must contain OrderBook instances")
        key = (book.symbol, book.venue)
        current = latest.get(key)
        if current is None or book.timestamp_ms > current.timestamp_ms:
            latest[key] = book

    by_symbol: dict[str, list[OrderBook]] = {}
    for book in latest.values():
        by_symbol.setdefault(book.symbol, []).append(book)

    assessments: list[PairAssessment] = []
    for symbol in sorted(by_symbol):
        symbol_books = sorted(by_symbol[symbol], key=lambda item: item.venue)
        for buy_book, sell_book in permutations(symbol_books, 2):
            if not buy_book.asks or not sell_book.bids:
                continue
            buy_level = buy_book.asks[0]
            sell_level = sell_book.bids[0]
            quantity = min(
                maximum / buy_level.price,
                buy_level.quantity,
                sell_level.quantity,
            )
            # PriceLevel quantities and max_notional validation make this
            # unreachable, but retaining the guard makes the arithmetic total
            # if OrderBook gains zero-size diagnostic levels in the future.
            if quantity <= ZERO:
                continue

            buy_notional = quantity * buy_level.price
            sell_notional = quantity * sell_level.price
            buy_fee_rate = fee_by_venue.get(buy_book.venue, fallback_fee)
            sell_fee_rate = fee_by_venue.get(sell_book.venue, fallback_fee)
            buy_fee = buy_notional * buy_fee_rate
            sell_fee = sell_notional * sell_fee_rate
            buffer_cost = buy_notional * risk_rate
            gross_profit = sell_notional - buy_notional
            net_profit = gross_profit - buy_fee - sell_fee - buffer_cost
            gross_edge = gross_profit / buy_notional
            net_edge = net_profit / buy_notional
            threshold_gap = net_edge - threshold

            reasons: list[str] = []
            if abs(buy_book.timestamp_ms - sell_book.timestamp_ms) > skew_limit:
                reasons.append(PAIR_SKEW)
            if buy_notional < minimum:
                reasons.append(INSUFFICIENT_DEPTH)
            # Economic rejection categories are intentionally exclusive.  It
            # keeps the funnel meaningful while market-data/depth reasons can
            # still coexist with the applicable economic reason.
            if gross_edge <= ZERO:
                reasons.append(NON_POSITIVE_GROSS)
            elif net_edge <= ZERO:
                reasons.append(NON_POSITIVE_AFTER_COSTS)
            elif net_edge < threshold:
                reasons.append(BELOW_NET_THRESHOLD)

            assessments.append(
                PairAssessment(
                    symbol=symbol,
                    buy_venue=buy_book.venue,
                    sell_venue=sell_book.venue,
                    buy_timestamp_ms=buy_book.timestamp_ms,
                    sell_timestamp_ms=sell_book.timestamp_ms,
                    quantity=quantity,
                    buy_price=buy_level.price,
                    sell_price=sell_level.price,
                    notional=buy_notional,
                    buy_depth=buy_level.notional,
                    sell_depth=sell_level.notional,
                    buy_fee=buy_fee,
                    sell_fee=sell_fee,
                    risk_buffer_cost=buffer_cost,
                    gross_edge=gross_edge,
                    net_edge=net_edge,
                    threshold_gap=threshold_gap,
                    primary_rejection=reasons[0] if reasons else None,
                    reasons=tuple(reasons),
                    eligible=not reasons,
                )
            )

    return sorted(
        assessments,
        key=lambda item: (
            -item.net_edge,
            item.symbol,
            item.buy_venue,
            item.sell_venue,
        ),
    )


def aggregate_assessments(
    assessments: Iterable[PairAssessment],
) -> dict[str, Any]:
    """Aggregate deterministic eligibility and rejection funnel counters."""

    rows = tuple(assessments)
    if any(not isinstance(row, PairAssessment) for row in rows):
        raise TypeError("assessments must contain PairAssessment instances")

    primary = {reason: 0 for reason in REJECTION_REASONS}
    reasons = {reason: 0 for reason in REJECTION_REASONS}
    for row in rows:
        if row.primary_rejection is not None:
            primary[row.primary_rejection] += 1
        for reason in row.reasons:
            reasons[reason] += 1

    eligible = sum(1 for row in rows if row.eligible)
    return {
        "total_pairs": len(rows),
        "eligible_pairs": eligible,
        "rejected_pairs": len(rows) - eligible,
        "primary_rejections": primary,
        "reason_counts": reasons,
    }


__all__ = [
    "BELOW_NET_THRESHOLD",
    "INSUFFICIENT_DEPTH",
    "NON_POSITIVE_AFTER_COSTS",
    "NON_POSITIVE_GROSS",
    "PAIR_SKEW",
    "PairAssessment",
    "REJECTION_REASONS",
    "aggregate_assessments",
    "assess_pairs",
]
