from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from packages.arbitrage.adapters import (
    BinancePublicAdapter,
    BitgetPublicAdapter,
    BybitPublicAdapter,
    OKXPublicAdapter,
    TickerPayloadError,
)


pytestmark = pytest.mark.contract


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_bybit_all_tickers_are_fetched_once_and_normalized() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert request.url.path == "/v5/market/tickers"
        assert dict(request.url.params) == {"category": "spot"}
        return httpx.Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "time": 1_723_456_789_000,
                "result": {
                    "category": "spot",
                    "list": [
                        {
                            "symbol": "ETHBTC",
                            "bid1Price": "0.0500",
                            "ask1Price": "0.0502",
                            "bid1Size": "12",
                            "ask1Size": "10",
                            "turnover24h": "2",
                            "price24hPcnt": "-0.0123",
                        },
                        {
                            "symbol": "BTCUSDT",
                            "bid1Price": "49900",
                            "ask1Price": "50100",
                            "bid1Size": "1.5",
                            "ask1Size": "2",
                            "turnover24h": "5000000",
                            "price24hPcnt": "0.005",
                        },
                        {
                            "symbol": "SUSPENDEDUSDT",
                            "bid1Price": "0",
                            "ask1Price": "0",
                            "bid1Size": "0",
                            "ask1Size": "0",
                            "turnover24h": "0",
                        },
                    ],
                },
            },
        )

    async with _client(handler) as client:
        adapter = BybitPublicAdapter(client=client, base_url="https://mock.test")
        tickers = await adapter.fetch_tickers()

    assert requests == 1
    assert [ticker.symbol for ticker in tickers] == ["ETHBTC", "BTCUSDT"]
    eth_btc = tickers[0]
    assert (eth_btc.base_asset, eth_btc.quote_asset) == ("ETH", "BTC")
    assert eth_btc.bid == Decimal("0.0500")
    assert eth_btc.ask_size == Decimal("10")
    assert eth_btc.quote_volume == Decimal("2")
    assert eth_btc.volume_usdt == Decimal("100000")
    assert eth_btc.timestamp_ms == 1_723_456_789_000
    assert eth_btc.change_24h_pct == Decimal("-1.2300")


@pytest.mark.asyncio
async def test_binance_all_tickers_schema_and_bad_rows_are_isolated() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert request.url.path == "/api/v3/ticker/24hr"
        assert not request.url.query
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "BNBUSDT",
                    "bidPrice": "599",
                    "askPrice": "601",
                    "bidQty": "3",
                    "askQty": "4",
                    "quoteVolume": "900000",
                    "priceChangePercent": "12.345",
                    "closeTime": 1_723_456_789_001,
                },
                {
                    "symbol": "BADUSDT",
                    "bidPrice": "NaN",
                    "askPrice": "1",
                    "bidQty": "1",
                    "askQty": "1",
                    "quoteVolume": "1",
                    "closeTime": 1_723_456_789_001,
                },
                {
                    "symbol": "LOCKEDUSDT",
                    "bidPrice": "1",
                    "askPrice": "1",
                    "bidQty": "100",
                    "askQty": "100",
                    "quoteVolume": "1000000",
                    "closeTime": 1_723_456_789_001,
                },
                "not-an-object",
            ],
        )

    async with _client(handler) as client:
        adapter = BinancePublicAdapter(
            client=client,
            base_url="https://mock.test",
            clock_ms=lambda: 1_800_000_000_000,
        )
        tickers = await adapter.fetch_tickers()

    assert requests == 1
    assert len(tickers) == 1
    assert tickers[0].symbol == "BNBUSDT"
    assert tickers[0].base_asset == "BNB"
    assert tickers[0].volume_usdt == Decimal("900000")
    assert tickers[0].change_24h_pct == Decimal("12.345")
    assert tickers[0].timestamp_ms == 1_800_000_000_000


@pytest.mark.asyncio
async def test_okx_all_tickers_use_spot_schema_and_reverse_usdt_rate() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert request.url.path == "/api/v5/market/tickers"
        assert dict(request.url.params) == {"instType": "SPOT"}
        return httpx.Response(
            200,
            json={
                "code": "0",
                "msg": "",
                "data": [
                    {
                        "instId": "USDT-BRL",
                        "bidPx": "4.99",
                        "askPx": "5.01",
                        "bidSz": "10000",
                        "askSz": "12000",
                        "volCcy24h": "5000000",
                        "last": "5",
                        "open24h": "4",
                        "ts": "1723456789002",
                    },
                    {
                        "instId": "BTC-BRL",
                        "bidPx": "249000",
                        "askPx": "251000",
                        "bidSz": "0.8",
                        "askSz": "1.2",
                        "volCcy24h": "1000000",
                        "last": "249000",
                        "open24h": "250000",
                        "ts": "1723456789002",
                    },
                ],
            },
        )

    async with _client(handler) as client:
        adapter = OKXPublicAdapter(client=client, base_url="https://mock.test")
        tickers = await adapter.fetch_tickers()

    assert requests == 1
    assert [ticker.symbol for ticker in tickers] == ["USDTBRL", "BTCBRL"]
    assert tickers[1].quote_asset == "BRL"
    assert tickers[1].volume_usdt == Decimal("200000")
    assert tickers[0].change_24h_pct == Decimal("25.00")
    assert tickers[1].change_24h_pct == Decimal("-0.400")


@pytest.mark.asyncio
async def test_bitget_all_tickers_prefer_reported_usdt_volume() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert request.url.path == "/api/v2/spot/market/tickers"
        assert not request.url.query
        return httpx.Response(
            200,
            json={
                "code": "00000",
                "msg": "success",
                "requestTime": 1_723_456_789_003,
                "data": [
                    {
                        "symbol": "ETHBTC",
                        "bidPr": "0.0499",
                        "askPr": "0.0501",
                        "bidSz": "5",
                        "askSz": "6",
                        "quoteVolume": "20",
                        "usdtVolume": "1000123.45",
                        "change24h": "0.052",
                        "ts": "1723456789004",
                    },
                    {
                        "symbol": "BROKENPAIR",
                        "bidPr": "1",
                        "askPr": "2",
                        "bidSz": "1",
                        "askSz": "1",
                        "quoteVolume": "1",
                        "ts": "1723456789004",
                    },
                ],
            },
        )

    async with _client(handler) as client:
        adapter = BitgetPublicAdapter(client=client, base_url="https://mock.test")
        tickers = await adapter.fetch_tickers()

    assert requests == 1
    assert len(tickers) == 1
    assert tickers[0].symbol == "ETHBTC"
    assert tickers[0].volume_usdt == Decimal("1000123.45")
    assert tickers[0].snapshot_id == "28724279:0.0499:0.0501:5:6"
    assert tickers[0].change_24h_pct == Decimal("5.200")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_type", "payload", "message"),
    [
        (BybitPublicAdapter, {"retCode": 0, "result": []}, "result"),
        (BinancePublicAdapter, {"symbol": "BTCUSDT"}, "root must be an array"),
        (OKXPublicAdapter, {"code": "0", "data": {}}, "data"),
        (BitgetPublicAdapter, {"code": "40034", "msg": "bad request"}, "bad request"),
    ],
)
async def test_malformed_all_ticker_payload_schema_is_rejected(
    adapter_type: type, payload: Any, message: str
) -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json=payload)

    async with _client(handler) as client:
        adapter = adapter_type(client=client, base_url="https://mock.test")
        with pytest.raises(TickerPayloadError, match=message):
            await adapter.fetch_tickers()

    assert requests == 1
