"""Liquidity-gated volatile universe selection for cross-venue scanning.

The selector deliberately separates *eligibility* from *ranking*: a market
must first be common to multiple venues and make a conservative liquidity
pool before its 24-hour move can improve its rank.  That prevents a thin,
one-off price spike from displacing executable markets.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping

from packages.arbitrage.models import (
    ZERO,
    decimal_string,
    decimal_value,
    normalize_symbol,
    normalize_venue,
)
from packages.arbitrage.triangular import MarketTicker


def _asset_name(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _positive_integer(value: int, *, name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be an integer") from exc
    if result <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return result


def _median(values: Iterable[Decimal]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


@dataclass(frozen=True, slots=True)
class CrossVenueSymbolStats:
    """Selection metadata for one symbol shared by multiple venues."""

    symbol: str
    base_asset: str
    quote_asset: str
    venue_count: int
    venues: tuple[str, ...]
    liquidity_usdt: Decimal
    volatility_24h_pct: Decimal

    def __post_init__(self) -> None:
        symbol = normalize_symbol(self.symbol)
        base_asset = _asset_name(self.base_asset, name="base_asset")
        quote_asset = _asset_name(self.quote_asset, name="quote_asset")
        if base_asset == quote_asset:
            raise ValueError("base_asset and quote_asset must differ")

        venues = tuple(sorted({normalize_venue(venue) for venue in self.venues}))
        if isinstance(self.venue_count, bool):
            raise TypeError("venue_count must be an integer")
        try:
            venue_count = int(self.venue_count)
        except (TypeError, ValueError) as exc:
            raise TypeError("venue_count must be an integer") from exc
        if venue_count != len(venues):
            raise ValueError("venue_count must match the number of unique venues")
        if venue_count < 2:
            raise ValueError("a cross-venue symbol requires at least two venues")

        liquidity = decimal_value(self.liquidity_usdt, name="liquidity_usdt")
        volatility = decimal_value(
            self.volatility_24h_pct,
            name="volatility_24h_pct",
        )
        if liquidity <= ZERO:
            raise ValueError("liquidity_usdt must be greater than zero")
        if volatility < ZERO:
            raise ValueError("volatility_24h_pct must not be negative")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "base_asset", base_asset)
        object.__setattr__(self, "quote_asset", quote_asset)
        object.__setattr__(self, "venue_count", venue_count)
        object.__setattr__(self, "venues", venues)
        object.__setattr__(self, "liquidity_usdt", liquidity)
        object.__setattr__(self, "volatility_24h_pct", volatility)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation without float precision loss."""

        return {
            "symbol": self.symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "venue_count": self.venue_count,
            "venues": list(self.venues),
            "liquidity_usdt": decimal_string(self.liquidity_usdt),
            "volatility_24h_pct": decimal_string(self.volatility_24h_pct),
        }


def _ticker_recency(ticker: MarketTicker) -> tuple[int, str]:
    return (ticker.timestamp_ms, ticker.snapshot_id or "")


def select_cross_venue_universe(
    tickers_by_venue: Mapping[str, Iterable[MarketTicker]],
    max_symbols: int = 50,
    liquidity_pool_size: int = 150,
    quote_asset: str = "USDT",
    min_venues: int = 2,
    min_liquidity_usdt: Decimal | str | int | float = Decimal("500000"),
) -> list[CrossVenueSymbolStats]:
    """Return a liquid, cross-venue universe ranked by recent volatility.

    A venue participates only when its normalized 24-hour USDT volume clears
    the absolute liquidity floor.  The symbol's score is the minimum volume
    among those qualifying venues; a stray thin listing therefore cannot
    disqualify an otherwise executable cross-venue pair.  Volatility is the
    median absolute 24-hour percentage change across the qualifying venues,
    making the rank less sensitive to one venue's bad print.  At most 50
    symbols are returned even if a larger limit is supplied.
    """

    if not isinstance(tickers_by_venue, Mapping):
        raise TypeError("tickers_by_venue must be a mapping")
    requested_limit = _positive_integer(max_symbols, name="max_symbols")
    limit = min(requested_limit, 50)
    pool_limit = _positive_integer(
        liquidity_pool_size,
        name="liquidity_pool_size",
    )
    required_venues = _positive_integer(min_venues, name="min_venues")
    if required_venues < 2:
        raise ValueError("min_venues must be at least 2")
    wanted_quote = _asset_name(quote_asset, name="quote_asset")
    minimum_liquidity = decimal_value(
        min_liquidity_usdt,
        name="min_liquidity_usdt",
    )
    if minimum_liquidity < ZERO:
        raise ValueError("min_liquidity_usdt must not be negative")

    latest: dict[tuple[str, str], MarketTicker] = {}
    for venue_hint, venue_tickers in tickers_by_venue.items():
        # Validate mapping keys even though the normalized ticker venue is the
        # source of truth.  This catches malformed inputs without making a
        # harmless alias/casing difference affect the result.
        normalize_venue(venue_hint)
        for ticker in venue_tickers:
            venue = normalize_venue(ticker.venue)
            symbol = normalize_symbol(ticker.symbol)
            key = (venue, symbol)
            existing = latest.get(key)
            if existing is None or _ticker_recency(ticker) > _ticker_recency(existing):
                latest[key] = ticker

    grouped: dict[tuple[str, str, str], dict[str, MarketTicker]] = {}
    for (venue, symbol), ticker in latest.items():
        ticker_quote = _asset_name(ticker.quote_asset, name="ticker quote_asset")
        if ticker_quote != wanted_quote:
            continue
        volume = decimal_value(ticker.volume_usdt, name="volume_usdt")
        if volume <= ZERO:
            continue
        base = _asset_name(ticker.base_asset, name="ticker base_asset")
        grouped.setdefault((symbol, base, ticker_quote), {})[venue] = ticker

    eligible: list[CrossVenueSymbolStats] = []
    for (symbol, base, ticker_quote), venue_tickers in grouped.items():
        qualified_tickers = {
            venue: ticker
            for venue, ticker in venue_tickers.items()
            if decimal_value(ticker.volume_usdt, name="volume_usdt")
            >= minimum_liquidity
        }
        if len(qualified_tickers) < required_venues:
            continue
        liquidity = min(
            decimal_value(ticker.volume_usdt, name="volume_usdt")
            for ticker in qualified_tickers.values()
        )
        changes = (
            abs(
                decimal_value(
                    getattr(ticker, "change_24h_pct", ZERO),
                    name="change_24h_pct",
                )
            )
            for ticker in qualified_tickers.values()
        )
        eligible.append(
            CrossVenueSymbolStats(
                symbol=symbol,
                base_asset=base,
                quote_asset=ticker_quote,
                venue_count=len(qualified_tickers),
                venues=tuple(qualified_tickers),
                liquidity_usdt=liquidity,
                volatility_24h_pct=_median(changes),
            )
        )

    liquid_pool = sorted(
        eligible,
        key=lambda item: (-item.liquidity_usdt, item.symbol),
    )[: min(pool_limit, len(eligible))]
    return sorted(
        liquid_pool,
        key=lambda item: (
            -item.volatility_24h_pct,
            -item.liquidity_usdt,
            item.symbol,
        ),
    )[:limit]


__all__ = ["CrossVenueSymbolStats", "select_cross_venue_universe"]
