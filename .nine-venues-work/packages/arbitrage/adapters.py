"""Public, read-only REST adapters for venue-neutral spot market data.

The adapters in this module intentionally expose only public market data.  They
normalize both order books and all-market top-of-book tickers, do not accept
credentials, and contain no order, account, or wallet endpoints.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import time
from typing import Any, ClassVar, Protocol, runtime_checkable

import httpx

from packages.arbitrage.models import OrderBook, PriceLevel
from packages.arbitrage.triangular import MarketTicker


__all__ = [
    "PublicVenueAdapter",
    "BasePublicVenueAdapter",
    "PublicVenueError",
    "OrderBookPayloadError",
    "TickerPayloadError",
    "BybitPublicAdapter",
    "BinancePublicAdapter",
    "OkxPublicAdapter",
    "OKXPublicAdapter",
    "BitgetPublicAdapter",
    "HuobiPublicAdapter",
    "HtxPublicAdapter",
    "HTXPublicAdapter",
    "KuCoinPublicAdapter",
    "KucoinPublicAdapter",
    "MEXCPublicAdapter",
    "MexcPublicAdapter",
    "BingXPublicAdapter",
    "BingxPublicAdapter",
    "GatePublicAdapter",
    "GateIOPublicAdapter",
    "GateioPublicAdapter",
    "BybitAdapter",
    "BinanceAdapter",
    "OKXAdapter",
    "BitgetAdapter",
    "HuobiAdapter",
    "HTXAdapter",
    "KuCoinAdapter",
    "MEXCAdapter",
    "BingXAdapter",
    "GateAdapter",
]


ClockMs = Callable[[], int]


class PublicVenueError(RuntimeError):
    """A public market-data request could not produce a valid snapshot."""


class OrderBookPayloadError(PublicVenueError):
    """A venue returned a successful HTTP response with invalid book data."""


class TickerPayloadError(PublicVenueError):
    """A venue returned a successful HTTP response with invalid ticker data."""


@runtime_checkable
class PublicVenueAdapter(Protocol):
    """Common contract implemented by every public spot venue adapter."""

    venue: str

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        """Fetch and normalize a public level-2 order-book snapshot."""

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        """Fetch and normalize all active public spot top-of-book tickers."""

    async def aclose(self) -> None:
        """Close resources owned by the adapter."""


class BasePublicVenueAdapter(ABC):
    """Shared HTTP lifecycle, validation, and error handling."""

    venue: ClassVar[str]
    default_base_url: ClassVar[str]
    max_depth: ClassVar[int]

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
        timeout: float = 5.0,
        clock_ms: ClockMs | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")

        injected_base_url = str(client.base_url) if client is not None else ""
        self.base_url = (
            base_url or injected_base_url or self.default_base_url
        ).rstrip("/")
        if not self.base_url:
            raise ValueError("base_url must not be empty")

        self._owns_client = client is None
        self._client = client or httpx.AsyncClient()
        self._timeout = timeout
        self._clock_ms = clock_ms or _system_clock_ms

    @abstractmethod
    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        """Fetch and normalize a public spot order book."""

    @abstractmethod
    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        """Fetch one public all-spot-tickers snapshot."""

    async def _request_json(
        self,
        path: str,
        *,
        params: Mapping[str, str | int],
        payload_error: type[PublicVenueError] = OrderBookPayloadError,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = await self._client.get(
                url,
                params=params,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PublicVenueError(f"{self.venue}: public request failed") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise payload_error(
                f"{self.venue}: response is not valid JSON"
            ) from exc

        return payload

    async def _get_json(
        self, path: str, *, params: Mapping[str, str | int]
    ) -> Mapping[str, Any]:
        payload = await self._request_json(path, params=params)
        if not isinstance(payload, Mapping):
            raise OrderBookPayloadError(
                f"{self.venue}: response root must be an object"
            )
        return payload

    async def _get_ticker_json(
        self, path: str, *, params: Mapping[str, str | int]
    ) -> Mapping[str, Any]:
        payload = await self._request_json(
            path, params=params, payload_error=TickerPayloadError
        )
        if not isinstance(payload, Mapping):
            raise TickerPayloadError(
                f"{self.venue}: response root must be an object"
            )
        return payload

    async def _get_json_array(
        self, path: str, *, params: Mapping[str, str | int]
    ) -> Sequence[Any]:
        payload = await self._request_json(
            path, params=params, payload_error=TickerPayloadError
        )
        if isinstance(payload, (str, bytes)) or not isinstance(payload, Sequence):
            if isinstance(payload, Mapping):
                detail = (
                    payload.get("msg")
                    or payload.get("message")
                    or payload.get("label")
                )
                if detail:
                    raise TickerPayloadError(f"{self.venue}: {detail}")
            raise TickerPayloadError(
                f"{self.venue}: response root must be an array"
            )
        return payload

    def _request_values(self, symbol: str, depth: int) -> tuple[str, int]:
        return _normalise_symbol(symbol), _validate_depth(depth, self.max_depth)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> BasePublicVenueAdapter:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()


class BybitPublicAdapter(BasePublicVenueAdapter):
    """Bybit V5 public spot order-book adapter."""

    venue = "bybit"
    default_base_url = "https://api.bybit.com"
    max_depth = 50

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        payload = await self._get_ticker_json(
            "/v5/market/tickers", params={"category": "spot"}
        )
        if payload.get("retCode") != 0:
            detail = payload.get("retMsg") or "unknown venue error"
            raise TickerPayloadError(f"{self.venue}: {detail}")

        result = _ticker_mapping(payload.get("result"), self.venue, "result")
        rows = _ticker_sequence(result.get("list"), self.venue, "result.list")
        timestamp = _ticker_timestamp_ms(
            payload.get("time"), venue=self.venue, field="time"
        )
        raw = _parse_compact_ticker_rows(
            venue=self.venue,
            rows=rows,
            timestamp=lambda _row: timestamp,
            bid_field="bid1Price",
            ask_field="ask1Price",
            bid_size_field="bid1Size",
            ask_size_field="ask1Size",
            quote_volume_field="turnover24h",
            change_field="price24hPcnt",
            change_multiplier=Decimal("100"),
        )
        return _market_tickers(raw)

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        canonical, depth = self._request_values(symbol, depth)
        payload = await self._get_json(
            "/v5/market/orderbook",
            params={"category": "spot", "symbol": canonical, "limit": depth},
        )

        if payload.get("retCode") != 0:
            detail = payload.get("retMsg") or "unknown venue error"
            raise OrderBookPayloadError(f"{self.venue}: {detail}")

        result = _require_mapping(payload.get("result"), self.venue, "result")
        timestamp = _timestamp_ms(
            result.get("ts", payload.get("time")),
            venue=self.venue,
            field="result.ts",
        )
        return _make_order_book(
            venue=self.venue,
            symbol=canonical,
            timestamp_ms=timestamp,
            bids=result.get("b"),
            asks=result.get("a"),
            snapshot_id=result.get("u", result.get("seq")),
        )


class BinancePublicAdapter(BasePublicVenueAdapter):
    """Binance public spot depth adapter."""

    venue = "binance"
    default_base_url = "https://api.binance.com"
    max_depth = 5_000

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        rows = await self._get_json_array("/api/v3/ticker/24hr", params={})
        # Binance's 24h-statistics closeTime may describe the last trade for
        # an inactive symbol, while bidPrice/askPrice are the current BBO in
        # the response.  Freshness therefore follows receipt time, just like
        # the Binance REST depth snapshot, rather than per-symbol closeTime.
        receipt_timestamp = _ticker_timestamp_ms(
            self._clock_ms(),
            venue=self.venue,
            field="receipt timestamp",
        )
        raw = _parse_compact_ticker_rows(
            venue=self.venue,
            rows=rows,
            timestamp=lambda _row: receipt_timestamp,
            bid_field="bidPrice",
            ask_field="askPrice",
            bid_size_field="bidQty",
            ask_size_field="askQty",
            quote_volume_field="quoteVolume",
            change_field="priceChangePercent",
        )
        return _market_tickers(raw)

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        canonical, depth = self._request_values(symbol, depth)
        payload = await self._get_json(
            "/api/v3/depth",
            params={"symbol": canonical, "limit": depth},
        )

        if "code" in payload and "bids" not in payload:
            detail = payload.get("msg") or f"venue error {payload.get('code')}"
            raise OrderBookPayloadError(f"{self.venue}: {detail}")

        # Binance's REST depth snapshot has no exchange timestamp.  Stamp it at
        # receipt so callers can still enforce a conservative freshness limit.
        timestamp = _timestamp_ms(
            self._clock_ms(), venue=self.venue, field="receipt timestamp"
        )
        return _make_order_book(
            venue=self.venue,
            symbol=canonical,
            timestamp_ms=timestamp,
            bids=payload.get("bids"),
            asks=payload.get("asks"),
            snapshot_id=payload.get("lastUpdateId"),
        )


class OkxPublicAdapter(BasePublicVenueAdapter):
    """OKX V5 public spot books adapter."""

    venue = "okx"
    default_base_url = "https://www.okx.com"
    max_depth = 400

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        payload = await self._get_ticker_json(
            "/api/v5/market/tickers", params={"instType": "SPOT"}
        )
        if str(payload.get("code")) != "0":
            detail = payload.get("msg") or "unknown venue error"
            raise TickerPayloadError(f"{self.venue}: {detail}")

        rows = _ticker_sequence(payload.get("data"), self.venue, "data")
        raw = _parse_okx_ticker_rows(rows)
        return _market_tickers(raw)

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        canonical, depth = self._request_values(symbol, depth)
        instrument_id = _okx_instrument_id(symbol, canonical)
        payload = await self._get_json(
            "/api/v5/market/books",
            params={"instId": instrument_id, "sz": depth},
        )

        if str(payload.get("code")) != "0":
            detail = payload.get("msg") or "unknown venue error"
            raise OrderBookPayloadError(f"{self.venue}: {detail}")

        data = _require_sequence(payload.get("data"), self.venue, "data")
        if not data:
            raise OrderBookPayloadError(f"{self.venue}: data must not be empty")
        snapshot = _require_mapping(data[0], self.venue, "data[0]")
        timestamp = _timestamp_ms(
            snapshot.get("ts"), venue=self.venue, field="data[0].ts"
        )
        return _make_order_book(
            venue=self.venue,
            symbol=canonical,
            timestamp_ms=timestamp,
            bids=snapshot.get("bids"),
            asks=snapshot.get("asks"),
            snapshot_id=snapshot.get("seqId", snapshot.get("ts")),
        )


class BitgetPublicAdapter(BasePublicVenueAdapter):
    """Bitget V2 public spot order-book adapter."""

    venue = "bitget"
    default_base_url = "https://api.bitget.com"
    max_depth = 150

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        payload = await self._get_ticker_json(
            "/api/v2/spot/market/tickers", params={}
        )
        if str(payload.get("code")) != "00000":
            detail = payload.get("msg") or "unknown venue error"
            raise TickerPayloadError(f"{self.venue}: {detail}")

        rows = _ticker_sequence(payload.get("data"), self.venue, "data")
        fallback_timestamp = payload.get("requestTime")
        raw = _parse_compact_ticker_rows(
            venue=self.venue,
            rows=rows,
            timestamp=lambda row: _ticker_timestamp_ms(
                row.get("ts", fallback_timestamp),
                venue=self.venue,
                field="ts",
            ),
            bid_field="bidPr",
            ask_field="askPr",
            bid_size_field="bidSz",
            ask_size_field="askSz",
            quote_volume_field="quoteVolume",
            usdt_volume_field="usdtVolume",
            change_field="change24h",
            change_multiplier=Decimal("100"),
        )
        return _market_tickers(raw)

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        canonical, depth = self._request_values(symbol, depth)
        payload = await self._get_json(
            "/api/v2/spot/market/orderbook",
            params={"symbol": canonical, "type": "step0", "limit": depth},
        )

        if str(payload.get("code")) != "00000":
            detail = payload.get("msg") or "unknown venue error"
            raise OrderBookPayloadError(f"{self.venue}: {detail}")

        snapshot = _require_mapping(payload.get("data"), self.venue, "data")
        timestamp = _timestamp_ms(
            snapshot.get("ts", payload.get("requestTime")),
            venue=self.venue,
            field="data.ts",
        )
        return _make_order_book(
            venue=self.venue,
            symbol=canonical,
            timestamp_ms=timestamp,
            bids=snapshot.get("bids"),
            asks=snapshot.get("asks"),
            snapshot_id=snapshot.get("checksum", snapshot.get("ts")),
        )


class HuobiPublicAdapter(BasePublicVenueAdapter):
    """HTX (formerly Huobi) public spot market-data adapter."""

    venue = "huobi"
    default_base_url = "https://api.huobi.pro"
    max_depth = 20

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        payload = await self._get_ticker_json("/market/tickers", params={})
        if payload.get("status") != "ok":
            detail = payload.get("err-msg") or payload.get("message") or "venue error"
            raise TickerPayloadError(f"{self.venue}: {detail}")

        rows = _ticker_sequence(payload.get("data"), self.venue, "data")
        timestamp = _ticker_timestamp_ms(
            payload.get("ts"), venue=self.venue, field="ts"
        )
        raw = _parse_compact_ticker_rows(
            venue=self.venue,
            rows=rows,
            timestamp=lambda _row: timestamp,
            bid_field="bid",
            ask_field="ask",
            bid_size_field="bidSize",
            ask_size_field="askSize",
            quote_volume_field="vol",
            base_volume_field="amount",
            last_price_field="close",
            open_field="open",
            close_field="close",
        )
        return _market_tickers(raw)

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        canonical, depth = self._request_values(symbol, depth)
        request_depth = _next_supported_depth(depth, (5, 10, 20))
        payload = await self._get_json(
            "/market/depth",
            params={
                "symbol": canonical.lower(),
                "type": "step0",
                "depth": request_depth,
            },
        )
        if payload.get("status") != "ok":
            detail = payload.get("err-msg") or payload.get("message") or "venue error"
            raise OrderBookPayloadError(f"{self.venue}: {detail}")

        snapshot = _require_mapping(payload.get("tick"), self.venue, "tick")
        timestamp = _timestamp_ms(
            snapshot.get("ts", payload.get("ts")),
            venue=self.venue,
            field="tick.ts",
        )
        return _make_order_book(
            venue=self.venue,
            symbol=canonical,
            timestamp_ms=timestamp,
            bids=snapshot.get("bids"),
            asks=snapshot.get("asks"),
            snapshot_id=snapshot.get("version", snapshot.get("id")),
            limit=depth,
        )


class KuCoinPublicAdapter(BasePublicVenueAdapter):
    """KuCoin public spot all-tickers and partial level-2 adapter."""

    venue = "kucoin"
    default_base_url = "https://api.kucoin.com"
    max_depth = 100

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        payload = await self._get_ticker_json(
            "/api/v1/market/allTickers", params={}
        )
        if str(payload.get("code")) != "200000":
            detail = payload.get("msg") or payload.get("message") or "venue error"
            raise TickerPayloadError(f"{self.venue}: {detail}")

        data = _ticker_mapping(payload.get("data"), self.venue, "data")
        rows = _ticker_sequence(data.get("ticker"), self.venue, "data.ticker")
        timestamp = _ticker_timestamp_ms(
            data.get("time"), venue=self.venue, field="data.time"
        )
        raw = _parse_compact_ticker_rows(
            venue=self.venue,
            rows=rows,
            timestamp=lambda _row: timestamp,
            bid_field="buy",
            ask_field="sell",
            bid_size_field="bestBidSize",
            ask_size_field="bestAskSize",
            quote_volume_field="volValue",
            base_volume_field="vol",
            last_price_field="last",
            change_field="changeRate",
            change_multiplier=Decimal("100"),
        )
        return _market_tickers(raw)

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        canonical, depth = self._request_values(symbol, depth)
        instrument = _separated_symbol(canonical, "-")
        book_size = 20 if depth <= 20 else 100
        payload = await self._get_json(
            f"/api/v1/market/orderbook/level2_{book_size}",
            params={"symbol": instrument},
        )
        if str(payload.get("code")) != "200000":
            detail = payload.get("msg") or payload.get("message") or "venue error"
            raise OrderBookPayloadError(f"{self.venue}: {detail}")

        snapshot = _require_mapping(payload.get("data"), self.venue, "data")
        timestamp = _timestamp_ms(
            snapshot.get("time"), venue=self.venue, field="data.time"
        )
        return _make_order_book(
            venue=self.venue,
            symbol=canonical,
            timestamp_ms=timestamp,
            bids=snapshot.get("bids"),
            asks=snapshot.get("asks"),
            snapshot_id=snapshot.get("sequence"),
            limit=depth,
        )


class MEXCPublicAdapter(BasePublicVenueAdapter):
    """MEXC V3 public spot market-data adapter."""

    venue = "mexc"
    default_base_url = "https://api.mexc.com"
    max_depth = 5_000

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        rows = await self._get_json_array("/api/v3/ticker/24hr", params={})
        receipt_timestamp = _ticker_timestamp_ms(
            self._clock_ms(), venue=self.venue, field="receipt timestamp"
        )
        raw = _parse_compact_ticker_rows(
            venue=self.venue,
            rows=rows,
            # closeTime is the last-trade time, not the freshness of the BBO
            # included in this successful all-market response.
            timestamp=lambda _row: receipt_timestamp,
            bid_field="bidPrice",
            ask_field="askPrice",
            bid_size_field="bidQty",
            ask_size_field="askQty",
            quote_volume_field="quoteVolume",
            base_volume_field="volume",
            last_price_field="lastPrice",
            change_field="priceChangePercent",
            # Despite the field name, MEXC documents this as a ratio (for
            # example 0.00400048 for roughly +0.400048%).
            change_multiplier=Decimal("100"),
        )
        return _market_tickers(raw)

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        canonical, depth = self._request_values(symbol, depth)
        payload = await self._get_json(
            "/api/v3/depth", params={"symbol": canonical, "limit": depth}
        )
        if "code" in payload and "bids" not in payload:
            detail = payload.get("msg") or f"venue error {payload.get('code')}"
            raise OrderBookPayloadError(f"{self.venue}: {detail}")

        timestamp = _timestamp_ms(
            self._clock_ms(), venue=self.venue, field="receipt timestamp"
        )
        return _make_order_book(
            venue=self.venue,
            symbol=canonical,
            timestamp_ms=timestamp,
            bids=payload.get("bids"),
            asks=payload.get("asks"),
            snapshot_id=payload.get("lastUpdateId"),
        )


class BingXPublicAdapter(BasePublicVenueAdapter):
    """BingX public spot market-data adapter."""

    venue = "bingx"
    default_base_url = "https://open-api.bingx.com"
    max_depth = 1_000

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        request_timestamp = self._clock_ms()
        payload = await self._get_ticker_json(
            "/openApi/spot/v1/ticker/24hr",
            params={"timestamp": request_timestamp},
        )
        if str(payload.get("code")) != "0":
            detail = payload.get("msg") or payload.get("message") or "venue error"
            raise TickerPayloadError(f"{self.venue}: {detail}")

        rows = _ticker_sequence(payload.get("data"), self.venue, "data")
        receipt_timestamp = _ticker_timestamp_ms(
            self._clock_ms(), venue=self.venue, field="receipt timestamp"
        )
        raw = _parse_compact_ticker_rows(
            venue=self.venue,
            rows=rows,
            # closeTime is a last-trade time and may be old for a thin pair.
            # Freshness follows receipt of this current all-market BBO snapshot.
            timestamp=lambda _row: receipt_timestamp,
            bid_field="bidPrice",
            ask_field="askPrice",
            bid_size_field="bidQty",
            ask_size_field="askQty",
            quote_volume_field="quoteVolume",
            base_volume_field="volume",
            last_price_field="lastPrice",
            change_field="priceChangePercent",
            change_parser=_bingx_percent,
        )
        return _market_tickers(raw)

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        canonical, depth = self._request_values(symbol, depth)
        instrument = _separated_symbol(canonical, "-")
        payload = await self._get_json(
            "/openApi/spot/v1/market/depth",
            params={
                "symbol": instrument,
                "limit": depth,
                "timestamp": self._clock_ms(),
            },
        )
        if str(payload.get("code")) != "0":
            detail = payload.get("msg") or payload.get("message") or "venue error"
            raise OrderBookPayloadError(f"{self.venue}: {detail}")

        snapshot = _require_mapping(payload.get("data"), self.venue, "data")
        timestamp = _timestamp_ms(
            snapshot.get("ts", payload.get("timestamp")),
            venue=self.venue,
            field="data.ts",
        )
        return _make_order_book(
            venue=self.venue,
            symbol=canonical,
            timestamp_ms=timestamp,
            bids=snapshot.get("bids"),
            asks=snapshot.get("asks"),
            snapshot_id=snapshot.get("lastUpdateId", snapshot.get("ts")),
        )


class GatePublicAdapter(BasePublicVenueAdapter):
    """Gate API v4 public spot market-data adapter."""

    venue = "gate"
    default_base_url = "https://api.gateio.ws/api/v4"
    max_depth = 100
    # Gate's all-market payload has no best-size fields. Twenty real books per
    # scan keep one cross monitor (2 s) plus one triangular monitor (10 s)
    # comfortably below Gate's public order-book request budget, while the
    # global nine-exchange universe can still contain 50 symbols.
    ticker_enrichment_limit = 20
    ticker_enrichment_concurrency = 20

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        # Gate's live all-market REST ticker omits quantities at the best
        # bid/ask.  Enrich a bounded candidate set with actual public order
        # books.  Non-standard extra fields and 24h volume are deliberately
        # never trusted as executable BBO depth.
        rows = await self._get_json_array("/spot/tickers", params={})
        candidates = _gate_ticker_candidates(
            rows,
            limit=self.ticker_enrichment_limit,
        )
        if not candidates:
            raise TickerPayloadError(
                "gate: all-market tickers contain no usable spot candidates"
            )

        # All enrichment requests below are dispatched as one bounded wave.
        # Gate's `current` field is the time the individual book last changed,
        # not the acquisition time of this fresh REST snapshot; using it as
        # freshness would falsely reject quiet but current books. Keep that
        # exchange value in the book snapshot id and use one local completion
        # timestamp for the coherent candidate batch.
        semaphore = asyncio.Semaphore(self.ticker_enrichment_concurrency)

        async def enrich(
            candidate: _GateTickerMetadata,
        ) -> tuple[_GateTickerMetadata, OrderBook] | None:
            try:
                async with semaphore:
                    book = await self.fetch_order_book(candidate.symbol, depth=1)
            except (PublicVenueError, TypeError, ValueError):
                # One suspended or disappearing pair must not invalidate the
                # coherent order books returned for the other candidates.
                return None
            return candidate, book

        enriched = await asyncio.gather(*(enrich(item) for item in candidates))
        available = tuple(item for item in enriched if item is not None)
        if not available:
            raise TickerPayloadError(
                "gate: no candidate order book could provide executable BBO depth"
            )
        batch_timestamp_ms = _ticker_timestamp_ms(
            self._clock_ms(),
            venue=self.venue,
            field="book enrichment acquisition timestamp",
        )
        return tuple(
            MarketTicker(
                venue=self.venue,
                symbol=candidate.symbol,
                base_asset=candidate.base_asset,
                quote_asset=candidate.quote_asset,
                timestamp_ms=batch_timestamp_ms,
                bid=book.best_bid,
                ask=book.best_ask,
                bid_size=book.bids[0].quantity,
                ask_size=book.asks[0].quantity,
                quote_volume=candidate.quote_volume,
                volume_usdt=candidate.volume_usdt,
                snapshot_id=book.snapshot_id,
                change_24h_pct=candidate.change_24h_pct,
            )
            for candidate, book in available
        )

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        canonical, depth = self._request_values(symbol, depth)
        instrument = _separated_symbol(canonical, "_")
        payload = await self._get_json(
            "/spot/order_book",
            params={
                "currency_pair": instrument,
                "limit": depth,
                "with_id": "true",
            },
        )
        if "label" in payload and "bids" not in payload:
            detail = payload.get("message") or payload.get("label") or "venue error"
            raise OrderBookPayloadError(f"{self.venue}: {detail}")

        timestamp = _timestamp_ms(
            payload.get("current", payload.get("update")),
            venue=self.venue,
            field="current",
        )
        return _make_order_book(
            venue=self.venue,
            symbol=canonical,
            timestamp_ms=timestamp,
            bids=payload.get("bids"),
            asks=payload.get("asks"),
            snapshot_id=payload.get("id", payload.get("order_book_id")),
        )


def _system_clock_ms() -> int:
    return time.time_ns() // 1_000_000


def _validate_depth(depth: int, maximum: int) -> int:
    if isinstance(depth, bool) or not isinstance(depth, int):
        raise TypeError("depth must be an integer")
    if not 1 <= depth <= maximum:
        raise ValueError(f"depth must be between 1 and {maximum}")
    return depth


def _normalise_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise TypeError("symbol must be a string")
    canonical = symbol.strip().upper()
    for separator in ("-", "/", "_"):
        canonical = canonical.replace(separator, "")
    if not canonical or not canonical.isascii() or not canonical.isalnum():
        raise ValueError("symbol must contain only ASCII letters and digits")
    return canonical


def _next_supported_depth(depth: int, supported: Sequence[int]) -> int:
    for value in supported:
        if depth <= value:
            return value
    return supported[-1]


_KNOWN_QUOTES = (
    "FDUSD",
    "PYUSD",
    "USDT",
    "USDC",
    "TUSD",
    "BUSD",
    "DAI",
    "USD",
    "EUR",
    "GBP",
    "BTC",
    "ETH",
    "BNB",
    "BRL",
    "TRY",
)

_STABLE_QUOTES = frozenset(
    {"USDT", "USDC", "FDUSD", "PYUSD", "TUSD", "BUSD", "DAI"}
)


@dataclass(frozen=True, slots=True)
class _RawTicker:
    venue: str
    symbol: str
    base_asset: str
    quote_asset: str
    timestamp_ms: int
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    quote_volume: Decimal
    reported_usdt_volume: Decimal | None = None
    change_24h_pct: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class _GateTickerMetadata:
    symbol: str
    base_asset: str
    quote_asset: str
    bid: Decimal
    ask: Decimal
    quote_volume: Decimal
    volume_usdt: Decimal
    change_24h_pct: Decimal


def _gate_ticker_candidates(
    rows: Sequence[Any],
    *,
    limit: int,
) -> tuple[_GateTickerMetadata, ...]:
    """Rank Gate metadata before bounded, real-order-book enrichment."""

    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            symbol = _normalise_symbol(row.get("currency_pair"))
            base_asset, quote_asset = _split_compact_symbol(symbol)
            bid = _ticker_positive_decimal(row.get("highest_bid"), "gate", "highest_bid")
            ask = _ticker_positive_decimal(row.get("lowest_ask"), "gate", "lowest_ask")
            if bid >= ask:
                continue
            try:
                quote_volume = _ticker_positive_decimal(
                    row.get("quote_volume"), "gate", "quote_volume"
                )
            except TickerPayloadError:
                base_volume = _ticker_positive_decimal(
                    row.get("base_volume"), "gate", "base_volume"
                )
                last = _ticker_positive_decimal(row.get("last"), "gate", "last")
                quote_volume = base_volume * last
            change = _ticker_optional_decimal(row.get("change_percentage")) or Decimal("0")
        except (TickerPayloadError, TypeError, ValueError):
            continue
        parsed.append(
            {
                "symbol": symbol,
                "base_asset": base_asset,
                "quote_asset": quote_asset,
                "bid": bid,
                "ask": ask,
                "quote_volume": quote_volume,
                "change": change,
            }
        )

    usdt_rates: dict[str, Decimal] = {
        asset: Decimal("1") for asset in _STABLE_QUOTES
    }
    for item in parsed:
        midpoint = (item["bid"] + item["ask"]) / Decimal("2")
        if item["quote_asset"] in _STABLE_QUOTES:
            usdt_rates.setdefault(item["base_asset"], midpoint)
        elif item["base_asset"] in _STABLE_QUOTES:
            usdt_rates.setdefault(
                item["quote_asset"], Decimal("1") / midpoint
            )

    ranked: list[_GateTickerMetadata] = []
    for item in parsed:
        volume_usdt = item["quote_volume"] * usdt_rates.get(
            item["quote_asset"], Decimal("0")
        )
        if volume_usdt <= 0:
            continue
        ranked.append(
            _GateTickerMetadata(
                symbol=item["symbol"],
                base_asset=item["base_asset"],
                quote_asset=item["quote_asset"],
                bid=item["bid"],
                ask=item["ask"],
                quote_volume=item["quote_volume"],
                volume_usdt=volume_usdt,
                change_24h_pct=item["change"],
            )
        )

    if limit <= 0:
        return ()

    def hybrid_select(
        items: Sequence[_GateTickerMetadata],
        count: int,
    ) -> list[_GateTickerMetadata]:
        """Keep a liquid core while reserving room for volatile markets."""

        if count <= 0:
            return []
        liquidity_pool = sorted(
            items,
            key=lambda item: (-item.volume_usdt, item.symbol),
        )[: max(count * 3, count)]
        liquid_count = max(1, (count * 7) // 10)
        chosen = list(liquidity_pool[:liquid_count])
        chosen_symbols = {item.symbol for item in chosen}
        for item in sorted(
            liquidity_pool,
            key=lambda value: (
                -abs(value.change_24h_pct),
                -value.volume_usdt,
                value.symbol,
            ),
        ):
            if len(chosen) >= count:
                break
            if item.symbol not in chosen_symbols:
                chosen.append(item)
                chosen_symbols.add(item.symbol)
        return chosen

    # A pure top-volume list is almost entirely USDT quoted. Reserve one fifth
    # of the bounded enrichment budget for liquid cross-quoted markets so Gate
    # can participate in triangular routes without weakening BBO truthfulness.
    stable_markets = [
        item for item in ranked if item.quote_asset in _STABLE_QUOTES
    ]
    cross_markets = [
        item for item in ranked if item.quote_asset not in _STABLE_QUOTES
    ]
    cross_count = min(len(cross_markets), max(1, limit // 5))
    stable_count = min(len(stable_markets), limit - cross_count)
    selected = hybrid_select(stable_markets, stable_count)
    selected.extend(hybrid_select(cross_markets, cross_count))

    selected_symbols = {item.symbol for item in selected}
    if len(selected) < limit:
        for item in hybrid_select(ranked, limit):
            if item.symbol not in selected_symbols:
                selected.append(item)
                selected_symbols.add(item.symbol)
            if len(selected) >= limit:
                break
    return tuple(selected)


def _parse_compact_ticker_rows(
    *,
    venue: str,
    rows: Sequence[Any],
    timestamp: Callable[[Mapping[str, Any]], int],
    bid_field: str,
    ask_field: str,
    bid_size_field: str,
    ask_size_field: str,
    quote_volume_field: str,
    symbol_field: str = "symbol",
    base_volume_field: str | None = None,
    last_price_field: str | None = None,
    usdt_volume_field: str | None = None,
    change_field: str | None = None,
    change_multiplier: Decimal = Decimal("1"),
    change_parser: Callable[[Any], Decimal | None] | None = None,
    open_field: str | None = None,
    close_field: str | None = None,
) -> tuple[_RawTicker, ...]:
    parsed: list[_RawTicker] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            symbol = _normalise_symbol(row.get(symbol_field))
            base_asset, quote_asset = _split_compact_symbol(symbol)
            bid = _ticker_positive_decimal(row.get(bid_field), venue, bid_field)
            ask = _ticker_positive_decimal(row.get(ask_field), venue, ask_field)
            bid_size = _ticker_positive_decimal(
                row.get(bid_size_field), venue, bid_size_field
            )
            ask_size = _ticker_positive_decimal(
                row.get(ask_size_field), venue, ask_size_field
            )
            try:
                quote_volume = _ticker_positive_decimal(
                    row.get(quote_volume_field), venue, quote_volume_field
                )
            except TickerPayloadError:
                if base_volume_field is None or last_price_field is None:
                    raise
                base_volume = _ticker_positive_decimal(
                    row.get(base_volume_field), venue, base_volume_field
                )
                last_price = _ticker_positive_decimal(
                    row.get(last_price_field), venue, last_price_field
                )
                quote_volume = base_volume * last_price
            if bid >= ask:
                raise TickerPayloadError(
                    f"{venue}: ticker must have a positive spread"
                )
            timestamp_ms = timestamp(row)
            reported_usdt_volume = (
                _ticker_optional_positive_decimal(row.get(usdt_volume_field))
                if usdt_volume_field is not None
                else None
            )
            raw_change = (
                (change_parser or _ticker_optional_decimal)(
                    row.get(change_field)
                )
                if change_field is not None
                else None
            )
            if raw_change is not None:
                change_24h_pct = raw_change * change_multiplier
            elif open_field is not None and close_field is not None:
                open_price = _ticker_optional_positive_decimal(row.get(open_field))
                close_price = _ticker_optional_positive_decimal(row.get(close_field))
                change_24h_pct = (
                    ((close_price / open_price) - Decimal("1")) * Decimal("100")
                    if open_price is not None and close_price is not None
                    else Decimal("0")
                )
            else:
                change_24h_pct = Decimal("0")
        except (TickerPayloadError, TypeError, ValueError):
            # All-ticker responses commonly contain newly listed, suspended, or
            # delisted markets with empty/zero top-of-book fields.  One such
            # market must not discard the otherwise coherent venue snapshot.
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        parsed.append(
            _RawTicker(
                venue=venue,
                symbol=symbol,
                base_asset=base_asset,
                quote_asset=quote_asset,
                timestamp_ms=timestamp_ms,
                bid=bid,
                ask=ask,
                bid_size=bid_size,
                ask_size=ask_size,
                quote_volume=quote_volume,
                reported_usdt_volume=reported_usdt_volume,
                change_24h_pct=change_24h_pct,
            )
        )
    return tuple(parsed)


def _parse_okx_ticker_rows(rows: Sequence[Any]) -> tuple[_RawTicker, ...]:
    parsed: list[_RawTicker] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            instrument_id = row.get("instId")
            if not isinstance(instrument_id, str):
                raise TickerPayloadError("okx: instId is invalid")
            parts = instrument_id.strip().upper().split("-")
            if (
                len(parts) != 2
                or not all(part and part.isascii() and part.isalnum() for part in parts)
            ):
                raise TickerPayloadError("okx: instId is invalid")
            base_asset, quote_asset = parts
            symbol = base_asset + quote_asset
            bid = _ticker_positive_decimal(row.get("bidPx"), "okx", "bidPx")
            ask = _ticker_positive_decimal(row.get("askPx"), "okx", "askPx")
            bid_size = _ticker_positive_decimal(row.get("bidSz"), "okx", "bidSz")
            ask_size = _ticker_positive_decimal(row.get("askSz"), "okx", "askSz")
            quote_volume = _ticker_positive_decimal(
                row.get("volCcy24h"), "okx", "volCcy24h"
            )
            if bid >= ask:
                raise TickerPayloadError(
                    "okx: ticker must have a positive spread"
                )
            timestamp_ms = _ticker_timestamp_ms(row.get("ts"), venue="okx", field="ts")
            last = _ticker_optional_positive_decimal(row.get("last"))
            open_24h = _ticker_optional_positive_decimal(row.get("open24h"))
            change_24h_pct = (
                ((last / open_24h) - Decimal("1")) * Decimal("100")
                if last is not None and open_24h is not None
                else Decimal("0")
            )
        except (TickerPayloadError, TypeError, ValueError):
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        parsed.append(
            _RawTicker(
                venue="okx",
                symbol=symbol,
                base_asset=base_asset,
                quote_asset=quote_asset,
                timestamp_ms=timestamp_ms,
                bid=bid,
                ask=ask,
                bid_size=bid_size,
                ask_size=ask_size,
                quote_volume=quote_volume,
                change_24h_pct=change_24h_pct,
            )
        )
    return tuple(parsed)


def _market_tickers(rows: Sequence[_RawTicker]) -> tuple[MarketTicker, ...]:
    usdt_rates: dict[str, Decimal] = {asset: Decimal("1") for asset in _STABLE_QUOTES}
    for row in rows:
        midpoint = (row.bid + row.ask) / Decimal("2")
        if row.quote_asset in _STABLE_QUOTES and row.base_asset not in _STABLE_QUOTES:
            usdt_rates.setdefault(row.base_asset, midpoint)
        elif row.base_asset in _STABLE_QUOTES and row.quote_asset not in _STABLE_QUOTES:
            usdt_rates.setdefault(row.quote_asset, Decimal("1") / midpoint)

    result: list[MarketTicker] = []
    for row in rows:
        if row.reported_usdt_volume is not None:
            volume_usdt = row.reported_usdt_volume
        else:
            quote_rate = usdt_rates.get(row.quote_asset, Decimal("0"))
            volume_usdt = row.quote_volume * quote_rate
        result.append(
            MarketTicker(
                venue=row.venue,
                symbol=row.symbol,
                base_asset=row.base_asset,
                quote_asset=row.quote_asset,
                timestamp_ms=row.timestamp_ms,
                bid=row.bid,
                ask=row.ask,
                bid_size=row.bid_size,
                ask_size=row.ask_size,
                quote_volume=row.quote_volume,
                volume_usdt=volume_usdt,
                # All-tickers endpoints do not expose a sequence number.  A
                # minute-bucketed BBO identity prevents PAPER mode from
                # repeatedly consuming unchanged displayed liquidity on every
                # poll without suppressing a route forever when the same BBO
                # legitimately reappears later.
                snapshot_id=(
                    f"{row.timestamp_ms // 60_000}:"
                    f"{row.bid}:{row.ask}:{row.bid_size}:{row.ask_size}"
                ),
                change_24h_pct=row.change_24h_pct,
            )
        )
    return tuple(result)


def _split_compact_symbol(symbol: str) -> tuple[str, str]:
    for quote in _KNOWN_QUOTES:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)], quote
    raise ValueError("symbol must end with a recognized quote asset")


def _separated_symbol(symbol: str, separator: str) -> str:
    base, quote = _split_compact_symbol(symbol)
    return f"{base}{separator}{quote}"


def _ticker_mapping(value: Any, venue: str, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TickerPayloadError(f"{venue}: {field} must be an object")
    return value


def _ticker_sequence(value: Any, venue: str, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TickerPayloadError(f"{venue}: {field} must be an array")
    return value


def _ticker_timestamp_ms(value: Any, *, venue: str, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise TickerPayloadError(f"{venue}: {field} is missing or invalid")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TickerPayloadError(f"{venue}: {field} is invalid") from exc
    if not numeric.is_finite() or numeric <= 0:
        raise TickerPayloadError(f"{venue}: {field} is invalid")
    timestamp = int(numeric)
    if timestamp < 100_000_000_000:
        timestamp *= 1_000
    elif timestamp >= 100_000_000_000_000_000:
        timestamp //= 1_000_000
    elif timestamp >= 100_000_000_000_000:
        timestamp //= 1_000
    return timestamp


def _ticker_positive_decimal(value: Any, venue: str, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise TickerPayloadError(f"{venue}: {field} is invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TickerPayloadError(f"{venue}: {field} is invalid") from exc
    if not result.is_finite() or result <= 0:
        raise TickerPayloadError(f"{venue}: {field} must be positive")
    return result


def _ticker_optional_positive_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result > 0 else None


def _ticker_optional_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _bingx_percent(value: Any) -> Decimal | None:
    """Parse BingX's documented percent string without double scaling it."""

    if isinstance(value, str):
        value = value.strip()
        if value.endswith("%"):
            value = value[:-1].strip()
    return _ticker_optional_decimal(value)


