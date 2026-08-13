"""Venue-local, paper-only triangular spot arbitrage primitives.

The module is deliberately independent of exchange clients.  It consumes a
normalized top-of-book ticker universe, evaluates ``A -> B -> C -> A`` paths
with exact :class:`~decimal.Decimal` arithmetic, and can apply a discovered
round trip to an in-memory paper portfolio atomically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from packages.arbitrage.models import (
    ONE,
    ZERO,
    decimal_string,
    decimal_value,
    normalize_symbol,
    normalize_venue,
)

BPS = Decimal("10000")


def _asset_name(asset: str, *, name: str = "asset") -> str:
    if not isinstance(asset, str):
        raise TypeError(f"{name} must be a string")
    normalized = asset.strip().upper()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _timestamp(value: Any, *, name: str = "timestamp_ms") -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be an integer") from exc
    if result < 0:
        raise ValueError(f"{name} must not be negative")
    return result


def _json_balances(
    balances: Mapping[str, Mapping[str, Decimal]],
) -> dict[str, dict[str, str]]:
    return {
        venue: {
            asset: decimal_string(amount)
            for asset, amount in sorted(assets.items())
        }
        for venue, assets in sorted(balances.items())
    }


@dataclass(frozen=True, slots=True)
class MarketTicker:
    """Normalized executable top-of-book and 24-hour liquidity metadata."""

    venue: str
    symbol: str
    base_asset: str
    quote_asset: str
    timestamp_ms: int
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    quote_volume: Decimal = ZERO
    volume_usdt: Decimal = ZERO
    snapshot_id: str | None = None
    change_24h_pct: Decimal = ZERO

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", normalize_venue(self.venue))
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        object.__setattr__(
            self,
            "base_asset",
            _asset_name(self.base_asset, name="base_asset"),
        )
        object.__setattr__(
            self,
            "quote_asset",
            _asset_name(self.quote_asset, name="quote_asset"),
        )
        if self.base_asset == self.quote_asset:
            raise ValueError("base_asset and quote_asset must differ")
        object.__setattr__(self, "timestamp_ms", _timestamp(self.timestamp_ms))

        for name in ("bid", "ask", "bid_size", "ask_size"):
            value = decimal_value(getattr(self, name), name=name)
            if value <= ZERO:
                raise ValueError(f"{name} must be greater than zero")
            object.__setattr__(self, name, value)
        if self.bid >= self.ask:
            raise ValueError("ticker must have a positive bid/ask spread")

        for name in ("quote_volume", "volume_usdt"):
            value = decimal_value(getattr(self, name), name=name)
            if value < ZERO:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)

        snapshot_id = self.snapshot_id
        if snapshot_id is not None:
            snapshot_id = str(snapshot_id).strip()
            if not snapshot_id:
                raise ValueError("snapshot_id must not be empty")
        object.__setattr__(self, "snapshot_id", snapshot_id)

        object.__setattr__(
            self,
            "change_24h_pct",
            decimal_value(self.change_24h_pct, name="change_24h_pct"),
        )

    @property
    def mid_price(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "timestamp_ms": self.timestamp_ms,
            "bid": decimal_string(self.bid),
            "ask": decimal_string(self.ask),
            "bid_size": decimal_string(self.bid_size),
            "ask_size": decimal_string(self.ask_size),
            "quote_volume": decimal_string(self.quote_volume),
            "volume_usdt": decimal_string(self.volume_usdt),
            "snapshot_id": self.snapshot_id,
            "change_24h_pct": decimal_string(self.change_24h_pct),
        }


@dataclass(frozen=True, slots=True)
class TriangularConfig:
    """Fee, edge, sizing, and freshness assumptions for the scanner.

    Rates are fractions, so ``Decimal("0.001")`` represents 10 basis points.
    ``max_start_amount`` is denominated in whichever start asset a scan uses.
    """

    taker_fees: Mapping[str, Decimal] = field(default_factory=dict)
    min_net_edge: Decimal = ZERO
    risk_buffer: Decimal = ZERO
    max_start_amount: Decimal = Decimal("1000")
    max_staleness_ms: int | None = 1000
    max_leg_skew_ms: int | None = 1000
    default_taker_fee: Decimal = ZERO

    def __post_init__(self) -> None:
        fees: dict[str, Decimal] = {}
        for venue, raw_fee in dict(self.taker_fees).items():
            normalized_venue = normalize_venue(venue)
            fee = decimal_value(raw_fee, name=f"taker fee for {normalized_venue}")
            if fee < ZERO or fee >= ONE:
                raise ValueError("taker fees must be in [0, 1)")
            fees[normalized_venue] = fee
        object.__setattr__(self, "taker_fees", fees)

        for name in ("min_net_edge", "risk_buffer", "default_taker_fee"):
            value = decimal_value(getattr(self, name), name=name)
            if value < ZERO or value >= ONE:
                raise ValueError(f"{name} must be in [0, 1)")
            object.__setattr__(self, name, value)

        max_start_amount = decimal_value(
            self.max_start_amount,
            name="max_start_amount",
        )
        if max_start_amount <= ZERO:
            raise ValueError("max_start_amount must be greater than zero")
        object.__setattr__(self, "max_start_amount", max_start_amount)

        if self.max_staleness_ms is not None:
            staleness = _timestamp(
                self.max_staleness_ms,
                name="max_staleness_ms",
            )
            object.__setattr__(self, "max_staleness_ms", staleness)
        if self.max_leg_skew_ms is not None:
            skew = _timestamp(
                self.max_leg_skew_ms,
                name="max_leg_skew_ms",
            )
            object.__setattr__(self, "max_leg_skew_ms", skew)

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
            "max_start_amount": decimal_string(self.max_start_amount),
            "max_staleness_ms": self.max_staleness_ms,
            "max_leg_skew_ms": self.max_leg_skew_ms,
            "default_taker_fee": decimal_string(self.default_taker_fee),
        }


@dataclass(frozen=True, slots=True)
class TriangularLeg:
    """One executable conversion captured from a ticker snapshot."""

    venue: str
    symbol: str
    from_asset: str
    to_asset: str
    side: str
    price: Decimal
    input_amount: Decimal
    output_before_fee: Decimal
    fee: Decimal
    output_amount: Decimal
    capacity_input: Decimal
    timestamp_ms: int
    snapshot_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", normalize_venue(self.venue))
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        object.__setattr__(
            self,
            "from_asset",
            _asset_name(self.from_asset, name="from_asset"),
        )
        object.__setattr__(
            self,
            "to_asset",
            _asset_name(self.to_asset, name="to_asset"),
        )
        if self.from_asset == self.to_asset:
            raise ValueError("leg assets must differ")
        side = str(self.side).strip().lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "timestamp_ms", _timestamp(self.timestamp_ms))
        for name in (
            "price",
            "input_amount",
            "output_before_fee",
            "output_amount",
            "capacity_input",
        ):
            value = decimal_value(getattr(self, name), name=name)
            if value <= ZERO:
                raise ValueError(f"{name} must be greater than zero")
            object.__setattr__(self, name, value)
        fee = decimal_value(self.fee, name="fee")
        if fee < ZERO:
            raise ValueError("fee must not be negative")
        object.__setattr__(self, "fee", fee)
        if self.input_amount > self.capacity_input:
            raise ValueError("leg input exceeds top-of-book capacity")
        if self.output_before_fee - self.fee != self.output_amount:
            raise ValueError("output_amount must equal output_before_fee minus fee")
        snapshot_id = self.snapshot_id
        if snapshot_id is not None:
            snapshot_id = str(snapshot_id).strip()
            if not snapshot_id:
                raise ValueError("snapshot_id must not be empty")
        object.__setattr__(self, "snapshot_id", snapshot_id)

    @property
    def fee_rate(self) -> Decimal:
        """Effective fee fraction charged from this leg's gross output."""

        return self.fee / self.output_before_fee

    @property
    def fee_rate_bps(self) -> Decimal:
        return self.fee_rate * BPS

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "from_asset": self.from_asset,
            "to_asset": self.to_asset,
            "side": self.side,
            "price": decimal_string(self.price),
            "input_amount": decimal_string(self.input_amount),
            "output_before_fee": decimal_string(self.output_before_fee),
            "fee": decimal_string(self.fee),
            "fee_amount": decimal_string(self.fee),
            "fee_asset": self.to_asset,
            "fee_rate": decimal_string(self.fee_rate),
            "fee_rate_bps": decimal_string(self.fee_rate_bps),
            "output_amount": decimal_string(self.output_amount),
            "capacity_input": decimal_string(self.capacity_input),
            "timestamp_ms": self.timestamp_ms,
            "snapshot_id": self.snapshot_id,
        }


