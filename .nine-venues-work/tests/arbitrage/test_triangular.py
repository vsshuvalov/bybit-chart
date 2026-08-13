from __future__ import annotations

import json
from decimal import Decimal

import pytest

from packages.arbitrage.triangular import (
    MarketTicker,
    TriangularConfig,
    TriangularEngine,
    TriangularInsufficientBalanceError,
    TriangularPaperExecutor,
    TriangularPaperPortfolio,
    select_liquid_tickers,
    ticker_snapshot_key,
)


pytestmark = pytest.mark.contract

D = Decimal


def ticker(
    symbol: str,
    base: str,
    quote: str,
    *,
    venue: str = "demo",
    bid: str,
    ask: str,
    bid_size: str = "1000000",
    ask_size: str = "1000000",
    volume: str = "1000000",
    timestamp_ms: int = 1_000,
    snapshot_id: str | None = None,
) -> MarketTicker:
    return MarketTicker(
        venue=venue,
        symbol=symbol,
        base_asset=base,
        quote_asset=quote,
        timestamp_ms=timestamp_ms,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        quote_volume=volume,
        volume_usdt=volume,
        snapshot_id=snapshot_id or f"{symbol}-{timestamp_ms}",
    )


def profitable_triangle(
    *,
    venue: str = "demo",
    first_ask_size: str = "1000000",
    second_ask_size: str = "1000000",
    third_bid_size: str = "1000000",
) -> list[MarketTicker]:
    # USDT -> BTC buys BTCUSDT; BTC -> ETH buys ETHBTC; ETH -> USDT sells
    # ETHUSDT.  Raw round-trip multiplier = 1/10 * 1/0.5 * 6 = 1.2.
    return [
        ticker(
            "BTCUSDT",
            "BTC",
            "USDT",
            venue=venue,
            bid="9.9",
            ask="10",
            ask_size=first_ask_size,
        ),
        ticker(
            "ETHBTC",
            "ETH",
            "BTC",
            venue=venue,
            bid="0.49",
            ask="0.5",
            ask_size=second_ask_size,
        ),
        ticker(
            "ETHUSDT",
            "ETH",
            "USDT",
            venue=venue,
            bid="6",
            ask="6.1",
            bid_size=third_bid_size,
        ),
    ]


def test_market_ticker_normalizes_and_serializes_decimals_as_strings() -> None:
    item = MarketTicker(
        " ByBit ",
        "btc/usdt",
        " btc ",
        "usdt",
        123,
        "9.9",
        "10",
        "2",
        "3",
        "500",
        "500",
        "snapshot-1",
        "-3.25",
    )

    assert item.venue == "bybit"
    assert item.symbol == "BTCUSDT"
    assert item.base_asset == "BTC"
    assert item.mid_price == D("9.95")
    assert item.to_dict()["ask_size"] == "3"
    assert item.to_dict()["change_24h_pct"] == "-3.25"
    json.dumps(item.to_dict())


def test_market_ticker_rejects_locked_top_of_book() -> None:
    with pytest.raises(ValueError, match="positive bid/ask spread"):
        ticker("BTCUSDT", "BTC", "USDT", bid="10", ask="10")


def test_triangle_uses_both_market_orientations_and_returns_to_start() -> None:
    opportunities = TriangularEngine().scan(
        profitable_triangle(),
        start_asset="USDT",
        start_amount="100",
        now_ms=1_000,
    )

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.route == ("USDT", "BTC", "ETH", "USDT")
    assert [leg.side for leg in opportunity.legs] == ["buy", "buy", "sell"]
    assert [leg.input_amount for leg in opportunity.legs] == [
        D("100"),
        D("10"),
        D("2E+1"),
    ]
    assert opportunity.gross_final_amount == D("120")
    assert opportunity.final_amount == D("120")
    assert opportunity.net_profit == D("20")
    assert opportunity.net_edge == D("0.2")
    assert all(isinstance(item, str) for item in (
        opportunity.to_dict()["start_amount"],
        opportunity.to_dict()["net_profit"],
        opportunity.to_dict()["net_edge"],
    ))
    json.dumps(opportunity.to_dict())


def test_taker_fee_is_applied_to_each_of_all_three_outputs() -> None:
    config = TriangularConfig(
        taker_fees={"demo": "0.01"},
        max_start_amount="100",
    )

    opportunity = TriangularEngine(config).scan(
        profitable_triangle(),
        start_asset="USDT",
        start_amount="100",
        now_ms=1_000,
    )[0]

    assert [leg.fee for leg in opportunity.legs] == [
        D("0.10"),
        D("0.198"),
        D("1.17612"),
    ]
    assert opportunity.gross_final_amount == D("120")
    assert opportunity.final_amount == D("116.43588")
    assert opportunity.net_profit == D("16.43588")
    assert opportunity.net_edge == D("0.1643588")


