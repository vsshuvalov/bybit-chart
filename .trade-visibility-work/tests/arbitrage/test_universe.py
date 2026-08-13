from __future__ import annotations

import json
from decimal import Decimal
from random import Random

import pytest

from packages.arbitrage.triangular import MarketTicker
from packages.arbitrage.universe import select_cross_venue_universe


pytestmark = pytest.mark.contract


def ticker(
    venue: str,
    base: str,
    *,
    quote: str = "USDT",
    volume: str = "1000000",
    change: str = "1",
    timestamp_ms: int = 100,
) -> MarketTicker:
    return MarketTicker(
        venue=venue,
        symbol=f"{base}{quote}",
        base_asset=base,
        quote_asset=quote,
        timestamp_ms=timestamp_ms,
        bid="1",
        ask="1.01",
        bid_size="1000",
        ask_size="1000",
        quote_volume=volume,
        volume_usdt=Decimal(volume),
        change_24h_pct=Decimal(change),
        snapshot_id=f"{venue}-{base}-{timestamp_ms}",
    )


def common(*items: tuple[str, str, str]) -> dict[str, list[MarketTicker]]:
    result: dict[str, list[MarketTicker]] = {"bybit": [], "binance": []}
    for base, volume, change in items:
        result["bybit"].append(ticker("bybit", base, volume=volume, change=change))
        result["binance"].append(ticker("binance", base, volume=volume, change=change))
    return result


def test_more_volatile_symbol_wins_inside_liquid_pool() -> None:
    selected = select_cross_venue_universe(
        common(
            ("CALM", "3000000", "1"),
            ("FAST", "2000000", "-8"),
            ("MID", "1000000", "4"),
        ),
        max_symbols=2,
        liquidity_pool_size=3,
        min_liquidity_usdt=0,
    )

    assert [item.symbol for item in selected] == ["FASTUSDT", "MIDUSDT"]
    assert selected[0].volatility_24h_pct == Decimal("8")


def test_illiquid_pump_is_excluded_before_volatility_ranking() -> None:
    selected = select_cross_venue_universe(
        common(
            ("DEEP", "3000000", "2"),
            ("ACTIVE", "2000000", "5"),
            ("PUMP", "10", "900"),
        ),
        max_symbols=2,
        liquidity_pool_size=2,
        min_liquidity_usdt=0,
    )

    assert [item.symbol for item in selected] == ["ACTIVEUSDT", "DEEPUSDT"]


def test_requires_common_positive_volume_markets_and_requested_quote() -> None:
    tickers = common(("GOOD", "1000", "3"))
    tickers["bybit"].extend(
        [
            ticker("bybit", "SINGLE", volume="5000", change="50"),
            ticker("bybit", "EURO", quote="EUR", volume="5000", change="50"),
            ticker("bybit", "ZERO", volume="0", change="50"),
        ]
    )
    tickers["binance"].extend(
        [
            ticker("binance", "EURO", quote="EUR", volume="5000", change="50"),
            ticker("binance", "ZERO", volume="0", change="50"),
        ]
    )

    selected = select_cross_venue_universe(tickers, min_liquidity_usdt=0)

    assert [item.symbol for item in selected] == ["GOODUSDT"]
    assert selected[0].venue_count == 2
    assert selected[0].venues == ("binance", "bybit")
    assert selected[0].quote_asset == "USDT"
    json.dumps(selected[0].to_dict())


def test_uses_latest_ticker_per_venue_and_median_absolute_change() -> None:
    tickers = {
        "bybit": [
            ticker("bybit", "COIN", volume="9999999", change="99", timestamp_ms=1),
            ticker("bybit", "COIN", volume="400", change="-2", timestamp_ms=2),
        ],
        "binance": [ticker("binance", "COIN", volume="500", change="4")],
        "okx": [ticker("okx", "COIN", volume="600", change="100")],
    }

    selected = select_cross_venue_universe(tickers, min_liquidity_usdt=0)

    assert selected[0].liquidity_usdt == Decimal("400")
    assert selected[0].volatility_24h_pct == Decimal("4")


def test_caps_result_at_50_and_is_deterministic() -> None:
    original = common(
        *((f"C{index:03d}", str(100000 - index), str(index % 17)) for index in range(70))
    )
    shuffled = {venue: list(items) for venue, items in original.items()}
    random = Random(42)
    for items in shuffled.values():
        random.shuffle(items)

    first = select_cross_venue_universe(
        original,
        max_symbols=999,
        liquidity_pool_size=150,
        min_liquidity_usdt=0,
    )
    second = select_cross_venue_universe(
        shuffled,
        max_symbols=999,
        liquidity_pool_size=150,
        min_liquidity_usdt=0,
    )

    assert len(first) == 50
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]


def test_ties_use_conservative_liquidity_then_symbol() -> None:
    selected = select_cross_venue_universe(
        common(
            ("ZZZ", "1000", "5"),
            ("AAA", "1000", "5"),
            ("MMM", "2000", "5"),
        ),
        min_liquidity_usdt=0,
    )

    assert [item.symbol for item in selected] == [
        "MMMUSDT",
        "AAAUSDT",
        "ZZZUSDT",
    ]


def test_default_absolute_liquidity_floor_excludes_thin_markets() -> None:
    selected = select_cross_venue_universe(
        common(
            ("LIQUID", "500000", "4"),
            ("THIN", "499999", "100"),
        )
    )

    assert [item.symbol for item in selected] == ["LIQUIDUSDT"]


def test_thin_extra_listing_does_not_disqualify_two_liquid_venues() -> None:
    tickers = common(("GOOD", "1000000", "6"))
    tickers["okx"] = [
        ticker("okx", "GOOD", volume="10", change="900")
    ]

    selected = select_cross_venue_universe(tickers)

    assert [item.symbol for item in selected] == ["GOODUSDT"]
    assert selected[0].venues == ("binance", "bybit")
    assert selected[0].venue_count == 2
    assert selected[0].liquidity_usdt == Decimal("1000000")
    assert selected[0].volatility_24h_pct == Decimal("6")