@dataclass(frozen=True, slots=True)
class TriangularOpportunity:
    """An executable three-leg round trip on one venue."""

    venue: str
    start_asset: str
    route: tuple[str, str, str, str]
    legs: tuple[TriangularLeg, TriangularLeg, TriangularLeg]
    start_amount: Decimal
    gross_final_amount: Decimal
    final_amount: Decimal
    risk_buffer_cost: Decimal
    gross_profit: Decimal
    net_profit: Decimal
    gross_edge: Decimal
    net_edge: Decimal
    timestamp_ms: int
    snapshot_key: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", normalize_venue(self.venue))
        start_asset = _asset_name(self.start_asset, name="start_asset")
        object.__setattr__(self, "start_asset", start_asset)
        route = tuple(_asset_name(asset, name="route asset") for asset in self.route)
        if len(route) != 4 or route[0] != route[-1]:
            raise ValueError("route must contain A -> B -> C -> A")
        if len(set(route[:3])) != 3 or route[0] != start_asset:
            raise ValueError("route must contain exactly three distinct assets")
        object.__setattr__(self, "route", route)
        legs = tuple(self.legs)
        if len(legs) != 3 or not all(isinstance(leg, TriangularLeg) for leg in legs):
            raise ValueError("opportunity must contain exactly three legs")
        for index, leg in enumerate(legs):
            if leg.venue != self.venue:
                raise ValueError("all triangular legs must use one venue")
            if (leg.from_asset, leg.to_asset) != (route[index], route[index + 1]):
                raise ValueError("legs must follow the opportunity route")
        if len({leg.symbol for leg in legs}) != 3:
            raise ValueError("triangular legs must use three distinct markets")
        object.__setattr__(self, "legs", legs)

        for name in (
            "start_amount",
            "gross_final_amount",
            "final_amount",
            "risk_buffer_cost",
            "gross_profit",
            "net_profit",
            "gross_edge",
            "net_edge",
        ):
            object.__setattr__(self, name, decimal_value(getattr(self, name), name=name))
        if self.start_amount <= ZERO or self.gross_final_amount <= ZERO or self.final_amount <= ZERO:
            raise ValueError("opportunity amounts must be greater than zero")
        if self.risk_buffer_cost < ZERO:
            raise ValueError("risk_buffer_cost must not be negative")
        object.__setattr__(self, "timestamp_ms", _timestamp(self.timestamp_ms))
        snapshot_key = str(self.snapshot_key).strip()
        if not snapshot_key:
            raise ValueError("snapshot_key must not be empty")
        object.__setattr__(self, "snapshot_key", snapshot_key)

    @property
    def symbols(self) -> tuple[str, str, str]:
        return tuple(leg.symbol for leg in self.legs)  # type: ignore[return-value]

    @property
    def route_text(self) -> str:
        return " -> ".join(self.route)

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "start_asset": self.start_asset,
            "route": list(self.route),
            "route_text": self.route_text,
            "symbols": list(self.symbols),
            "legs": [leg.to_dict() for leg in self.legs],
            "start_amount": decimal_string(self.start_amount),
            "gross_final_amount": decimal_string(self.gross_final_amount),
            "final_amount": decimal_string(self.final_amount),
            "risk_buffer_cost": decimal_string(self.risk_buffer_cost),
            "gross_profit": decimal_string(self.gross_profit),
            "net_profit": decimal_string(self.net_profit),
            "gross_edge": decimal_string(self.gross_edge),
            "net_edge": decimal_string(self.net_edge),
            "timestamp_ms": self.timestamp_ms,
            "snapshot_key": self.snapshot_key,
        }


