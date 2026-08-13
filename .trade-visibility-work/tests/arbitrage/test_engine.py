from __future__ import annotations

import json
from decimal import Decimal

import pytest

from packages.arbitrage import (
    ArbitrageConfig,
    ArbitrageEngine,
    InsufficientBalanceError,
    InsufficientLiquidityError,
    OrderBook,
    PaperArbitrageExecutor,
    PaperPortfolio,
    PriceLevel,
    Side,
    scan_opportunities,
)


pytestmark = pytest.mark.contract


D = Decimal


def book(
    venue: str,
    *,
    bid: str,
    ask: str,
    timestamp_ms: int = 1_000,
    bid_quantity: str = "10",
    ask_quantity: str = "10",
) -> OrderBook:
    return OrderBook(
        venue=venue,
        symbol="BTCUSDT",
        timestamp_ms=timestamp_ms,
        bids=(PriceLevel(bid, bid_quantity),),
        asks=(PriceLevel(ask, ask_quantity),),
    )


def test_order_book_uses_decimal_sorts_depth_and_serializes() -> None:
    order_book = OrderBook(
        " ByBit ",
        "btc/usdt",
        123,
        bids=[("99", "2"), ("100", "1")],
        asks=[{"price": "102", "size": "3"}, {"price": "101", "quantity": "2"}],
    )

    assert order_book.venue == "bybit"
    assert order_book.symbol == "BTCUSDT"
    assert order_book.best_bid == D("100")
    assert order_book.best_ask == D("101")
    assert all(isinstance(level.price, Decimal) for level in order_book.bids)
    assert order_book.to_dict()["asks"][0] == {"price": "101", "quantity": "2"}
    json.dumps(order_book.to_dict())


def test_executable_vwap_walks_depth_and_rejects_partial_fill() -> None:
    order_book = OrderBook(
        "a",
        "BTCUSDT",
        1_000,
        bids=[("99", "1"), ("98", "2")],
        asks=[("100", "1"), ("102", "2")],
    )

    buy = order_book.executable_vwap(Side.BUY, "2")
    sell = order_book.vwap("sell", "2")

    assert buy.notional == D("202")
    assert buy.average_price == D("101")
    assert buy.levels_consumed == 2
    assert sell.notional == D("197")
    assert sell.vwap == D("98.5")
    with pytest.raises(InsufficientLiquidityError):
        order_book.executable_vwap("buy", "3.0001")


def test_scan_accounts_for_fees_risk_buffer_and_max_notional() -> None:
    buy_book = book("a", bid="99", ask="100")
    sell_book = book("b", bid="102", ask="103")
    config = ArbitrageConfig(
        taker_fees={"a": "0.001", "b": "0.001"},
        min_net_edge="0.01",
        risk_buffer="0.0005",
        max_notional="500",
        max_staleness_ms=100,
    )

    opportunities = ArbitrageEngine(config).scan([buy_book, sell_book], now_ms=1_000)

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.route == "a->b"
    assert opportunity.quantity == D("5")
    assert opportunity.buy_fee == D("0.500")
    assert opportunity.sell_fee == D("0.510")
    assert opportunity.risk_buffer_cost == D("0.2500")
    assert opportunity.net_profit == D("8.7400")
    assert opportunity.net_edge == D("0.01748")
    json.dumps(opportunity.to_dict())

    too_high = ArbitrageConfig(
        taker_fees=config.taker_fees,
        min_net_edge="0.018",
        risk_buffer=config.risk_buffer,
        max_notional=config.max_notional,
    )
    assert ArbitrageEngine(too_high).scan([buy_book, sell_book], now_ms=1_000) == []


def test_depth_scanner_selects_profitable_size_instead_of_blindly_using_maximum() -> None:
    buy_book = OrderBook(
        "cheap",
        "BTCUSDT",
        1_000,
        bids=[("99", "10")],
        asks=[("100", "1"), ("110", "9")],
    )
    sell_book = OrderBook(
        "rich",
        "BTCUSDT",
        1_000,
        bids=[("105", "10")],
        asks=[("106", "10")],
    )

    opportunity = scan_opportunities(
        [buy_book, sell_book],
        ArbitrageConfig(max_notional="1000"),
        now_ms=1_000,
    )[0]

    # Deeper asks cost 110 and destroy the edge; the executable optimum is
    # exactly the first one-BTC level.
    assert opportunity.quantity == D("1")
    assert opportunity.buy_vwap == D("100")
    assert opportunity.net_profit == D("5")


