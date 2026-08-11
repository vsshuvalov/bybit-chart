"""
Тесты для footprint analytics module (Roadmap §9.1 Этап 5).
"""

import pytest
from decimal import Decimal

from contracts.footprint import FootprintBar, FootprintLevel
from contracts.schemas import RawTrade, TakerSide
from packages.analytics.footprint import FootprintAggregator, compute_footprint_bars


def make_trade(trade_id: str, taker_side: TakerSide, price_ticks: int, qty_steps: int, timestamp_ms: int) -> RawTrade:
    """Helper для создания RawTrade."""
    return RawTrade(
        venue="BYBIT",
        category="linear",
        symbol="BTCUSDT",
        tradeId=trade_id,
        sequence=int(trade_id),
        exchangeTimestampMs=timestamp_ms,
        outerTimestampMs=timestamp_ms,
        receiveTimestampMs=timestamp_ms + 100,
        priceTicks=price_ticks,
        qtySteps=qty_steps,
        takerSide=taker_side,
        isBlockTrade=False,
        isRpiTrade=False,
    )


def test_footprint_aggregator_basic():
    """Базовый тест FootprintAggregator."""
    aggregator = FootprintAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        interval_seconds=60,
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
        interval_start_ms=1672324800000,
    )

    # price_ticks=166500 → 16650.0, qty_steps=1500 → 1.5
    trades = [
        make_trade("1", TakerSide.BUY, 166500, 1500, 1672324800000),
        make_trade("2", TakerSide.SELL, 166500, 500, 1672324810000),
        make_trade("3", TakerSide.BUY, 166510, 2000, 1672324820000),
    ]

    for trade in trades:
        aggregator.add_trade(trade)

    footprint = aggregator.build()

    assert footprint.symbol == "BTCUSDT"
    assert footprint.level_count == 2
    assert footprint.total_bid_volume == Decimal("3.5")
    assert footprint.total_ask_volume == Decimal("0.5")


def test_footprint_aggregator_imbalance():
    """Тест imbalance calculation."""
    aggregator = FootprintAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        interval_seconds=60,
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
        interval_start_ms=1672324800000,
    )

    # Strong buy: 9.0 buy, 1.0 sell
    aggregator.add_trade(make_trade("1", TakerSide.BUY, 166500, 9000, 1672324800000))
    aggregator.add_trade(make_trade("2", TakerSide.SELL, 166500, 1000, 1672324810000))

    footprint = aggregator.build()
    level = footprint.get_level(Decimal("16650.0"))

    assert level is not None
    # Imbalance = (9 - 1) / 10 = 0.8
    assert abs(level.imbalance - Decimal("0.8")) < Decimal("0.01")


def test_footprint_aggregator_empty():
    """Тест пустого aggregator."""
    aggregator = FootprintAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        interval_seconds=60,
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
    )

    with pytest.raises(ValueError, match="Нет данных"):
        aggregator.build()


def test_footprint_get_top_imbalanced_levels():
    """Тест get_top_imbalanced_levels."""
    aggregator = FootprintAggregator(
        venue="BYBIT",
        symbol="BTCUSDT",
        interval_seconds=60,
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
        interval_start_ms=1672324800000,
    )

    # Level 1: strong buy (0.8)
    aggregator.add_trade(make_trade("1", TakerSide.BUY, 166500, 9000, 1672324800000))
    aggregator.add_trade(make_trade("2", TakerSide.SELL, 166500, 1000, 1672324805000))

    # Level 2: weak (0.2)
    aggregator.add_trade(make_trade("3", TakerSide.BUY, 166510, 6000, 1672324810000))
    aggregator.add_trade(make_trade("4", TakerSide.SELL, 166510, 4000, 1672324815000))

    footprint = aggregator.build()

    imbalanced = footprint.get_top_imbalanced_levels(Decimal("0.5"))
    assert len(imbalanced) == 1
    assert imbalanced[0].price == Decimal("16650.0")


def test_compute_footprint_bars():
    """Тест compute_footprint_bars."""
    trades = [
        # Interval 1: 0..60s
        make_trade("1", TakerSide.BUY, 166500, 1000, 1672324800000),
        make_trade("2", TakerSide.SELL, 166500, 500, 1672324850000),
        # Interval 2: 60s+1ms
        make_trade("3", TakerSide.BUY, 166510, 2000, 1672324860001),
    ]

    bars = list(
        compute_footprint_bars(
            iter(trades),
            venue="BYBIT",
            symbol="BTCUSDT",
            interval_seconds=60,
            tick_size=Decimal("0.1"),
            step_size=Decimal("0.001"),
        )
    )

    assert len(bars) == 2
    assert bars[0].level_count == 1
    assert bars[1].level_count == 1