@dataclass(frozen=True, slots=True)
class _ConversionEdge:
    ticker: MarketTicker
    from_asset: str
    to_asset: str
    side: str
    raw_rate: Decimal
    capacity_input: Decimal


def _ticker_edges(ticker: MarketTicker) -> tuple[_ConversionEdge, _ConversionEdge]:
    # Selling base consumes the best bid size.  Buying base consumes the best
    # ask size, whose equivalent input capacity is expressed in quote units.
    return (
        _ConversionEdge(
            ticker=ticker,
            from_asset=ticker.base_asset,
            to_asset=ticker.quote_asset,
            side="sell",
            raw_rate=ticker.bid,
            capacity_input=ticker.bid_size,
        ),
        _ConversionEdge(
            ticker=ticker,
            from_asset=ticker.quote_asset,
            to_asset=ticker.base_asset,
            side="buy",
            raw_rate=ONE / ticker.ask,
            capacity_input=ticker.ask * ticker.ask_size,
        ),
    )


def ticker_snapshot_key(
    tickers: Iterable[MarketTicker],
    *,
    route: Sequence[str] | None = None,
) -> str:
    """Return a deterministic key suitable for duplicate-snapshot guards."""

    normalized: list[MarketTicker] = []
    for ticker in tickers:
        if not isinstance(ticker, MarketTicker):
            raise TypeError("tickers must contain MarketTicker instances")
        normalized.append(ticker)
    if not normalized:
        raise ValueError("at least one ticker is required")
    tokens = sorted(
        f"{ticker.venue}:{ticker.symbol}:"
        f"{ticker.snapshot_id if ticker.snapshot_id is not None else ticker.timestamp_ms}"
        for ticker in normalized
    )
    route_token = ""
    if route is not None:
        normalized_route = tuple(_asset_name(asset, name="route asset") for asset in route)
        route_token = ">".join(normalized_route) + "|"
    return route_token + "|".join(tokens)


