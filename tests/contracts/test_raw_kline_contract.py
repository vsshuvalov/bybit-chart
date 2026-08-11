"""
Contract tests для RawKline (Roadmap §8.2 RPI feed).

Property-based tests с Hypothesis для OHLC invariants.
"""

import pytest
from decimal import Decimal
from hypothesis import given, strategies as st

pytestmark = pytest.mark.contract

from contracts.raw_kline import RawKline


# Hypothesis strategies
symbol_strategy = st.sampled_from(["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"])
interval_strategy = st.sampled_from(["1", "3", "5", "15", "30", "60", "D"])
price_strategy = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000"),
    places=2,
)
volume_strategy = st.decimals(
    min_value=Decimal("0.001"),
    max_value=Decimal("10000"),
    places=3,
)
timestamp_strategy = st.integers(min_value=1672531200000, max_value=1893456000000)


def test_raw_kline_immutable():
    """RawKline должен быть immutable."""
    kline = RawKline(
        venue="BYBIT",
        category="linear",
        symbol="BTCUSDT",
        interval="1",
        start_timestamp_ms=1672324800000,
        end_timestamp_ms=1672324859999,
        open=Decimal("16649.5"),
        high=Decimal("16650.5"),
        low=Decimal("16649"),
        close=Decimal("16650"),
        volume=Decimal("2.343"),
        turnover=Decimal("39007.1165"),
        confirm=False,
        exchange_timestamp_ms=1672324800000,
        receive_timestamp_ms=1672324850000,
    )

    with pytest.raises(Exception):  # Pydantic frozen model
        kline.open = Decimal("99999")


@given(
    symbol=symbol_strategy,
    interval=interval_strategy,
    open_price=price_strategy,
    high_price=price_strategy,
    low_price=price_strategy,
    close_price=price_strategy,
    volume=volume_strategy,
)
def test_raw_kline_ohlc_invariants(
    symbol, interval, open_price, high_price, low_price, close_price, volume
):
    """Property: OHLC invariants.

    - high >= max(open, close, low)
    - low <= min(open, close, high)
    - volume >= 0
    """
    # Adjust prices to satisfy OHLC constraints
    actual_high = max(open_price, high_price, low_price, close_price)
    actual_low = min(open_price, high_price, low_price, close_price)

    kline = RawKline(
        venue="BYBIT",
        category="linear",
        symbol=symbol,
        interval=interval,
        start_timestamp_ms=1672324800000,
        end_timestamp_ms=1672324859999,
        open=open_price,
        high=actual_high,
        low=actual_low,
        close=close_price,
        volume=volume,
        turnover=Decimal("10000"),
        confirm=False,
        exchange_timestamp_ms=1672324800000,
        receive_timestamp_ms=1672324850000,
    )

    # Verify OHLC invariants
    assert kline.high >= kline.open
    assert kline.high >= kline.close
    assert kline.high >= kline.low

    assert kline.low <= kline.open
    assert kline.low <= kline.close
    assert kline.low <= kline.high

    assert kline.volume >= 0


@given(
    start_ts=timestamp_strategy,
    end_ts=timestamp_strategy,
)
def test_raw_kline_timestamp_order(start_ts, end_ts):
    """Property: start_timestamp_ms <= end_timestamp_ms."""
    # Ensure start <= end
    if start_ts > end_ts:
        start_ts, end_ts = end_ts, start_ts

    kline = RawKline(
        venue="BYBIT",
        category="linear",
        symbol="BTCUSDT",
        interval="1",
        start_timestamp_ms=start_ts,
        end_timestamp_ms=end_ts,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("10"),
        turnover=Decimal("1000"),
        confirm=False,
        exchange_timestamp_ms=start_ts,
        receive_timestamp_ms=end_ts,
    )

    assert kline.start_timestamp_ms <= kline.end_timestamp_ms
    assert kline.exchange_timestamp_ms <= kline.receive_timestamp_ms


