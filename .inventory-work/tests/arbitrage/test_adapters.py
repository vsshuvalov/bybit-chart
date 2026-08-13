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
    OrderBookPayloadError,
    PublicVenueAdapter,
    PublicVenueError,
)


pytestmark = pytest.mark.contract


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_bybit_normalizes_public_spot_book() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v5/market/orderbook"
        assert dict(request.url.params) == {
            "category": "spot",
            "symbol": "BTCUSDT",
            "limit": "2",
        }
        assert "x-bapi-api-key" not in request.headers
        return httpx.Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "s": "BTCUSDT",
                    "b": [["99.50", "2"], ["100.00", "1.25"]],
                    "a": [["101.00", "0.75"], ["100.50", "3"]],
                    "ts": 1_723_456_789_012,
                },
                "time": 1_723_456_789_100,
            },
        )

    async with _client(handler) as client:
        adapter = BybitPublicAdapter(client=client, base_url="https://mock.bybit.test/")
        book = await adapter.fetch_order_book("btc/usdt", depth=2)

    assert isinstance(adapter, PublicVenueAdapter)
    assert book.venue == "bybit"
    assert book.symbol == "BTCUSDT"
    assert book.timestamp_ms == 1_723_456_789_012
    assert [(level.price, level.quantity) for level in book.bids] == [
        (Decimal("100.00"), Decimal("1.25")),
        (Decimal("99.50"), Decimal("2")),
    ]
    assert [(level.price, level.quantity) for level in book.asks] == [
        (Decimal("100.50"), Decimal("3")),
        (Decimal("101.00"), Decimal("0.75")),
    ]


@pytest.mark.asyncio
async def test_binance_uses_receipt_timestamp_when_schema_has_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/depth"
        assert dict(request.url.params) == {"symbol": "ETHUSDT", "limit": "20"}
        assert "x-mbx-apikey" not in request.headers
        return httpx.Response(
            200,
            json={
                "lastUpdateId": 1027024,
                "bids": [["1999.9", "4.5"]],
                "asks": [["2000.1", "6.75"]],
            },
        )

    async with _client(handler) as client:
        adapter = BinancePublicAdapter(
            client=client,
            base_url="https://mock.binance.test",
            clock_ms=lambda: 1_723_456_700_000,
        )
        book = await adapter.fetch_order_book("eth-usdt")

    assert book.venue == "binance"
    assert book.symbol == "ETHUSDT"
    assert book.timestamp_ms == 1_723_456_700_000
    assert book.bids[0].price == Decimal("1999.9")
    assert book.asks[0].quantity == Decimal("6.75")


@pytest.mark.asyncio
async def test_okx_normalizes_four_column_levels_and_instrument_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v5/market/books"
        assert dict(request.url.params) == {"instId": "SOL-USDT", "sz": "5"}
        assert "ok-access-key" not in request.headers
        return httpx.Response(
            200,
            json={
                "code": "0",
                "msg": "",
                "data": [
                    {
                        "asks": [["150.2", "8.1", "0", "3"]],
                        "bids": [["150.1", "7.2", "0", "4"]],
                        "ts": "1723456789013",
                    }
                ],
            },
        )

    async with _client(handler) as client:
        adapter = OKXPublicAdapter(client=client, base_url="https://mock.okx.test")
        book = await adapter.fetch_order_book("sol_usdt", depth=5)

    assert book.venue == "okx"
    assert book.symbol == "SOLUSDT"
    assert book.timestamp_ms == 1_723_456_789_013
    assert book.bids[0].quantity == Decimal("7.2")
    assert book.asks[0].price == Decimal("150.2")