class TriangularEngine:
    """Discover executable ``A -> B -> C -> A`` paths on each venue."""

    def __init__(self, config: TriangularConfig | None = None) -> None:
        self.config = config or TriangularConfig()

    def scan(
        self,
        tickers: Iterable[MarketTicker],
        *,
        start_asset: str,
        start_amount: Decimal | str | int | float | None = None,
        venue: str | None = None,
        now_ms: int | None = None,
    ) -> list[TriangularOpportunity]:
        start = _asset_name(start_asset, name="start_asset")
        requested = (
            self.config.max_start_amount
            if start_amount is None
            else decimal_value(start_amount, name="start_amount")
        )
        if requested <= ZERO:
            raise ValueError("start_amount must be greater than zero")
        requested = min(requested, self.config.max_start_amount)
        venue_filter = normalize_venue(venue) if venue is not None else None

        latest: dict[tuple[str, str], MarketTicker] = {}
        for ticker in tickers:
            if not isinstance(ticker, MarketTicker):
                raise TypeError("tickers must contain MarketTicker instances")
            if venue_filter is not None and ticker.venue != venue_filter:
                continue
            key = (ticker.venue, ticker.symbol)
            existing = latest.get(key)
            if existing is None or (
                ticker.timestamp_ms,
                ticker.snapshot_id or "",
            ) > (
                existing.timestamp_ms,
                existing.snapshot_id or "",
            ):
                latest[key] = ticker
        if not latest:
            return []

        reference_ms = (
            max(ticker.timestamp_ms for ticker in latest.values())
            if now_ms is None
            else _timestamp(now_ms, name="now_ms")
        )
        by_venue: dict[str, list[MarketTicker]] = {}
        for ticker in latest.values():
            if (
                self.config.max_staleness_ms is not None
                and reference_ms - ticker.timestamp_ms > self.config.max_staleness_ms
            ):
                continue
            by_venue.setdefault(ticker.venue, []).append(ticker)

        opportunities: list[TriangularOpportunity] = []
        for venue_name in sorted(by_venue):
            graph: dict[str, list[_ConversionEdge]] = {}
            for ticker in sorted(by_venue[venue_name], key=lambda item: item.symbol):
                for edge in _ticker_edges(ticker):
                    graph.setdefault(edge.from_asset, []).append(edge)

            seen: set[tuple[tuple[str, str, str, str], tuple[str, str, str]]] = set()
            for first in graph.get(start, ()):
                middle = first.to_asset
                if middle == start:
                    continue
                for second in graph.get(middle, ()):
                    last = second.to_asset
                    if len({start, middle, last}) != 3:
                        continue
                    for third in graph.get(last, ()):
                        if third.to_asset != start:
                            continue
                        edges = (first, second, third)
                        symbols = tuple(edge.ticker.symbol for edge in edges)
                        if len(set(symbols)) != 3:
                            continue
                        timestamps = tuple(
                            edge.ticker.timestamp_ms for edge in edges
                        )
                        if (
                            self.config.max_leg_skew_ms is not None
                            and max(timestamps) - min(timestamps)
                            > self.config.max_leg_skew_ms
                        ):
                            continue
                        route = (start, middle, last, start)
                        dedupe_key = (route, symbols)
                        if dedupe_key in seen:
                            continue
                        seen.add(dedupe_key)
                        opportunity = self._evaluate_route(
                            venue_name,
                            route,
                            edges,
                            requested,
                        )
                        if opportunity is not None:
                            opportunities.append(opportunity)

        return sorted(
            opportunities,
            key=lambda item: (
                -item.net_profit,
                -item.net_edge,
                item.venue,
                item.route,
                item.symbols,
            ),
        )

    scan_opportunities = scan

    def _evaluate_route(
        self,
        venue: str,
        route: tuple[str, str, str, str],
        edges: tuple[_ConversionEdge, _ConversionEdge, _ConversionEdge],
        requested: Decimal,
    ) -> TriangularOpportunity | None:
        fee_rate = self.config.fee_for(venue)
        effective_rates = tuple(edge.raw_rate * (ONE - fee_rate) for edge in edges)

        # Express each downstream input capacity back in start-asset units.
        start_limit = min(
            requested,
            edges[0].capacity_input,
            edges[1].capacity_input / effective_rates[0],
            edges[2].capacity_input / (effective_rates[0] * effective_rates[1]),
        )
        if start_limit <= ZERO:
            return None

        # Decimal division may round an analytically exact downstream bound a
        # few ULPs upward.  Re-run the same two-step fee calculation used for
        # the actual legs and move the start size just below any observed
        # violation.  The proportional correction converges immediately in
        # normal contexts while avoiding a partial top-of-book fill.
        for _ in range(16):
            route_amount = start_limit
            correction = ONE
            for edge in edges:
                if route_amount > edge.capacity_input:
                    correction = min(
                        correction,
                        edge.capacity_input / route_amount,
                    )
                raw_output = route_amount * edge.raw_rate
                route_amount = raw_output - raw_output * fee_rate
            if correction == ONE:
                break
            corrected = start_limit * correction
            start_limit = (
                corrected if corrected < start_limit else start_limit
            ).next_minus()
            if start_limit <= ZERO:
                return None
        else:
            # A non-standard Decimal context should not turn a quote into a
            # knowingly over-capacity opportunity.
            return None

        amount = start_limit
        legs: list[TriangularLeg] = []
        for edge in edges:
            raw_output = amount * edge.raw_rate
            fee = raw_output * fee_rate
            output = raw_output - fee
            legs.append(
                TriangularLeg(
                    venue=venue,
                    symbol=edge.ticker.symbol,
                    from_asset=edge.from_asset,
                    to_asset=edge.to_asset,
                    side=edge.side,
                    price=edge.ticker.bid if edge.side == "sell" else edge.ticker.ask,
                    input_amount=amount,
                    output_before_fee=raw_output,
                    fee=fee,
                    output_amount=output,
                    capacity_input=edge.capacity_input,
                    timestamp_ms=edge.ticker.timestamp_ms,
                    snapshot_id=edge.ticker.snapshot_id,
                )
            )
            amount = output

        gross_final = start_limit
        for edge in edges:
            gross_final *= edge.raw_rate
        gross_profit = gross_final - start_limit
        risk_buffer_cost = start_limit * self.config.risk_buffer
        net_profit = amount - start_limit - risk_buffer_cost
        gross_edge = gross_profit / start_limit
        net_edge = net_profit / start_limit
        if net_profit <= ZERO or net_edge < self.config.min_net_edge:
            return None

        ticker_tuple = tuple(edge.ticker for edge in edges)
        return TriangularOpportunity(
            venue=venue,
            start_asset=route[0],
            route=route,
            legs=tuple(legs),  # type: ignore[arg-type]
            start_amount=start_limit,
            gross_final_amount=gross_final,
            final_amount=amount,
            risk_buffer_cost=risk_buffer_cost,
            gross_profit=gross_profit,
            net_profit=net_profit,
            gross_edge=gross_edge,
            net_edge=net_edge,
            timestamp_ms=max(edge.ticker.timestamp_ms for edge in edges),
            snapshot_key=ticker_snapshot_key(ticker_tuple, route=route),
        )