def test_depth_scanner_sizes_to_edge_threshold_inside_a_level() -> None:
    buy_book = OrderBook(
        "cheap",
        "BTCUSDT",
        1_000,
        bids=[("99", "10")],
        asks=[("100", "1"), ("100", "9")],
    )
    sell_book = OrderBook(
        "rich",
        "BTCUSDT",
        1_000,
        bids=[("105", "1"), ("101", "9")],
        asks=[("106", "10")],
    )

    opportunity = scan_opportunities(
        [buy_book, sell_book],
        ArbitrageConfig(min_net_edge="0.02", max_notional="1000"),
        now_ms=1_000,
    )[0]

    # q=1 earns 5%; the next level remains profitable but dilutes the edge.
    # q=4 is the exact maximum-profit size that still earns 2%.
    assert opportunity.quantity == D("4")
    assert opportunity.net_profit == D("8")
    assert opportunity.net_edge == D("0.02")


def test_scanner_checks_every_directed_venue_pair() -> None:
    books = [
        book("a", bid="99", ask="100"),
        book("b", bid="101", ask="102"),
        book("c", bid="103", ask="104"),
    ]

    opportunities = scan_opportunities(
        books,
        ArbitrageConfig(max_notional="100"),
        now_ms=1_000,
    )

    assert {item.route for item in opportunities} == {"a->b", "a->c", "b->c"}
    assert opportunities[0].route == "a->c"


def test_stale_quotes_are_excluded_before_pairing() -> None:
    stale_buy = book("a", bid="99", ask="100", timestamp_ms=1_000)
    fresh_sell = book("b", bid="110", ask="111", timestamp_ms=2_000)
    engine = ArbitrageEngine(ArbitrageConfig(max_staleness_ms=500))

    assert engine.scan([stale_buy, fresh_sell], now_ms=2_000) == []
    assert len(
        ArbitrageEngine(ArbitrageConfig(max_staleness_ms=1_000)).scan(
            [stale_buy, fresh_sell], now_ms=2_000
        )
    ) == 1


def test_scanner_limits_quantity_by_prefunded_balances() -> None:
    buy_book = book("a", bid="99", ask="100")
    sell_book = book("b", bid="102", ask="103")
    balances = {
        "a": {"USDT": "252", "BTC": "0"},
        "b": {"USDT": "0", "BTC": "1.5"},
    }

    opportunity = scan_opportunities(
        [buy_book, sell_book],
        ArbitrageConfig(max_notional="1000"),
        now_ms=1_000,
        balances=balances,
    )[0]

    assert opportunity.quantity == D("1.5")
    assert opportunity.buy_notional == D("150.0")


def test_paper_execution_is_atomic_and_never_shorts() -> None:
    buy_book = book("a", bid="99", ask="100")
    sell_book = book("b", bid="102", ask="103")
    opportunity = scan_opportunities(
        [buy_book, sell_book],
        ArbitrageConfig(max_notional="500"),
        now_ms=1_000,
    )[0]
    portfolio = PaperPortfolio(
        {
            "a": {"USDT": "1000", "BTC": "0"},
            "b": {"USDT": "0", "BTC": "4.999"},
        }
    )
    executor = PaperArbitrageExecutor(portfolio)
    before = portfolio.snapshot()

    with pytest.raises(InsufficientBalanceError):
        executor.execute(opportunity, buy_book, sell_book)

    assert portfolio.snapshot() == before
    assert executor.realized_pnl == D("0")
    assert executor.journal == []