@pytest.mark.asyncio
async def test_bitget_normalizes_public_spot_book() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/spot/market/orderbook"
        assert dict(request.url.params) == {
            "symbol": "DOGEUSDT",
            "type": "step0",
            "limit": "10",
        }
        assert "access-key" not in request.headers
        return httpx.Response(
            200,
            json={
                "code": "00000",
                "msg": "success",
                "requestTime": 1_723_456_789_000,
                "data": {
                    "asks": [["0.101", "1000"]],
                    "bids": [["0.100", "900"]],
                    "ts": "1723456789014",
                },
            },
        )

    async with _client(handler) as client:
        adapter = BitgetPublicAdapter(client=client, base_url="https://mock.bitget.test")
        book = await adapter.fetch_order_book("doge/usdt", depth=10)

    assert book.venue == "bitget"
    assert book.symbol == "DOGEUSDT"
    assert book.timestamp_ms == 1_723_456_789_014
    assert book.bids[0].price == Decimal("0.100")
    assert book.asks[0].quantity == Decimal("1000")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_type", "payload", "message"),
    [
        (
            BybitPublicAdapter,
            {"retCode": 10001, "retMsg": "invalid symbol", "result": {}},
            "invalid symbol",
        ),
        (
            BinancePublicAdapter,
            {"code": -1121, "msg": "Invalid symbol."},
            "Invalid symbol",
        ),
        (
            OKXPublicAdapter,
            {"code": "51001", "msg": "Instrument ID doesn't exist", "data": []},
            "Instrument ID",
        ),
        (
            BitgetPublicAdapter,
            {"code": "40034", "msg": "Parameter error", "data": None},
            "Parameter error",
        ),
    ],
)
async def test_venue_error_payloads_are_rejected(
    adapter_type: type, payload: dict[str, Any], message: str
) -> None:
    async with _client(lambda _request: httpx.Response(200, json=payload)) as client:
        adapter = adapter_type(client=client, base_url="https://mock.venue.test")
        with pytest.raises(OrderBookPayloadError, match=message):
            await adapter.fetch_order_book("BTCUSDT")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_type", "payload"),
    [
        (
            BybitPublicAdapter,
            {
                "retCode": 0,
                "result": {"b": [], "a": [["101", "1"]], "ts": 1_700_000_000_000},
            },
        ),
        (
            BinancePublicAdapter,
            {"bids": [["100", "1"]], "asks": []},
        ),
        (
            OKXPublicAdapter,
            {"code": "0", "msg": "", "data": []},
        ),
        (
            BitgetPublicAdapter,
            {
                "code": "00000",
                "data": {"bids": None, "asks": [["101", "1"]], "ts": "1700000000000"},
            },
        ),
    ],
)
async def test_empty_or_missing_books_are_rejected(
    adapter_type: type, payload: dict[str, Any]
) -> None:
    async with _client(lambda _request: httpx.Response(200, json=payload)) as client:
        adapter = adapter_type(
            client=client,
            base_url="https://mock.venue.test",
            clock_ms=lambda: 1_700_000_000_000,
        )
        with pytest.raises(OrderBookPayloadError):
            await adapter.fetch_order_book("BTCUSDT")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_level",
    [
        ["not-a-price", "1"],
        ["100", "0"],
        ["100"],
        {"price": "100", "quantity": "1"},
    ],
)
async def test_malformed_levels_are_rejected(bad_level: Any) -> None:
    payload = {
        "bids": [bad_level],
        "asks": [["101", "1"]],
    }
    async with _client(lambda _request: httpx.Response(200, json=payload)) as client:
        adapter = BinancePublicAdapter(
            client=client,
            base_url="https://mock.binance.test",
            clock_ms=lambda: 1_700_000_000_000,
        )
        with pytest.raises(OrderBookPayloadError):
            await adapter.fetch_order_book("BTCUSDT")


@pytest.mark.asyncio
async def test_http_and_json_errors_have_common_public_error_types() -> None:
    async with _client(
        lambda _request: httpx.Response(503, json={"error": "unavailable"})
    ) as client:
        adapter = BinancePublicAdapter(client=client, base_url="https://mock.test")
        with pytest.raises(PublicVenueError, match="public request failed"):
            await adapter.fetch_order_book("BTCUSDT")

    async with _client(
        lambda _request: httpx.Response(200, content=b"not json")
    ) as client:
        adapter = BinancePublicAdapter(client=client, base_url="https://mock.test")
        with pytest.raises(OrderBookPayloadError, match="valid JSON"):
            await adapter.fetch_order_book("BTCUSDT")


@pytest.mark.asyncio
async def test_input_validation_happens_before_network_request() -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    async with _client(handler) as client:
        bybit = BybitPublicAdapter(client=client, base_url="https://mock.test")
        with pytest.raises(ValueError, match="between 1 and 50"):
            await bybit.fetch_order_book("BTCUSDT", depth=51)
        with pytest.raises(TypeError, match="integer"):
            await bybit.fetch_order_book("BTCUSDT", depth=True)
        with pytest.raises(ValueError, match="ASCII"):
            await bybit.fetch_order_book("BTC$USDT")

        okx = OKXPublicAdapter(client=client, base_url="https://mock.test")
        with pytest.raises(ValueError, match="recognized quote"):
            await okx.fetch_order_book("UNKNOWNPAIR")

    assert requests == 0


@pytest.mark.asyncio
async def test_injected_client_base_url_is_honored() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "local.mock"
        return httpx.Response(
            200,
            json={
                "bids": [["100", "1"]],
                "asks": [["101", "1"]],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://local.mock"
    ) as client:
        adapter = BinancePublicAdapter(
            client=client,
            clock_ms=lambda: 1_700_000_000_000,
        )
        book = await adapter.fetch_order_book("BTCUSDT")

    assert book.venue == "binance"