def _liquidity_key(ticker: MarketTicker) -> tuple[Decimal, Decimal, str, str]:
    return (-ticker.volume_usdt, -ticker.quote_volume, ticker.venue, ticker.symbol)


def _best_pair_ticker(tickers: Sequence[MarketTicker]) -> MarketTicker:
    return sorted(tickers, key=_liquidity_key)[0]


def select_liquid_tickers(
    tickers: Iterable[MarketTicker],
    *,
    max_tickers: int = 50,
    start_asset: str = "USDT",
) -> list[MarketTicker]:
    """Select at most 50 liquid markets without breaking chosen triangles.

    Complete cycles containing ``start_asset`` are packed first, followed by
    other complete high-liquidity cycles.  Any remaining slots are filled by
    the most liquid individual markets.  The function is venue-aware: a
    triangle is never assembled from markets belonging to different venues.
    """

    if isinstance(max_tickers, bool):
        raise TypeError("max_tickers must be an integer")
    try:
        requested_limit = int(max_tickers)
    except (TypeError, ValueError) as exc:
        raise TypeError("max_tickers must be an integer") from exc
    if requested_limit <= 0:
        raise ValueError("max_tickers must be greater than zero")
    limit = min(requested_limit, 50)
    preferred_asset = _asset_name(start_asset, name="start_asset")

    latest: dict[tuple[str, str], MarketTicker] = {}
    for ticker in tickers:
        if not isinstance(ticker, MarketTicker):
            raise TypeError("tickers must contain MarketTicker instances")
        key = (ticker.venue, ticker.symbol)
        existing = latest.get(key)
        if existing is None or (
            ticker.timestamp_ms,
            ticker.snapshot_id or "",
        ) > (
            existing.timestamp_ms,
            existing.snapshot_id or "",
        ):
            latest[key] = ticker
    universe = list(latest.values())
    if len(universe) <= limit:
        return sorted(universe, key=_liquidity_key)

    pair_markets: dict[tuple[str, frozenset[str]], list[MarketTicker]] = {}
    adjacency: dict[str, dict[str, set[str]]] = {}
    for ticker in universe:
        pair = frozenset((ticker.base_asset, ticker.quote_asset))
        pair_markets.setdefault((ticker.venue, pair), []).append(ticker)
        venue_graph = adjacency.setdefault(ticker.venue, {})
        venue_graph.setdefault(ticker.base_asset, set()).add(ticker.quote_asset)
        venue_graph.setdefault(ticker.quote_asset, set()).add(ticker.base_asset)

    cycle_assets: set[tuple[str, str, str, str]] = set()
    for venue, graph in adjacency.items():
        for first in sorted(graph):
            for second in sorted(asset for asset in graph[first] if asset > first):
                for third in sorted(
                    asset
                    for asset in graph[first].intersection(graph.get(second, set()))
                    if asset > second
                ):
                    cycle_assets.add((venue, first, second, third))

    cycles: list[tuple[bool, Decimal, Decimal, tuple[MarketTicker, ...]]] = []
    for venue, first, second, third in cycle_assets:
        markets = tuple(
            _best_pair_ticker(pair_markets[(venue, frozenset(pair))])
            for pair in ((first, second), (second, third), (first, third))
        )
        volumes = tuple(ticker.volume_usdt for ticker in markets)
        cycles.append(
            (
                preferred_asset in {first, second, third},
                min(volumes),
                sum(volumes, ZERO),
                markets,
            )
        )
    cycles.sort(
        key=lambda item: (
            not item[0],
            -item[1],
            -item[2],
            tuple((ticker.venue, ticker.symbol) for ticker in item[3]),
        )
    )

    selected: dict[tuple[str, str], MarketTicker] = {}
    for _, _, _, cycle in cycles:
        new_markets = [
            ticker
            for ticker in cycle
            if (ticker.venue, ticker.symbol) not in selected
        ]
        if len(selected) + len(new_markets) <= limit:
            for ticker in new_markets:
                selected[(ticker.venue, ticker.symbol)] = ticker
        if len(selected) == limit:
            break

    for ticker in sorted(universe, key=_liquidity_key):
        if len(selected) == limit:
            break
        selected.setdefault((ticker.venue, ticker.symbol), ticker)
    return sorted(selected.values(), key=_liquidity_key)