def _okx_instrument_id(original: str, canonical: str) -> str:
    del original  # separators are intentionally normalized across every venue
    for quote in _KNOWN_QUOTES:
        if canonical.endswith(quote) and len(canonical) > len(quote):
            return f"{canonical[:-len(quote)]}-{quote}"
    raise ValueError(
        "OKX symbol must end with a recognized quote asset, for example BTCUSDT"
    )


def _require_mapping(value: Any, venue: str, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OrderBookPayloadError(f"{venue}: {field} must be an object")
    return value


def _require_sequence(value: Any, venue: str, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise OrderBookPayloadError(f"{venue}: {field} must be an array")
    return value


def _timestamp_ms(value: Any, *, venue: str, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise OrderBookPayloadError(f"{venue}: {field} is missing or invalid")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OrderBookPayloadError(f"{venue}: {field} is invalid") from exc
    if not numeric.is_finite() or numeric <= 0:
        raise OrderBookPayloadError(f"{venue}: {field} is invalid")

    timestamp = int(numeric)
    # Normalize seconds, microseconds, or nanoseconds when a venue/proxy changes
    # units.  All four current venue schemas normally return milliseconds.
    if timestamp < 100_000_000_000:
        timestamp *= 1_000
    elif timestamp >= 100_000_000_000_000_000:
        timestamp //= 1_000_000
    elif timestamp >= 100_000_000_000_000:
        timestamp //= 1_000
    return timestamp


def _make_order_book(
    *,
    venue: str,
    symbol: str,
    timestamp_ms: int,
    bids: Any,
    asks: Any,
    snapshot_id: Any = None,
    limit: int | None = None,
) -> OrderBook:
    normalized_bids = _levels(bids, venue=venue, side="bids", reverse=True)
    normalized_asks = _levels(asks, venue=venue, side="asks", reverse=False)
    if limit is not None:
        normalized_bids = normalized_bids[:limit]
        normalized_asks = normalized_asks[:limit]
    if normalized_bids[0].price >= normalized_asks[0].price:
        raise OrderBookPayloadError(
            f"{venue}: locked or crossed order book (best bid must be below best ask)"
        )
    return OrderBook(
        venue=venue,
        symbol=symbol,
        timestamp_ms=timestamp_ms,
        bids=normalized_bids,
        asks=normalized_asks,
        snapshot_id=None if snapshot_id is None else str(snapshot_id),
    )


def _levels(
    raw_levels: Any, *, venue: str, side: str, reverse: bool
) -> tuple[PriceLevel, ...]:
    rows = _require_sequence(raw_levels, venue, side)
    if not rows:
        raise OrderBookPayloadError(f"{venue}: {side} must not be empty")

    levels: list[PriceLevel] = []
    for index, row in enumerate(rows):
        if isinstance(row, (str, bytes)) or not isinstance(row, Sequence):
            raise OrderBookPayloadError(
                f"{venue}: {side}[{index}] must be a price/quantity array"
            )
        if len(row) < 2:
            raise OrderBookPayloadError(
                f"{venue}: {side}[{index}] must contain price and quantity"
            )
        price = _positive_decimal(row[0], venue, f"{side}[{index}].price")
        quantity = _positive_decimal(row[1], venue, f"{side}[{index}].quantity")
        levels.append(PriceLevel(price=price, quantity=quantity))

    levels.sort(key=lambda level: level.price, reverse=reverse)
    return tuple(levels)


def _positive_decimal(value: Any, venue: str, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise OrderBookPayloadError(f"{venue}: {field} is invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OrderBookPayloadError(f"{venue}: {field} is invalid") from exc
    if not result.is_finite() or result <= 0:
        raise OrderBookPayloadError(f"{venue}: {field} must be positive")
    return result


# Concise aliases are kept for callers that do not need the explicit "Public"
# qualifier.  Every class remains public-data-only.
BybitAdapter = BybitPublicAdapter
BinanceAdapter = BinancePublicAdapter
OKXPublicAdapter = OkxPublicAdapter
OKXAdapter = OkxPublicAdapter
BitgetAdapter = BitgetPublicAdapter
HtxPublicAdapter = HuobiPublicAdapter
HTXPublicAdapter = HuobiPublicAdapter
KucoinPublicAdapter = KuCoinPublicAdapter
MexcPublicAdapter = MEXCPublicAdapter
BingxPublicAdapter = BingXPublicAdapter
GateIOPublicAdapter = GatePublicAdapter
GateioPublicAdapter = GatePublicAdapter
HuobiAdapter = HuobiPublicAdapter
HTXAdapter = HuobiPublicAdapter
KuCoinAdapter = KuCoinPublicAdapter
MEXCAdapter = MEXCPublicAdapter
BingXAdapter = BingXPublicAdapter
GateAdapter = GatePublicAdapter