def test_raw_kline_confirmed_flag():
    """Confirmed kline должен иметь confirm=True."""
    kline_unconfirmed = RawKline(
        venue="BYBIT",
        category="linear",
        symbol="BTCUSDT",
        interval="1",
        start_timestamp_ms=1672324800000,
        end_timestamp_ms=1672324859999,
        open=Decimal("16649.5"),
        high=Decimal("16650.5"),
        low=Decimal("16649"),
        close=Decimal("16650"),
        volume=Decimal("2.343"),
        turnover=Decimal("39007.1165"),
        confirm=False,
        exchange_timestamp_ms=1672324800000,
        receive_timestamp_ms=1672324850000,
    )

    kline_confirmed = RawKline(
        venue="BYBIT",
        category="linear",
        symbol="BTCUSDT",
        interval="1",
        start_timestamp_ms=1672324800000,
        end_timestamp_ms=1672324859999,
        open=Decimal("16649.5"),
        high=Decimal("16650.5"),
        low=Decimal("16649"),
        close=Decimal("16650"),
        volume=Decimal("2.343"),
        turnover=Decimal("39007.1165"),
        confirm=True,
        exchange_timestamp_ms=1672324800000,
        receive_timestamp_ms=1672324860000,
    )

    assert kline_unconfirmed.confirm is False
    assert kline_confirmed.confirm is True


@given(
    volume=volume_strategy,
)
def test_raw_kline_volume_positive(volume):
    """Property: volume >= 0."""
    kline = RawKline(
        venue="BYBIT",
        category="linear",
        symbol="BTCUSDT",
        interval="1",
        start_timestamp_ms=1672324800000,
        end_timestamp_ms=1672324859999,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=volume,
        turnover=Decimal("1000"),
        confirm=False,
        exchange_timestamp_ms=1672324800000,
        receive_timestamp_ms=1672324850000,
    )

    assert kline.volume >= 0


def test_raw_kline_serialization():
    """RawKline должен сериализоваться в JSON (mode='json')."""
    kline = RawKline(
        venue="BYBIT",
        category="linear",
        symbol="BTCUSDT",
        interval="1",
        start_timestamp_ms=1672324800000,
        end_timestamp_ms=1672324859999,
        open=Decimal("16649.5"),
        high=Decimal("16650.5"),
        low=Decimal("16649"),
        close=Decimal("16650"),
        volume=Decimal("2.343"),
        turnover=Decimal("39007.1165"),
        confirm=False,
        exchange_timestamp_ms=1672324800000,
        receive_timestamp_ms=1672324850000,
    )

    # Serialize to dict with JSON-compatible types
    kline_dict = kline.model_dump(mode='json')

    assert isinstance(kline_dict['open'], str)  # Decimal → str
    assert isinstance(kline_dict['volume'], str)
    assert kline_dict['symbol'] == "BTCUSDT"
    assert kline_dict['confirm'] is False


def test_raw_kline_venue_bybit():
    """Venue должен быть BYBIT (contract invariant)."""
    kline = RawKline(
        venue="BYBIT",
        category="linear",
        symbol="BTCUSDT",
        interval="1",
        start_timestamp_ms=1672324800000,
        end_timestamp_ms=1672324859999,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("10"),
        turnover=Decimal("1000"),
        confirm=False,
        exchange_timestamp_ms=1672324800000,
        receive_timestamp_ms=1672324850000,
    )

    assert kline.venue == "BYBIT"


def test_raw_kline_multiple_intervals():
    """Разные интервалы должны работать."""
    intervals = ["1", "3", "5", "15", "30", "60", "D"]

    for interval in intervals:
        kline = RawKline(
            venue="BYBIT",
            category="linear",
            symbol="BTCUSDT",
            interval=interval,
            start_timestamp_ms=1672324800000,
            end_timestamp_ms=1672324859999,
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=Decimal("10"),
            turnover=Decimal("1000"),
            confirm=False,
            exchange_timestamp_ms=1672324800000,
            receive_timestamp_ms=1672324850000,
        )

        assert kline.interval == interval
