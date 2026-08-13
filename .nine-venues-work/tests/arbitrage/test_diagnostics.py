from __future__ import annotations

import json
from decimal import Decimal

import pytest

from packages.arbitrage.diagnostics import (
    BELOW_NET_THRESHOLD,
    INSUFFICIENT_DEPTH,
    NON_POSITIVE_AFTER_COSTS,
    NON_POSITIVE_GROSS,
    PAIR_SKEW,
    aggregate_assessments,
    assess_pairs,
)
from packages.arbitrage.models import OrderBook, PriceLevel


pytestmark = pytest.mark.contract

D = Decimal


def book(
    venue: str,
    *,
    symbol: str = "BTCUSDT",
    bid: str,
    ask: str,
    bid_quantity: str = "10",
    ask_quantity: str = "10",
    timestamp_ms: int = 1_000,
) -> OrderBook:
    return OrderBook(
        venue=venue,
        symbol=symbol,
        timestamp_ms=timestamp_ms,
        bids=(PriceLevel(bid, bid_quantity),),
        asks=(PriceLevel(ask, ask_quantity),),
    )


def route(rows, buy: str, sell: str):
    return next(
        row for row in rows if row.buy_venue == buy and row.sell_venue == sell
    )


def test_assessment_matches_engine_top_level_fee_and_risk_math() -> None:
    rows = assess_pairs(
        [
            book("a", bid="99", ask="100"),
            book("b", bid="102", ask="103"),
        ],
        taker_fees={"a": "0.001", "b": "0.001"},
        risk_buffer="0.0005",
        min_net_edge="0.01",
        max_notional="500",
        min_notional="10",
    )

    assessment = route(rows, "a", "b")
    assert assessment.quantity == D("5")
    assert assessment.buy_price == D("100")
    assert assessment.sell_price == D("102")
    assert assessment.notional == D("500")
    assert assessment.sell_notional == D("510")
    assert assessment.buy_depth == D("1000")
    assert assessment.sell_depth == D("1020")
    assert assessment.buy_fee == D("0.500")
    assert assessment.sell_fee == D("0.510")
    assert assessment.risk_buffer_cost == D("0.2500")
    assert assessment.gross_edge == D("0.02")
    assert assessment.net_edge == D("0.01748")
    assert assessment.threshold_gap == D("0.00748")
    assert assessment.reasons == ()
    assert assessment.primary_rejection is None
    assert assessment.eligible is True

    payload = assessment.to_dict()
    assert payload["route"] == "a->b"
    assert payload["buy_fee_bps"] == "10.000"
    assert payload["sell_fee_bps"] == "10.000"
    assert D(payload["net_edge_bps"]) == D("174.8")
    assert D(payload["threshold_gap_bps"]) == D("74.8")
    assert payload["reasons"] == []
    json.dumps(payload)


def test_default_fee_is_used_for_unconfigured_venue() -> None:
    assessment = route(
        assess_pairs(
            [
                book("configured", bid="99", ask="100"),
                book("fallback", bid="102", ask="103"),
            ],
            taker_fees={"configured": "0.0005"},
            default_taker_fee="0.002",
            max_notional="100",
        ),
        "configured",
        "fallback",
    )

    assert assessment.buy_fee == D("0.0500")
    assert assessment.sell_fee == D("0.204")
    assert assessment.to_dict()["sell_fee_bps"] == "20.000"


def test_skew_and_depth_reasons_are_reported_without_hiding_pair() -> None:
    assessment = route(
        assess_pairs(
            [
                book(
                    "thin-buy",
                    bid="99",
                    ask="100",
                    ask_quantity="0.7",
                    timestamp_ms=1_000,
                ),
                book(
                    "thin-sell",
                    bid="102",
                    ask="103",
                    bid_quantity="0.5",
                    timestamp_ms=1_101,
                ),
            ],
            max_notional="500",
            min_notional="100",
            max_pair_skew_ms=100,
        ),
        "thin-buy",
        "thin-sell",
    )

    assert assessment.quantity == D("0.5")
    assert assessment.notional == D("50.0")
    assert assessment.pair_skew_ms == 101
    assert assessment.reasons == (PAIR_SKEW, INSUFFICIENT_DEPTH)
    assert assessment.primary_rejection == PAIR_SKEW
    assert assessment.eligible is False


@pytest.mark.parametrize(
    ("sell_bid", "fee", "threshold", "reason"),
    [
        ("100", "0", "0", NON_POSITIVE_GROSS),
        ("101", "0.006", "0", NON_POSITIVE_AFTER_COSTS),
        ("101", "0", "0.02", BELOW_NET_THRESHOLD),
    ],
)
def test_economic_rejection_categories_are_distinct(
    sell_bid: str,
    fee: str,
    threshold: str,
    reason: str,
) -> None:
    assessment = route(
        assess_pairs(
            [
                book("buy", bid="99", ask="100"),
                book("sell", bid=sell_bid, ask="103"),
            ],
            default_taker_fee=fee,
            min_net_edge=threshold,
            max_notional="100",
        ),
        "buy",
        "sell",
    )

    assert assessment.reasons == (reason,)
    assert assessment.primary_rejection == reason
    assert assessment.eligible is False


def test_all_directed_pairs_use_latest_snapshot_and_sort_best_net_first() -> None:
    rows = assess_pairs(
        [
            # The older duplicate would make a->c the strongest route if it
            # were not replaced by the latest (symbol, venue) snapshot.
            book("a", bid="89", ask="90", timestamp_ms=900),
            book("a", bid="99", ask="100", timestamp_ms=1_000),
            book("b", bid="101", ask="102", timestamp_ms=1_000),
            book("c", bid="103", ask="104", timestamp_ms=1_000),
        ],
        max_notional="100",
    )

    assert len(rows) == 6
    assert [(row.buy_venue, row.sell_venue) for row in rows[:2]] == [
        ("a", "c"),
        ("a", "b"),
    ]
    assert rows[0].buy_price == D("100")
    assert [row.net_edge for row in rows] == sorted(
        (row.net_edge for row in rows), reverse=True
    )


def test_assessment_funnel_counts_primary_and_all_reasons() -> None:
    rows = assess_pairs(
        [
            book("a", bid="99", ask="100", timestamp_ms=1_000),
            book("b", bid="102", ask="103", timestamp_ms=1_200),
        ],
        default_taker_fee="0.011",
        min_notional="2000",
        max_notional="100",
        max_pair_skew_ms=100,
    )

    funnel = aggregate_assessments(rows)
    assert funnel["total_pairs"] == 2
    assert funnel["eligible_pairs"] == 0
    assert funnel["rejected_pairs"] == 2
    assert funnel["primary_rejections"][PAIR_SKEW] == 2
    assert funnel["reason_counts"][INSUFFICIENT_DEPTH] == 2
    assert funnel["reason_counts"][NON_POSITIVE_AFTER_COSTS] == 1
    assert funnel["reason_counts"][NON_POSITIVE_GROSS] == 1


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"default_taker_fee": "1"}, "default_taker_fee"),
        ({"risk_buffer": "-0.1"}, "risk_buffer"),
        ({"min_net_edge": "1"}, "min_net_edge"),
        ({"max_notional": "0"}, "max_notional"),
        ({"min_notional": "-1"}, "min_notional"),
        ({"max_pair_skew_ms": -1}, "max_pair_skew_ms"),
    ],
)
def test_assessment_configuration_is_validated(kwargs, error: str) -> None:
    with pytest.raises((TypeError, ValueError), match=error):
        assess_pairs([], **kwargs)