def test_three_fees_and_risk_buffer_can_remove_a_raw_opportunity() -> None:
    barely_profitable = [
        ticker("BTCUSDT", "BTC", "USDT", bid="9.9", ask="10"),
        ticker("ETHBTC", "ETH", "BTC", bid="0.49", ask="0.5"),
        # Raw multiplier is 1.02, but three 1% fees make it unprofitable.
        ticker("ETHUSDT", "ETH", "USDT", bid="5.1", ask="5.2"),
    ]
    fee_engine = TriangularEngine(
        TriangularConfig(default_taker_fee="0.01")
    )

    assert fee_engine.scan(
        barely_profitable,
        start_asset="USDT",
        start_amount="100",
        now_ms=1_000,
    ) == []

    # A 19% buffer also rejects the otherwise 20%-gross fixture.
    buffered = TriangularEngine(TriangularConfig(risk_buffer="0.19"))
    assert buffered.scan(
        profitable_triangle(),
        start_asset="USDT",
        start_amount="100",
        now_ms=1_000,
    )[0].net_edge == D("0.01")
    assert TriangularEngine(
        TriangularConfig(risk_buffer="0.19", min_net_edge="0.011")
    ).scan(
        profitable_triangle(),
        start_asset="USDT",
        start_amount="100",
        now_ms=1_000,
    ) == []


@pytest.mark.parametrize(
    ("first_ask_size", "second_ask_size", "third_bid_size", "expected"),
    [
        ("4", "1000000", "1000000", "40"),
        ("1000000", "10", "1000000", "50"),
        ("1000000", "1000000", "8", "40"),
    ],
)
def test_size_is_capped_by_every_top_of_book_leg(
    first_ask_size: str,
    second_ask_size: str,
    third_bid_size: str,
    expected: str,
) -> None:
    opportunity = TriangularEngine(
        TriangularConfig(max_start_amount="1000")
    ).scan(
        profitable_triangle(
            first_ask_size=first_ask_size,
            second_ask_size=second_ask_size,
            third_bid_size=third_bid_size,
        ),
        start_asset="USDT",
        start_amount="100",
        now_ms=1_000,
    )[0]

    assert opportunity.start_amount == D(expected)
    assert all(leg.input_amount <= leg.capacity_input for leg in opportunity.legs)


def test_capacity_sizing_is_conservative_at_decimal_rounding_boundary() -> None:
    # This route's second-leg reverse division rounds the analytical start
    # bound upward by one ULP in the default Decimal context.  It must be
    # adjusted, not rejected or emitted above the executable ask capacity.
    ask_one = D("7.7856598")
    ask_two = D("0.0692274")
    bid_three = D("0.646777182286224")
    markets = [
        ticker(
            "AS",
            "A",
            "S",
            bid=str(ask_one * D("0.99")),
            ask=str(ask_one),
            ask_size="544196.43",
        ),
        ticker(
            "CA",
            "C",
            "A",
            bid=str(ask_two * D("0.99")),
            ask=str(ask_two),
            ask_size="157.15498",
        ),
        ticker(
            "CS",
            "C",
            "S",
            bid=str(bid_three),
            ask=str(bid_three * D("1.01")),
            bid_size="287015.56",
        ),
    ]

    opportunity = TriangularEngine(
        TriangularConfig(
            default_taker_fee="0.00067",
            max_start_amount="1e20",
        )
    ).scan(
        markets,
        start_asset="S",
        start_amount="1e20",
        now_ms=1_000,
    )[0]

    assert all(leg.input_amount <= leg.capacity_input for leg in opportunity.legs)


def test_scanner_rejects_two_market_and_repeated_asset_false_cycles() -> None:
    incomplete = [
        ticker("BTCUSDT", "BTC", "USDT", bid="9.9", ask="10"),
        ticker("ETHBTC", "ETH", "BTC", bid="0.49", ask="0.5"),
    ]
    assert TriangularEngine().scan(
        incomplete,
        start_asset="USDT",
        start_amount="100",
        now_ms=1_000,
    ) == []

    # A direct pair cannot be traversed back and forth to masquerade as a
    # three-asset cycle, even if the same symbol is repeated in the input.
    duplicates = [incomplete[0], incomplete[0], incomplete[0]]
    assert TriangularEngine().scan(
        duplicates,
        start_asset="USDT",
        start_amount="100",
        now_ms=1_000,
    ) == []


