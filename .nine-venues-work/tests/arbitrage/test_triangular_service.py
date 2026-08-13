from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from packages.arbitrage.triangular import MarketTicker
from packages.arbitrage.triangular_service import (
    TriangularPaperService,
    TriangularScanSettings,
)


pytestmark = pytest.mark.contract
D = Decimal
NOW_MS = 1_800_000_000_000


def ticker(
    venue: str,
    symbol: str,
    base: str,
    quote: str,
    bid: str,
    ask: str,
    *,
    timestamp_ms: int = NOW_MS,
    snapshot_id: str | None = None,
    volume_usdt: str = "1000000",
) -> MarketTicker:
    return MarketTicker(
        venue=venue,
        symbol=symbol,
        base_asset=base,
        quote_asset=quote,
        timestamp_ms=timestamp_ms,
        bid=bid,
        ask=ask,
        bid_size="100",
        ask_size="100",
        quote_volume="1000000",
        volume_usdt=volume_usdt,
        snapshot_id=snapshot_id or f"{symbol}-1",
    )


def profitable_triangle(venue: str) -> tuple[MarketTicker, ...]:
    # USDT -> BTC -> ETH -> USDT = 1.03 before three 10 bps fees.
    return (
        ticker(venue, "BTCUSDT", "BTC", "USDT", "99", "100"),
        ticker(venue, "ETHBTC", "ETH", "BTC", "0.49", "0.5"),
        ticker(venue, "ETHUSDT", "ETH", "USDT", "51.5", "52"),
    )


class FakeTickerAdapter:
    def __init__(
        self,
        venue: str,
        tickers: tuple[MarketTicker, ...] | Exception,
        *,
        delay: float = 0,
    ) -> None:
        self.venue = venue
        self.tickers = tickers
        self.delay = delay
        self.fetch_count = 0
        self.closed = False

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        self.fetch_count += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.tickers, Exception):
            raise self.tickers
        return self.tickers

    async def aclose(self) -> None:
        self.closed = True


def make_service(*adapters: FakeTickerAdapter) -> TriangularPaperService:
    return TriangularPaperService(
        adapters,
        initial_balances={
            adapter.venue: {"USDT": "10000", "BTC": "10", "ETH": "100"}
            for adapter in adapters
        },
        taker_fees={adapter.venue: "0.001" for adapter in adapters},
        clock_ms=lambda: NOW_MS,
    )


@pytest.mark.asyncio
async def test_scan_uses_one_all_tickers_call_and_reports_cycle() -> None:
    adapter = FakeTickerAdapter("alpha", profitable_triangle("alpha"))
    service = make_service(adapter)

    result = await service.scan(
        TriangularScanSettings(
            venue="all",
            start_asset="USDT",
            start_amount="500",
            min_net_edge_bps="1",
            risk_buffer_bps="2",
            max_tickers=50,
        )
    )

    assert adapter.fetch_count == 1
    assert result["strategy"] == "triangular"
    assert result["best_opportunity"]["route"] == ["USDT", "BTC", "ETH", "USDT"]
    assert len(result["best_opportunity"]["legs"]) == 3
    assert D(result["best_opportunity"]["net_edge_bps"]) > 0
    assert result["ticker_universe"]["alpha"]["count"] == 3
    assert result["venues"][0]["selected_ticker_count"] == 3
    assert result["metrics"]["trade_count"] == 0
    assert result["live_trading_enabled"] is False


@pytest.mark.asyncio
async def test_auto_paper_is_atomic_and_same_snapshot_is_not_reused() -> None:
    adapter = FakeTickerAdapter("alpha", profitable_triangle("alpha"))
    service = make_service(adapter)
    settings = TriangularScanSettings(
        start_amount="500",
        min_net_edge_bps="1",
        risk_buffer_bps="2",
        auto_execute=True,
    )
    before = D(service.status()["balances"]["alpha"]["USDT"])

    first = await service.scan(settings)
    second = await service.scan(settings)

    assert first["metrics"]["trade_count"] == 1
    assert D(first["balances"]["alpha"]["USDT"]) > before
    assert first["journal"][0]["status"] == "paper_filled"
    assert first["journal"][0]["path"] == "USDT → BTC → ETH → USDT"
    assert len(first["journal"][0]["legs"]) == 3
    assert all(
        D(leg["fee_rate_bps"]) == D("10")
        for leg in first["journal"][0]["legs"]
    )
    assert second["metrics"]["trade_count"] == 1
    assert "already executed" in second["errors"]["duplicate_snapshot"]


