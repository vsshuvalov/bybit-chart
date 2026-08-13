"""Domain models for venue-neutral spot arbitrage.

All monetary values are represented by :class:`~decimal.Decimal`.  The
``to_dict`` methods deliberately encode decimals as strings so that API
layers can pass the result directly to ``json.dumps`` without losing
precision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Sequence


ZERO = Decimal("0")
ONE = Decimal("1")


def decimal_value(value: Decimal | str | int | float, *, name: str = "value") -> Decimal:
    """Return a finite ``Decimal`` while avoiding binary-float artefacts."""

    if isinstance(value, bool):
        raise TypeError(f"{name} must be a number, not bool")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TypeError(f"{name} must be Decimal-compatible") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def decimal_string(value: Decimal) -> str:
    """Serialize a ``Decimal`` exactly in fixed-point notation."""

    return format(value, "f")


def normalize_venue(venue: str) -> str:
    if not isinstance(venue, str):
        raise TypeError("venue must be a string")
    normalized = venue.strip().lower()
    if not normalized:
        raise ValueError("venue must not be empty")
    return normalized


def normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise TypeError("symbol must be a string")
    normalized = symbol.strip().upper()
    for separator in ("/", "-", "_"):
        normalized = normalized.replace(separator, "")
    if not normalized:
        raise ValueError("symbol must not be empty")
    return normalized


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @classmethod
    def parse(cls, value: Side | str) -> Side:
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError("side must be 'buy' or 'sell'")
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            raise ValueError("side must be 'buy' or 'sell'") from exc


class InsufficientLiquidityError(ValueError):
    """Raised when an order-book side cannot fill the requested quantity."""


@dataclass(frozen=True, slots=True)
class PriceLevel:
    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        price = decimal_value(self.price, name="price")
        quantity = decimal_value(self.quantity, name="quantity")
        if price <= ZERO:
            raise ValueError("price must be greater than zero")
        if quantity <= ZERO:
            raise ValueError("quantity must be greater than zero")
        object.__setattr__(self, "price", price)
        object.__setattr__(self, "quantity", quantity)

    @property
    def size(self) -> Decimal:
        """Common exchange-API synonym for ``quantity``."""

        return self.quantity

    @property
    def notional(self) -> Decimal:
        return self.price * self.quantity

    def to_dict(self) -> dict[str, str]:
        return {
            "price": decimal_string(self.price),
            "quantity": decimal_string(self.quantity),
        }


# ``BookLevel`` is retained as a readable synonym for callers.
BookLevel = PriceLevel


def _coerce_level(level: PriceLevel | Mapping[str, Any] | Sequence[Any]) -> PriceLevel:
    if isinstance(level, PriceLevel):
        return level
    if isinstance(level, Mapping):
        quantity = level.get("quantity", level.get("size"))
        if "price" not in level or quantity is None:
            raise ValueError("level mapping requires price and quantity")
        return PriceLevel(level["price"], quantity)
    if isinstance(level, Sequence) and not isinstance(level, (str, bytes)) and len(level) == 2:
        return PriceLevel(level[0], level[1])
    raise TypeError("each level must be PriceLevel, a mapping, or a (price, quantity) pair")


@dataclass(frozen=True, slots=True)
class VWAPResult:
    side: Side
    quantity: Decimal
    notional: Decimal
    average_price: Decimal
    levels_consumed: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", Side.parse(self.side))
        for name in ("quantity", "notional", "average_price"):
            value = decimal_value(getattr(self, name), name=name)
            if value <= ZERO:
                raise ValueError(f"{name} must be greater than zero")
            object.__setattr__(self, name, value)
        if isinstance(self.levels_consumed, bool) or self.levels_consumed <= 0:
            raise ValueError("levels_consumed must be a positive integer")

    @property
    def vwap(self) -> Decimal:
        return self.average_price

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side.value,
            "quantity": decimal_string(self.quantity),
            "notional": decimal_string(self.notional),
            "average_price": decimal_string(self.average_price),
            "levels_consumed": self.levels_consumed,
        }


@dataclass(frozen=True, slots=True)
class OrderBook:
    venue: str
    symbol: str
    timestamp_ms: int
    bids: tuple[PriceLevel, ...] = field(default_factory=tuple)
    asks: tuple[PriceLevel, ...] = field(default_factory=tuple)
    snapshot_id: str | None = None

    def __post_init__(self) -> None:
        venue = normalize_venue(self.venue)
        symbol = normalize_symbol(self.symbol)
        if isinstance(self.timestamp_ms, bool):
            raise TypeError("timestamp_ms must be an integer")
        try:
            timestamp_ms = int(self.timestamp_ms)
        except (TypeError, ValueError) as exc:
            raise TypeError("timestamp_ms must be an integer") from exc
        if timestamp_ms < 0:
            raise ValueError("timestamp_ms must not be negative")

        snapshot_id = self.snapshot_id
        if snapshot_id is not None:
            snapshot_id = str(snapshot_id).strip()
            if not snapshot_id:
                raise ValueError("snapshot_id must not be empty")

        bids = tuple(sorted((_coerce_level(level) for level in self.bids), key=lambda x: x.price, reverse=True))
        asks = tuple(sorted((_coerce_level(level) for level in self.asks), key=lambda x: x.price))
        if bids and asks and bids[0].price >= asks[0].price:
            raise ValueError("order book is crossed: best bid must be below best ask")

        object.__setattr__(self, "venue", venue)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "timestamp_ms", timestamp_ms)
        object.__setattr__(self, "bids", bids)
        object.__setattr__(self, "asks", asks)
        object.__setattr__(self, "snapshot_id", snapshot_id)

    @property
    def best_bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None

    def executable_vwap(self, side: Side | str, quantity: Decimal | str | int | float) -> VWAPResult:
        """Calculate the exact VWAP for a marketable base-asset quantity.

        Buys consume asks and sells consume bids.  The call either returns a
        complete fill or raises ``InsufficientLiquidityError``; it never
        silently returns a partial execution.
        """

        parsed_side = Side.parse(side)
        requested = decimal_value(quantity, name="quantity")
        if requested <= ZERO:
            raise ValueError("quantity must be greater than zero")
        levels = self.asks if parsed_side is Side.BUY else self.bids
        remaining = requested
        notional = ZERO
        consumed = 0
        for level in levels:
            fill = min(remaining, level.quantity)
            if fill > ZERO:
                notional += fill * level.price
                remaining -= fill
                consumed += 1
            if remaining == ZERO:
                break
        if remaining > ZERO:
            available = requested - remaining
            raise InsufficientLiquidityError(
                f"{self.venue} {self.symbol} {parsed_side.value} requested {requested}, "
                f"only {available} available"
            )
        return VWAPResult(
            side=parsed_side,
            quantity=requested,
            notional=notional,
            average_price=notional / requested,
            levels_consumed=consumed,
        )

    # Short name convenient in notebooks and API services.
    vwap = executable_vwap

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "timestamp_ms": self.timestamp_ms,
            "snapshot_id": self.snapshot_id,
            "bids": [level.to_dict() for level in self.bids],
            "asks": [level.to_dict() for level in self.asks],
        }


@dataclass(frozen=True, slots=True)
class ArbitrageOpportunity:
    symbol: str
    base_asset: str
    quote_asset: str
    buy_venue: str
    sell_venue: str
    buy_timestamp_ms: int
    sell_timestamp_ms: int
    quantity: Decimal
    buy_vwap: Decimal
    sell_vwap: Decimal
    buy_notional: Decimal
    sell_notional: Decimal
    buy_fee: Decimal
    sell_fee: Decimal
    risk_buffer_cost: Decimal
    gross_profit: Decimal
    net_profit: Decimal
    gross_edge: Decimal
    net_edge: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        object.__setattr__(self, "buy_venue", normalize_venue(self.buy_venue))
        object.__setattr__(self, "sell_venue", normalize_venue(self.sell_venue))
        if self.buy_venue == self.sell_venue:
            raise ValueError("buy and sell venues must differ")
        for name in ("base_asset", "quote_asset"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value.strip().upper())
        if self.base_asset == self.quote_asset:
            raise ValueError("base_asset and quote_asset must differ")
        for name in ("buy_timestamp_ms", "sell_timestamp_ms"):
            raw_timestamp = getattr(self, name)
            if isinstance(raw_timestamp, bool):
                raise TypeError(f"{name} must be an integer")
            try:
                timestamp = int(raw_timestamp)
            except (TypeError, ValueError) as exc:
                raise TypeError(f"{name} must be an integer") from exc
            if timestamp < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, timestamp)
        for name in (
            "quantity",
            "buy_vwap",
            "sell_vwap",
            "buy_notional",
            "sell_notional",
            "buy_fee",
            "sell_fee",
            "risk_buffer_cost",
            "gross_profit",
            "net_profit",
            "gross_edge",
            "net_edge",
        ):
            object.__setattr__(self, name, decimal_value(getattr(self, name), name=name))
        if self.quantity <= ZERO or self.buy_notional <= ZERO or self.sell_notional <= ZERO:
            raise ValueError("opportunity quantity and notionals must be greater than zero")
        if self.buy_vwap <= ZERO or self.sell_vwap <= ZERO:
            raise ValueError("opportunity VWAPs must be greater than zero")
        if self.buy_fee < ZERO or self.sell_fee < ZERO or self.risk_buffer_cost < ZERO:
            raise ValueError("fees and risk buffer cost must not be negative")

    @property
    def expected_profit(self) -> Decimal:
        return self.net_profit

    @property
    def route(self) -> str:
        return f"{self.buy_venue}->{self.sell_venue}"

    def to_dict(self) -> dict[str, Any]:
        decimal_fields = (
            "quantity",
            "buy_vwap",
            "sell_vwap",
            "buy_notional",
            "sell_notional",
            "buy_fee",
            "sell_fee",
            "risk_buffer_cost",
            "gross_profit",
            "net_profit",
            "gross_edge",
            "net_edge",
        )
        result: dict[str, Any] = {
            "symbol": self.symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "buy_venue": self.buy_venue,
            "sell_venue": self.sell_venue,
            "route": self.route,
            "buy_timestamp_ms": self.buy_timestamp_ms,
            "sell_timestamp_ms": self.sell_timestamp_ms,
        }
        result.update({name: decimal_string(getattr(self, name)) for name in decimal_fields})
        return result