def test_paper_execution_updates_both_venues_journal_and_realized_pnl() -> None:
    buy_book = book("a", bid="99", ask="100")
    sell_book = book("b", bid="102", ask="103")
    config = ArbitrageConfig(
        taker_fees={"a": "0.001", "b": "0.001"},
        risk_buffer="0.0005",
        max_notional="500",
    )
    opportunity = ArbitrageEngine(config).scan([buy_book, sell_book], now_ms=1_000)[0]
    portfolio = PaperPortfolio(
        {
            "a": {"USDT": "1000", "BTC": "0"},
            "b": {"USDT": "0", "BTC": "10"},
        }
    )
    executor = PaperArbitrageExecutor(portfolio)

    execution = executor.execute(opportunity, buy_book, sell_book)

    assert portfolio.balance("a", "USDT") == D("499.500")
    assert portfolio.balance("a", "BTC") == D("5")
    assert portfolio.balance("b", "USDT") == D("509.490")
    assert portfolio.balance("b", "BTC") == D("5")
    assert execution.realized_pnl == D("8.990")
    # The planning edge includes a conservative buffer; realized paper PnL
    # records only actual depth and taker fees.
    assert execution.expected_net_profit == D("8.7400")
    assert executor.realized_pnl == D("8.990")
    assert executor.journal == [execution]
    payload = executor.to_dict()
    row = payload["journal"][0]
    assert row["buy_fee_usdt"] == "0.500"
    assert row["sell_fee_usdt"] == "0.510"
    assert row["total_fee_usdt"] == "1.010"
    assert row["buy_fee_quote"] == "0.500"
    assert row["sell_fee_quote"] == "0.510"
    assert row["total_fee_quote"] == "1.010"
    assert row["fee_quote_asset"] == "USDT"
    assert row["buy_fee_rate"] == "0.001"
    assert row["sell_fee_rate"] == "0.001"
    assert row["buy_fee_rate_bps"] == "10.000"
    assert row["sell_fee_rate_bps"] == "10.000"
    assert row["buy_leg"]["fee"] == "0.500"
    assert row["buy_leg"]["fee_quote"] == "0.500"
    assert row["buy_leg"]["fee_asset"] == "USDT"
    assert row["buy_leg"]["fee_rate"] == "0.001"
    assert row["buy_leg"]["fee_rate_bps"] == "10.000"
    json.dumps(payload)


def test_non_usdt_paper_fee_contract_uses_quote_fields_without_usdt_aliases() -> None:
    buy_book = OrderBook(
        "a",
        "BTCEUR",
        1_000,
        bids=[("499", "1")],
        asks=[("500", "1")],
    )
    sell_book = OrderBook(
        "b",
        "BTCEUR",
        1_000,
        bids=[("510", "1")],
        asks=[("511", "1")],
    )
    config = ArbitrageConfig(
        taker_fees={"a": "0.001", "b": "0.002"},
        max_notional="500",
    )
    opportunity = ArbitrageEngine(config).scan(
        [buy_book, sell_book], now_ms=1_000
    )[0]
    portfolio = PaperPortfolio(
        {
            "a": {"EUR": "1000", "BTC": "0"},
            "b": {"EUR": "0", "BTC": "1"},
        }
    )

    row = PaperArbitrageExecutor(portfolio).execute(
        opportunity, buy_book, sell_book
    ).to_dict()

    assert row["buy_fee_quote"] == "0.500"
    assert row["sell_fee_quote"] == "1.020"
    assert row["total_fee_quote"] == "1.520"
    assert row["fee_quote_asset"] == "EUR"
    assert "buy_fee_usdt" not in row
    assert "sell_fee_usdt" not in row
    assert "total_fee_usdt" not in row
    json.dumps(row)


def test_balance_sizing_never_rounds_above_affordable_quote() -> None:
    buy_book = book(
        "a",
        bid="0.9",
        ask="1",
        bid_quantity="200000",
        ask_quantity="200000",
    )
    sell_book = book(
        "b",
        bid="1.01",
        ask="1.02",
        bid_quantity="200000",
        ask_quantity="200000",
    )
    quote_balance = D("145377.26")
    config = ArbitrageConfig(
        taker_fees={"a": "0.0006", "b": "0"},
        max_notional="200000",
    )
    balances = {
        "a": {"USDT": quote_balance},
        "b": {"BTC": "200000"},
    }

    opportunity = ArbitrageEngine(config).scan(
        [buy_book, sell_book], now_ms=1_000, balances=balances
    )[0]
    portfolio = PaperPortfolio(balances)
    executor = PaperArbitrageExecutor(portfolio, config.taker_fees)

    executor.execute(opportunity, buy_book, sell_book)
    assert portfolio.balance("a", "USDT") >= 0


def test_quantity_step_rounds_down_and_minimum_notional_is_enforced() -> None:
    buy_book = book("a", bid="99", ask="100", ask_quantity="1")
    sell_book = book("b", bid="102", ask="103", bid_quantity="1")
    config = ArbitrageConfig(
        max_notional="25.55",
        quantity_steps={"BTCUSDT": "0.1"},
        min_notionals={"BTCUSDT": "10"},
    )

    opportunity = ArbitrageEngine(config).scan(
        [buy_book, sell_book], now_ms=1_000
    )[0]
    assert opportunity.quantity == D("0.2")
    assert opportunity.buy_notional == D("20.0")

    below_minimum = ArbitrageConfig(
        max_notional="9.99",
        quantity_steps={"BTCUSDT": "0.01"},
        min_notionals={"BTCUSDT": "10"},
    )
    assert ArbitrageEngine(below_minimum).scan(
        [buy_book, sell_book], now_ms=1_000
    ) == []