@pytest.mark.asyncio
async def test_fee_token_toggle_applies_effective_rate_to_all_three_legs() -> None:
    def make_discount_service() -> TriangularPaperService:
        adapter = FakeTickerAdapter(
            "binance",
            profitable_triangle("binance"),
        )
        return TriangularPaperService(
            (adapter,),
            initial_balances={"binance": {"USDT": "10000"}},
            taker_fees={"binance": "0.001"},
            clock_ms=lambda: NOW_MS,
        )

    enabled = await make_discount_service().scan(
        TriangularScanSettings(
            venue="binance",
            start_amount="500",
            min_net_edge_bps="1",
            risk_buffer_bps="0",
            auto_execute=True,
            use_fee_token_discounts=True,
        )
    )
    disabled = await make_discount_service().scan(
        TriangularScanSettings(
            venue="binance",
            start_amount="500",
            min_net_edge_bps="1",
            risk_buffer_bps="0",
            auto_execute=True,
            use_fee_token_discounts=False,
        )
    )

    for leg in enabled["best_opportunity"]["legs"]:
        assert D(leg["fee"]) / D(leg["output_before_fee"]) == D("0.00075")
        assert D(leg["fee_rate_bps"]) == D("7.5")
    for leg in disabled["best_opportunity"]["legs"]:
        assert D(leg["fee"]) / D(leg["output_before_fee"]) == D("0.001")
    assert D(enabled["metrics"]["realized_pnl"]) == D(
        "13.84211884523437500"
    )
    assert D(disabled["metrics"]["realized_pnl"]) == D("13.45654448500")
    assert enabled["fee_policy"]["binance"]["effective_taker_fee"] == (
        "0.00075"
    )
    assert all(
        D(leg["fee_rate_bps"]) == D("7.5")
        for leg in enabled["journal"][0]["legs"]
    )


@pytest.mark.asyncio
async def test_failed_and_unselected_venues_are_isolated() -> None:
    good = FakeTickerAdapter("alpha", profitable_triangle("alpha"))
    broken = FakeTickerAdapter("beta", RuntimeError("maintenance"))
    service = make_service(good, broken)

    result = await service.scan(
        TriangularScanSettings(venue="all", min_net_edge_bps="1")
    )
    assert result["best_opportunity"]["venue"] == "alpha"
    assert "maintenance" in result["errors"]["beta"]

    only_alpha = await service.scan(
        TriangularScanSettings(venue="alpha", min_net_edge_bps="1")
    )
    beta = next(row for row in only_alpha["venues"] if row["name"] == "beta")
    assert beta["status"] == "not_selected"
    assert broken.fetch_count == 1


@pytest.mark.asyncio
async def test_stop_during_initial_fetch_prevents_late_execution() -> None:
    adapter = FakeTickerAdapter(
        "alpha", profitable_triangle("alpha"), delay=0.05
    )
    service = make_service(adapter)
    start_task = asyncio.create_task(
        service.start(
            TriangularScanSettings(
                auto_execute=True,
                min_net_edge_bps="1",
                interval_ms=10_000,
            )
        )
    )
    await asyncio.sleep(0.005)

    stopped = await service.stop()
    started_result = await start_task

    assert stopped["running"] is False
    assert started_result["running"] is False
    assert service.status()["metrics"]["scan_count"] == 0
    assert service.status()["metrics"]["trade_count"] == 0


@pytest.mark.asyncio
async def test_reset_and_close_restore_paper_state() -> None:
    adapter = FakeTickerAdapter("alpha", profitable_triangle("alpha"))
    service = make_service(adapter)
    await service.scan(
        TriangularScanSettings(auto_execute=True, min_net_edge_bps="1")
    )

    reset = await service.reset()
    assert reset["metrics"]["scan_count"] == 0
    assert reset["metrics"]["trade_count"] == 0
    assert reset["ticker_universe"] == {}

    await service.close()
    assert adapter.closed is True