class TriangularPaperExecutionError(RuntimeError):
    """Base error for rejected virtual triangular executions."""


class TriangularInsufficientBalanceError(TriangularPaperExecutionError):
    """Raised when the paper start-asset balance cannot fund a route."""


class TriangularPaperPortfolio:
    """Virtual per-venue balances used only by the triangular paper engine."""

    def __init__(
        self,
        initial_balances: Mapping[
            str,
            Mapping[str, Decimal | str | int | float],
        ]
        | None = None,
    ) -> None:
        normalized: dict[str, dict[str, Decimal]] = {}
        for venue, assets in (initial_balances or {}).items():
            normalized_venue = normalize_venue(venue)
            if not isinstance(assets, Mapping):
                raise TypeError("each venue balance must be an asset mapping")
            venue_balances = normalized.setdefault(normalized_venue, {})
            for asset, raw_amount in assets.items():
                normalized_asset = _asset_name(asset)
                amount = decimal_value(
                    raw_amount,
                    name=f"initial balance {normalized_asset}@{normalized_venue}",
                )
                if amount < ZERO:
                    raise ValueError("initial balances must not be negative")
                venue_balances[normalized_asset] = amount
        self._initial = {venue: dict(assets) for venue, assets in normalized.items()}
        self._balances = {venue: dict(assets) for venue, assets in normalized.items()}

    @property
    def balances(self) -> dict[str, dict[str, Decimal]]:
        return self.snapshot()

    def snapshot(self) -> dict[str, dict[str, Decimal]]:
        return {venue: dict(assets) for venue, assets in self._balances.items()}

    def balance(self, venue: str, asset: str) -> Decimal:
        return self._balances.get(normalize_venue(venue), {}).get(_asset_name(asset), ZERO)

    def deposit(
        self,
        venue: str,
        asset: str,
        amount: Decimal | str | int | float,
    ) -> None:
        value = decimal_value(amount, name="deposit amount")
        if value <= ZERO:
            raise ValueError("deposit amount must be greater than zero")
        proposed = self.snapshot()
        normalized_venue = normalize_venue(venue)
        normalized_asset = _asset_name(asset)
        balances = proposed.setdefault(normalized_venue, {})
        balances[normalized_asset] = balances.get(normalized_asset, ZERO) + value
        self._balances = proposed

    def reset(self) -> None:
        self._balances = {
            venue: dict(assets)
            for venue, assets in self._initial.items()
        }

    def to_dict(self) -> dict[str, Any]:
        return {"balances": _json_balances(self._balances)}

    def _round_trip(
        self,
        venue: str,
        asset: str,
        debit: Decimal,
        credit: Decimal,
    ) -> dict[str, dict[str, Decimal]]:
        proposed = self.snapshot()
        venue_balances = proposed.setdefault(venue, {})
        available = venue_balances.get(asset, ZERO)
        if available < debit:
            raise TriangularInsufficientBalanceError(
                f"insufficient {asset} on {venue}: required {debit}, available {available}"
            )
        venue_balances[asset] = available - debit + credit
        return proposed

    def _commit(self, proposed: dict[str, dict[str, Decimal]]) -> None:
        self._balances = proposed