def test_scanner_is_venue_local_fresh_and_sorted_by_profit_then_edge() -> None:
    large_lower_edge = [
        ticker("BTCUSDT", "BTC", "USDT", venue="large", bid="9.9", ask="10"),
        ticker("ETHBTC", "ETH", "BTC", venue="large", bid="0.49", ask="0.5"),
        ticker(
            "ETHUSDT",
            "ETH",
            "USDT",
            venue="large",
            bid="5.5",
            ask="5.6",
        ),
    ]
    small_higher_edge = profitable_triangle(
        venue="small",
        first_ask_size="1",
    )
    results = TriangularEngine().scan(
        [*small_higher_edge, *large_lower_edge],
        start_asset="USDT",
        start_amount="100",
        now_ms=1_000,
    )

    assert [item.venue for item in results] == ["large", "small"]
    assert results[0].net_profit == D("10")
    assert results[0].net_edge == D("0.1")
    assert results[1].net_profit == D("2")
    assert results[1].net_edge == D("0.2")
    assert TriangularEngine(TriangularConfig(max_staleness_ms=10)).scan(
        profitable_triangle(),
        start_asset="USDT",
        start_amount="100",
        now_ms=1_011,
    ) == []


def test_scanner_rejects_three_leg_timestamps_with_excessive_skew() -> None:
    markets = profitable_triangle()
    skewed = [
        markets[0],
        ticker(
            markets[1].symbol,
            markets[1].base_asset,
            markets[1].quote_asset,
            bid=str(markets[1].bid),
            ask=str(markets[1].ask),
            timestamp_ms=3_001,
        ),
        ticker(
            markets[2].symbol,
            markets[2].base_asset,
            markets[2].quote_asset,
            bid=str(markets[2].bid),
            ask=str(markets[2].ask),
            timestamp_ms=3_000,
        ),
    ]
    engine = TriangularEngine(
        TriangularConfig(max_staleness_ms=10_000, max_leg_skew_ms=2_000)
    )

    assert engine.scan(
        skewed,
        start_asset="USDT",
        start_amount="100",
        now_ms=3_001,
    ) == []


def test_universe_prefers_complete_start_asset_cycle_and_never_exceeds_50() -> None:
    preferred = [
        ticker("BTCUSDT", "BTC", "USDT", bid="9", ask="10", volume="10"),
        ticker("ETHBTC", "ETH", "BTC", bid="0.4", ask="0.5", volume="10"),
        ticker("ETHUSDT", "ETH", "USDT", bid="6", ask="7", volume="10"),
    ]
    much_more_liquid_nonpreferred = [
        ticker("XY", "X", "Y", bid="1", ask="1.1", volume="100000"),
        ticker("YZ", "Y", "Z", bid="1", ask="1.1", volume="100000"),
        ticker("XZ", "X", "Z", bid="1", ask="1.1", volume="100000"),
    ]

    chosen_three = select_liquid_tickers(
        [*preferred, *much_more_liquid_nonpreferred],
        max_tickers=3,
        start_asset="USDT",
    )
    assert {item.symbol for item in chosen_three} == {
        "BTCUSDT",
        "ETHBTC",
        "ETHUSDT",
    }

    isolated = [
        ticker(
            f"COIN{index}USDT",
            f"COIN{index}",
            "USDT",
            bid="1",
            ask="1.1",
            volume=str(1_000 - index),
        )
        for index in range(57)
    ]
    chosen_fifty = select_liquid_tickers(
        [*preferred, *isolated],
        max_tickers=500,
        start_asset="USDT",
    )
    assert len(chosen_fifty) == 50
    assert {item.symbol for item in preferred}.issubset(
        {item.symbol for item in chosen_fifty}
    )


def test_snapshot_key_is_deterministic_and_route_specific() -> None:
    markets = profitable_triangle()

    first = ticker_snapshot_key(markets, route=("USDT", "BTC", "ETH", "USDT"))
    second = ticker_snapshot_key(
        reversed(markets),
        route=("USDT", "BTC", "ETH", "USDT"),
    )
    opposite = ticker_snapshot_key(
        markets,
        route=("USDT", "ETH", "BTC", "USDT"),
    )

    assert first == second
    assert first != opposite


def test_paper_round_trip_is_atomic_and_only_settles_the_start_asset() -> None:
    opportunity = TriangularEngine().scan(
        profitable_triangle(),
        start_asset="USDT",
        start_amount="100",
        now_ms=1_000,
    )[0]
    insufficient = TriangularPaperPortfolio({"demo": {"USDT": "99"}})
    rejected = TriangularPaperExecutor(insufficient)
    before = insufficient.snapshot()

    with pytest.raises(TriangularInsufficientBalanceError):
        rejected.execute(opportunity)
    assert insufficient.snapshot() == before
    assert rejected.journal == []
    assert rejected.realized_pnl == D("0")

    portfolio = TriangularPaperPortfolio({"demo": {"USDT": "100"}})
    executor = TriangularPaperExecutor(portfolio)
    execution = executor.execute(opportunity)

    assert portfolio.balance("demo", "USDT") == D("120")
    assert portfolio.snapshot() == {"demo": {"USDT": D("120")}}
    assert execution.realized_pnl == D("20")
    assert executor.realized_pnl == D("20")
    assert executor.journal == [execution]
    json.dumps(executor.to_dict())

    executor.reset()
    assert portfolio.balance("demo", "USDT") == D("100")
    assert executor.realized_pnl == D("0")
    assert executor.journal == []