@dataclass(frozen=True, slots=True)
class TriangularPaperExecution:
    execution_id: str
    timestamp_ms: int
    venue: str
    route: tuple[str, str, str, str]
    start_asset: str
    start_amount: Decimal
    final_amount: Decimal
    realized_pnl: Decimal
    expected_net_profit: Decimal
    legs: tuple[TriangularLeg, TriangularLeg, TriangularLeg]
    snapshot_key: str
    balances_after: Mapping[str, Mapping[str, Decimal]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "timestamp_ms": self.timestamp_ms,
            "venue": self.venue,
            "route": list(self.route),
            "route_text": " -> ".join(self.route),
            "start_asset": self.start_asset,
            "start_amount": decimal_string(self.start_amount),
            "final_amount": decimal_string(self.final_amount),
            "realized_pnl": decimal_string(self.realized_pnl),
            "expected_net_profit": decimal_string(self.expected_net_profit),
            "legs": [leg.to_dict() for leg in self.legs],
            "snapshot_key": self.snapshot_key,
            "balances_after": _json_balances(self.balances_after),
        }


class TriangularPaperExecutor:
    """Atomically execute an immutable opportunity against paper balances."""

    def __init__(self, portfolio: TriangularPaperPortfolio) -> None:
        if not isinstance(portfolio, TriangularPaperPortfolio):
            raise TypeError("portfolio must be a TriangularPaperPortfolio")
        self.portfolio = portfolio
        self.journal: list[TriangularPaperExecution] = []
        self.realized_pnl = ZERO

    def execute(
        self,
        opportunity: TriangularOpportunity,
        *,
        timestamp_ms: int | None = None,
    ) -> TriangularPaperExecution:
        if not isinstance(opportunity, TriangularOpportunity):
            raise TypeError("opportunity must be a TriangularOpportunity")
        proposed = self.portfolio._round_trip(
            opportunity.venue,
            opportunity.start_asset,
            opportunity.start_amount,
            opportunity.final_amount,
        )
        execution_timestamp = (
            opportunity.timestamp_ms
            if timestamp_ms is None
            else _timestamp(timestamp_ms)
        )
        realized = opportunity.final_amount - opportunity.start_amount
        execution = TriangularPaperExecution(
            execution_id=f"triangle-paper-{len(self.journal) + 1}",
            timestamp_ms=execution_timestamp,
            venue=opportunity.venue,
            route=opportunity.route,
            start_asset=opportunity.start_asset,
            start_amount=opportunity.start_amount,
            final_amount=opportunity.final_amount,
            realized_pnl=realized,
            expected_net_profit=opportunity.net_profit,
            legs=opportunity.legs,
            snapshot_key=opportunity.snapshot_key,
            balances_after={venue: dict(assets) for venue, assets in proposed.items()},
        )

        # Commit after all validation and object construction: a rejected
        # virtual trade cannot leave a partial intermediate-asset balance.
        self.portfolio._commit(proposed)
        self.journal.append(execution)
        self.realized_pnl += realized
        return execution

    execute_opportunity = execute

    def reset(self, *, reset_portfolio: bool = True) -> None:
        if reset_portfolio:
            self.portfolio.reset()
        self.journal.clear()
        self.realized_pnl = ZERO

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio": self.portfolio.to_dict(),
            "realized_pnl": decimal_string(self.realized_pnl),
            "journal": [execution.to_dict() for execution in self.journal],
        }


def scan_triangular_opportunities(
    tickers: Iterable[MarketTicker],
    config: TriangularConfig | None = None,
    *,
    start_asset: str,
    start_amount: Decimal | str | int | float | None = None,
    venue: str | None = None,
    now_ms: int | None = None,
) -> list[TriangularOpportunity]:
    """Functional convenience wrapper around :class:`TriangularEngine`."""

    return TriangularEngine(config).scan(
        tickers,
        start_asset=start_asset,
        start_amount=start_amount,
        venue=venue,
        now_ms=now_ms,
    )


__all__ = [
    "MarketTicker",
    "TriangularConfig",
    "TriangularEngine",
    "TriangularInsufficientBalanceError",
    "TriangularLeg",
    "TriangularOpportunity",
    "TriangularPaperExecution",
    "TriangularPaperExecutionError",
    "TriangularPaperExecutor",
    "TriangularPaperPortfolio",
    "scan_triangular_opportunities",
    "select_liquid_tickers",
    "ticker_snapshot_key",
]
