from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from packages.arbitrage import MarketTicker, OrderBook, PriceLevel
from packages.arbitrage.service import ArbitragePaperService, ScanSettings


pytestmark = pytest.mark.contract
D = Decimal
NOW_MS = 1_800_000_000_000


class FakeAdapter:
    def __init__(self, venue: str, book: OrderBook | Exception) -> None:
        self.venue = venue
        self.book = book
        self.closed = False

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        assert depth == 50
        if isinstance(self.book, Exception):
            raise self.book
        assert self.book.symbol == symbol
        return self.book

    async def aclose(self) -> None:
        self.closed = True


class SlowAdapter(FakeAdapter):
    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        await asyncio.sleep(0.05)
        return await super().fetch_order_book(symbol, depth)


class AutoAdapter(FakeAdapter):
    def __init__(self, venue: str, rows: tuple[MarketTicker, ...]) -> None:
        self.venue = venue
        self.rows = rows
        self.closed = False
        self.ticker_fetch_count = 0

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        self.ticker_fetch_count += 1
        return self.rows


class SequencedAutoAdapter(AutoAdapter):
    def __init__(
        self,
        venue: str,
        rows_by_scan: tuple[tuple[MarketTicker, ...], ...],
    ) -> None:
        super().__init__(venue, rows_by_scan[0])
        self.rows_by_scan = rows_by_scan

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        index = min(self.ticker_fetch_count, len(self.rows_by_scan) - 1)
        self.ticker_fetch_count += 1
        return self.rows_by_scan[index]


class SlowAutoAdapter(AutoAdapter):
    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        await asyncio.sleep(0.05)
        return await super().fetch_tickers()


def make_ticker(
    venue: str,
    base: str,
    bid: str,
    ask: str,
    *,
    volume: str,
    change: str,
    snapshot_id: str | None = None,
    timestamp_ms: int = NOW_MS,
    bid_size: str = "100000",
    ask_size: str = "100000",
) -> MarketTicker:
    return MarketTicker(
        venue=venue,
        symbol=f"{base}USDT",
        base_asset=base,
        quote_asset="USDT",
        timestamp_ms=timestamp_ms,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        quote_volume=volume,
        volume_usdt=volume,
        snapshot_id=snapshot_id or f"{base}-1",
        change_24h_pct=change,
    )


def make_book(venue: str, bid: str, ask: str, *, ts: int = NOW_MS) -> OrderBook:
    return OrderBook(
        venue=venue,
        symbol="BTCUSDT",
        timestamp_ms=ts,
        bids=(PriceLevel(bid, "10"),),
        asks=(PriceLevel(ask, "10"),),
    )


def service_with(*adapters: FakeAdapter) -> ArbitragePaperService:
    return ArbitragePaperService(
        adapters,
        initial_balances={
            adapter.venue: {"USDT": "10000", "BTC": "10"}
            for adapter in adapters
        },
        taker_fees={adapter.venue: "0.001" for adapter in adapters},
        clock_ms=lambda: NOW_MS,
    )


@pytest.mark.asyncio
async def test_scan_is_venue_neutral_and_does_not_execute_by_default() -> None:
    service = service_with(
        FakeAdapter("alpha", make_book("alpha", "99", "100")),
        FakeAdapter("beta", make_book("beta", "101", "102")),
        FakeAdapter("gamma", make_book("gamma", "103", "104")),
    )

    result = await service.scan(
        ScanSettings(notional="500", min_net_edge_bps="1", risk_buffer_bps="1")
    )

    assert result["best_opportunity"]["route"] == "alpha->gamma"
    assert {item["route"] for item in result["opportunities"]} == {
        "alpha->beta",
        "alpha->gamma",
        "beta->gamma",
    }
    assert result["metrics"]["trade_count"] == 0
    assert result["metrics"]["realized_pnl"] == "0"
    assert result["metrics"]["strategy_pnl_usdt"] is None
    assert result["metrics"]["strategy_equity_usdt"] is None
    assert result["live_trading_enabled"] is False
    assert result["public_data_only"] is True


@pytest.mark.asyncio
async def test_auto_execute_changes_only_virtual_balances_and_journal() -> None:
    service = service_with(
        FakeAdapter("cheap", make_book("cheap", "99", "100")),
        FakeAdapter("rich", make_book("rich", "102", "103")),
    )
    before = service.status()["balances"]

    result = await service.scan(
        ScanSettings(
            notional="500",
            min_net_edge_bps="1",
            risk_buffer_bps="2",
            auto_execute=True,
        )
    )

    assert result["balances"] != before
    assert D(result["balances"]["cheap"]["USDT"]) < D(before["cheap"]["USDT"])
    assert D(result["balances"]["rich"]["BTC"]) < D(before["rich"]["BTC"])
    assert result["metrics"]["trade_count"] == 1
    assert D(result["metrics"]["realized_pnl"]) > 0
    assert result["journal"][0]["status"] == "paper_filled"
    assert result["journal"][0]["buy_venue"] == "cheap"
    assert result["journal"][0]["sell_venue"] == "rich"


@pytest.mark.asyncio
async def test_failed_venue_is_isolated_and_other_pair_still_scans() -> None:
    service = service_with(
        FakeAdapter("cheap", make_book("cheap", "99", "100")),
        FakeAdapter("broken", RuntimeError("maintenance")),
        FakeAdapter("rich", make_book("rich", "102", "103")),
    )

    result = await service.scan(ScanSettings(min_net_edge_bps="1"))

    assert result["best_opportunity"]["route"] == "cheap->rich"
    assert "maintenance" in result["errors"]["broken"]
    broken = next(item for item in result["venues"] if item["name"] == "broken")
    assert broken["ok"] is False
    assert broken["status"] == "error"


@pytest.mark.asyncio
async def test_stale_book_is_reported_and_excluded() -> None:
    service = service_with(
        FakeAdapter("old", make_book("old", "99", "100", ts=NOW_MS - 20_000)),
        FakeAdapter("fresh", make_book("fresh", "102", "103")),
    )

    result = await service.scan(ScanSettings())

    assert result["best_opportunity"] is None
    assert "stale order book" in result["errors"]["old"]
    old = next(item for item in result["venues"] if item["name"] == "old")
    assert old["status"] == "stale"


@pytest.mark.asyncio
async def test_profitable_but_time_skewed_pair_is_excluded() -> None:
    service = service_with(
        FakeAdapter("lagging", make_book("lagging", "99", "100", ts=NOW_MS - 3_000)),
        FakeAdapter("fresh", make_book("fresh", "102", "103")),
    )

    result = await service.scan(ScanSettings(min_net_edge_bps="1"))

    assert result["best_opportunity"] is None
    assert "excluded 1 opportunity" in result["errors"]["market_data_skew"]
    assert result["market_data_policy"]["max_pair_skew_ms"] == 2_000


@pytest.mark.asyncio
async def test_monitor_start_stop_reset_and_close() -> None:
    adapters = (
        FakeAdapter("cheap", make_book("cheap", "99", "100")),
        FakeAdapter("rich", make_book("rich", "102", "103")),
    )
    service = service_with(*adapters)
    settings = ScanSettings(interval_ms=500, auto_execute=True, min_net_edge_bps="1")

    started = await service.start(settings)
    assert started["running"] is True
    assert started["metrics"]["scan_count"] == 1
    with pytest.raises(RuntimeError, match="already running"):
        await service.start(settings)

    stopped = await service.stop()
    assert stopped["running"] is False
    reset = await service.reset()
    assert reset["metrics"]["scan_count"] == 0
    assert reset["metrics"]["trade_count"] == 0
    assert reset["journal"] == []

    await service.close()
    assert all(adapter.closed for adapter in adapters)


@pytest.mark.asyncio
async def test_same_snapshot_pair_is_never_paper_executed_twice() -> None:
    service = service_with(
        FakeAdapter("cheap", make_book("cheap", "99", "100")),
        FakeAdapter("rich", make_book("rich", "102", "103")),
    )
    settings = ScanSettings(
        notional="100", auto_execute=True, min_net_edge_bps="1"
    )

    first = await service.scan(settings)
    second = await service.scan(settings)

    assert first["metrics"]["trade_count"] == 1
    assert second["metrics"]["trade_count"] == 1
    assert "already executed snapshot pair" in second["errors"]["duplicate_snapshot"]


@pytest.mark.asyncio
async def test_stop_during_initial_fetch_prevents_late_paper_execution() -> None:
    service = service_with(
        SlowAdapter("cheap", make_book("cheap", "99", "100")),
        SlowAdapter("rich", make_book("rich", "102", "103")),
    )
    start_task = asyncio.create_task(
        service.start(
            ScanSettings(auto_execute=True, min_net_edge_bps="1", interval_ms=500)
        )
    )
    await asyncio.sleep(0.005)

    stopped = await service.stop()
    started_result = await start_task

    assert stopped["running"] is False
    assert started_result["running"] is False
    assert service.status()["metrics"]["trade_count"] == 0
    assert service.status()["metrics"]["scan_count"] == 0


@pytest.mark.asyncio
async def test_reset_serializes_with_a_new_start_during_initial_fetch() -> None:
    """A restart cannot repopulate state while reset is still clearing it."""

    service = service_with(
        SlowAdapter("cheap", make_book("cheap", "99", "100")),
        SlowAdapter("rich", make_book("rich", "102", "103")),
    )
    settings = ScanSettings(
        auto_execute=True,
        min_net_edge_bps="1",
        interval_ms=500,
    )
    first_start = asyncio.create_task(service.start(settings))
    await asyncio.sleep(0.005)
    reset_task = asyncio.create_task(service.reset())
    await asyncio.sleep(0.005)
    restart_task = asyncio.create_task(service.start(settings))

    _first, reset, restarted = await asyncio.gather(
        first_start,
        reset_task,
        restart_task,
    )

    assert reset["running"] is False
    assert reset["metrics"]["scan_count"] == 0
    assert restarted["running"] is True
    assert restarted["metrics"]["scan_count"] == 1
    assert service.status()["running"] is True
    await service.stop()


@pytest.mark.asyncio
async def test_auto_selects_common_liquid_volatile_symbols_and_scans_them() -> None:
    alpha = AutoAdapter(
        "alpha",
        (
            make_ticker("alpha", "CALM", "99", "100", volume="5000000", change="1"),
            make_ticker("alpha", "FAST", "102", "103", volume="6000000", change="9"),
            make_ticker("alpha", "THIN", "100", "101", volume="10", change="100"),
        ),
    )
    beta = AutoAdapter(
        "beta",
        (
            make_ticker("beta", "CALM", "99", "100", volume="5000000", change="1"),
            make_ticker("beta", "FAST", "106", "107", volume="6000000", change="8"),
            make_ticker("beta", "THIN", "200", "201", volume="10", change="100"),
        ),
    )
    service = ArbitragePaperService(
        (alpha, beta),
        initial_balances={
            "alpha": {"USDT": "10000", "FAST": "100"},
            "beta": {"USDT": "10000", "FAST": "100"},
        },
        taker_fees={"alpha": "0.001", "beta": "0.001"},
        clock_ms=lambda: NOW_MS,
    )

    result = await service.scan(
        ScanSettings(
            symbol="AUTO",
            max_symbols=2,
            notional="25",
            min_net_edge_bps="1",
        )
    )

    assert alpha.ticker_fetch_count == beta.ticker_fetch_count == 1
    assert [row["symbol"] for row in result["universe"]] == [
        "FASTUSDT",
        "CALMUSDT",
    ]
    assert result["best_opportunity"]["symbol"] == "FASTUSDT"
    assert result["metrics"]["symbol_count"] == 2
    assert result["metrics"]["book_count"] == 4


def test_auto_settings_validate_limit_and_safe_poll_interval() -> None:
    with pytest.raises(ValueError, match="AUTO interval_ms"):
        ScanSettings(symbol="AUTO", interval_ms=1000)
    with pytest.raises(ValueError, match="between 1 and 50"):
        ScanSettings(symbol="AUTO", max_symbols=51)


def test_auto_settings_validate_configurable_risk_budget() -> None:
    custom = ScanSettings(
        symbol="AUTO",
        notional="30",
        activation_observations=3,
        evidence_window_minutes=15,
        inventory_idle_timeout_minutes=90,
        max_symbols=10,
        max_active_symbols=3,
        allocation_per_symbol_venue_usdt="60",
        min_24h_volume_usdt="1500000",
        bbo_depth_multiplier="3",
    )

    assert custom.evidence_window_ms == 15 * 60 * 1000
    assert custom.inventory_idle_timeout_ms == 90 * 60 * 1000
    assert custom.activation_min_bbo_notional_usdt == D("90")
    assert custom.auto_base_target_usdt == D("180")
    assert custom.auto_usdt_reserve_target == D("320")
    assert custom.auto_execution_base_cap_usdt == D("210")
    assert custom.auto_execution_usdt_floor == D("290")
    assert custom.to_dict()["allocation_per_symbol_venue_usdt"] == "60"
    assert custom.to_dict()["min_24h_volume_usdt"] == "1500000"

    with pytest.raises(ValueError, match="at least 10"):
        ScanSettings(symbol="AUTO", notional="9")
    with pytest.raises(ValueError, match="greater than or equal"):
        ScanSettings(
            symbol="AUTO",
            notional="60",
            allocation_per_symbol_venue_usdt="50",
        )
    with pytest.raises(ValueError, match="must not exceed max_symbols"):
        ScanSettings(symbol="AUTO", max_symbols=2, max_active_symbols=3)
    with pytest.raises(ValueError, match="budget exceeds 500"):
        ScanSettings(
            symbol="AUTO",
            notional="60",
            max_active_symbols=5,
            allocation_per_symbol_venue_usdt="90",
        )

    # AUTO-only controls do not reduce the legacy manual notional range.
    assert ScanSettings(symbol="BTCUSDT", notional="500").notional == D("500")


@pytest.mark.asyncio
async def test_stop_during_auto_fetch_does_not_seed_late_inventory() -> None:
    bybit = SlowAutoAdapter(
        "bybit",
        (make_ticker("bybit", "FAST", "99", "100", volume="5000000", change="9"),),
    )
    binance = SlowAutoAdapter(
        "binance",
        (make_ticker("binance", "FAST", "102", "103", volume="5000000", change="8"),),
    )
    service = ArbitragePaperService(
        (bybit, binance),
        clock_ms=lambda: NOW_MS,
    )
    start_task = asyncio.create_task(
        service.start(
            ScanSettings(
                symbol="AUTO",
                auto_execute=True,
                min_net_edge_bps="1",
            )
        )
    )
    await asyncio.sleep(0.005)

    await service.stop()
    await start_task

    assert service.status()["metrics"]["scan_count"] == 0
    assert "FAST" not in service.status()["balances"]["bybit"]
    assert "FAST" not in service.status()["balances"]["binance"]


@pytest.mark.asyncio
async def test_auto_allocates_after_five_distinct_signals_and_caps_trade() -> None:
    bybit = SequencedAutoAdapter(
        "bybit",
        tuple(
            (
                make_ticker(
                    "bybit",
                    "FAST",
                    "99",
                    "100",
                    volume="5000000",
                    change="9",
                    snapshot_id=f"fast-bybit-{index}",
                ),
            )
            for index in range(1, 6)
        ),
    )
    binance = SequencedAutoAdapter(
        "binance",
        tuple(
            (
                make_ticker(
                    "binance",
                    "FAST",
                    "103",
                    "104",
                    volume="5000000",
                    change="8",
                    snapshot_id=f"fast-binance-{index}",
                ),
            )
            for index in range(1, 6)
        ),
    )
    service = ArbitragePaperService(
        (bybit, binance),
        clock_ms=lambda: NOW_MS,
    )
    settings = ScanSettings(
        symbol="AUTO",
        notional="25",
        min_net_edge_bps="1",
        auto_execute=True,
    )

    for expected_observations in range(1, 5):
        result = await service.scan(settings)
        assert result["metrics"]["trade_count"] == 0
        assert result["active_inventory"] == []
        assert result["candidate_evidence"][0]["qualifying_observations"] == (
            expected_observations
        )
        assert result["balances"]["bybit"] == {"USDT": "500"}
        assert result["balances"]["binance"] == {"USDT": "500"}

    activated = await service.scan(settings)

    assert activated["metrics"]["trade_count"] == 1
    assert activated["journal"][0]["symbol"] == "FASTUSDT"
    assert D(activated["journal"][0]["notional_usdt"]) <= D("25")
    assert activated["metrics"]["active_inventory_count"] == 1
    assert activated["candidate_evidence"][0]["qualifying_observations"] == 5
    inventory = activated["active_inventory"][0]
    assert inventory["symbol"] == "FASTUSDT"
    assert inventory["evidence_observations"] == 5
    assert D(inventory["total_quote_spent_usdt"]) == D("100")
    assert len(inventory["allocations"]) == 2
    for venue in ("bybit", "binance"):
        assert D(activated["balances"][venue]["USDT"]) >= D("400")
        assert "FAST" in activated["balances"][venue]
    assert activated["market_data_policy"]["auto_initial_usdt_per_venue"] == "500"
    assert activated["market_data_policy"]["auto_max_active_symbols"] == 2
    assert activated["market_data_policy"]["auto_activation_observations"] == 5
    assert activated["market_data_policy"]["auto_max_trade_usdt"] == "25"
    assert activated["market_data_policy"]["auto_min_24h_volume_usdt"] == "1000000"
    assert activated["market_data_policy"]["auto_bbo_depth_multiplier"] == "2"
    assert (
        activated["market_data_policy"]["auto_inventory_idle_timeout_ms"]
        == 60 * 60 * 1000
    )


@pytest.mark.asyncio
async def test_auto_prepositions_without_profitable_spread_then_waits_for_edge(
) -> None:
    """Inventory readiness is independent; execution remains engine-strict."""

    def rows(venue: str) -> tuple[tuple[MarketTicker, ...], ...]:
        calm = tuple(
            (
                make_ticker(
                    venue,
                    "READY",
                    "99",
                    "100",
                    volume="1000000",
                    change="9",
                    snapshot_id=f"calm-{venue}-{index}",
                ),
            )
            for index in range(5)
        )
        profitable = (
            make_ticker(
                venue,
                "READY",
                "99" if venue == "cheap" else "103",
                "100" if venue == "cheap" else "104",
                volume="1000000",
                change="9",
                snapshot_id=f"profit-{venue}",
            ),
        )
        return calm + (profitable,)

    service = ArbitragePaperService(
        (
            SequencedAutoAdapter("cheap", rows("cheap")),
            SequencedAutoAdapter("rich", rows("rich")),
        ),
        clock_ms=lambda: NOW_MS,
    )
    settings = ScanSettings(
        symbol="AUTO",
        auto_execute=True,
        min_net_edge_bps="5",
        max_active_symbols=1,
    )

    for _ in range(5):
        positioned = await service.scan(settings)

    assert positioned["active_symbols"] == ["READYUSDT"]
    assert positioned["best_opportunity"] is None
    assert positioned["metrics"]["trade_count"] == 0
    assert positioned["candidate_evidence"][0]["qualifying_observations"] == 5

    traded = await service.scan(settings)
    assert traded["best_opportunity"]["symbol"] == "READYUSDT"
    assert traded["metrics"]["trade_count"] == 1


@pytest.mark.asyncio
async def test_auto_prioritizes_current_profitable_route_for_a_scarce_slot(
) -> None:
    cheap = AutoAdapter(
        "cheap",
        (
            make_ticker(
                "cheap", "VOL", "99", "100",
                volume="3000000", change="50", snapshot_id="vol-cheap",
            ),
            make_ticker(
                "cheap", "EDGE", "99", "100",
                volume="3000000", change="1", snapshot_id="edge-cheap",
            ),
        ),
    )
    rich = AutoAdapter(
        "rich",
        (
            make_ticker(
                "rich", "VOL", "99", "100",
                volume="3000000", change="49", snapshot_id="vol-rich",
            ),
            make_ticker(
                "rich", "EDGE", "103", "104",
                volume="3000000", change="1", snapshot_id="edge-rich",
            ),
        ),
    )
    service = ArbitragePaperService((cheap, rich), clock_ms=lambda: NOW_MS)

    result = await service.scan(
        ScanSettings(
            symbol="AUTO",
            max_symbols=2,
            max_active_symbols=1,
            activation_observations=1,
            auto_execute=True,
            min_net_edge_bps="5",
        )
    )

    assert [row["symbol"] for row in result["universe"]] == [
        "VOLUSDT",
        "EDGEUSDT",
    ]
    assert result["active_symbols"] == ["EDGEUSDT"]
    assert result["best_opportunity"]["symbol"] == "EDGEUSDT"
    assert result["metrics"]["trade_count"] == 1
    assert result["journal"][0]["symbol"] == "EDGEUSDT"


@pytest.mark.asyncio
async def test_auto_preserves_profit_priority_when_only_one_slot_is_free(
) -> None:
    def first(venue: str) -> tuple[MarketTicker, ...]:
        return (
            make_ticker(
                venue, "OLD", "99", "100",
                volume="3000000", change="5", snapshot_id=f"old-1-{venue}",
            ),
        )

    def second(venue: str) -> tuple[MarketTicker, ...]:
        return (
            make_ticker(
                venue, "OLD", "99", "100",
                volume="10", change="5", snapshot_id=f"old-2-{venue}",
            ),
            make_ticker(
                venue, "VOL", "99", "100",
                volume="3000000", change="50", snapshot_id=f"vol-{venue}",
            ),
            make_ticker(
                venue,
                "EDGE",
                "99" if venue == "cheap" else "103",
                "100" if venue == "cheap" else "104",
                volume="3000000",
                change="1",
                snapshot_id=f"edge-{venue}",
            ),
        )

    service = ArbitragePaperService(
        (
            SequencedAutoAdapter("cheap", (first("cheap"), second("cheap"))),
            SequencedAutoAdapter("rich", (first("rich"), second("rich"))),
        ),
        clock_ms=lambda: NOW_MS,
    )
    settings = ScanSettings(
        symbol="AUTO",
        max_symbols=3,
        max_active_symbols=2,
        activation_observations=1,
        auto_execute=True,
        min_net_edge_bps="5",
    )

    positioned = await service.scan(settings)
    assert positioned["active_symbols"] == ["OLDUSDT"]

    result = await service.scan(settings)

    assert [row["symbol"] for row in result["universe"]] == [
        "VOLUSDT",
        "EDGEUSDT",
    ]
    assert result["active_symbols"] == ["EDGEUSDT", "OLDUSDT"]
    assert result["metrics"]["trade_count"] == 1
    assert result["journal"][0]["symbol"] == "EDGEUSDT"


@pytest.mark.asyncio
async def test_auto_exposes_near_miss_and_keeps_last_profitable_signal() -> None:
    clock = [NOW_MS]

    def rows(venue: str) -> tuple[tuple[MarketTicker, ...], ...]:
        profitable = (
            make_ticker(
                venue,
                "TRACE",
                "99" if venue == "cheap" else "103",
                "100" if venue == "cheap" else "104",
                volume="2000000",
                change="9",
                snapshot_id=f"profitable-{venue}",
            ),
        )
        flat = (
            make_ticker(
                venue,
                "TRACE",
                "99",
                "100",
                volume="2000000",
                change="9",
                snapshot_id=f"flat-{venue}",
                timestamp_ms=NOW_MS + 2_000,
            ),
        )
        return profitable, flat

    service = ArbitragePaperService(
        (
            SequencedAutoAdapter("cheap", rows("cheap")),
            SequencedAutoAdapter("rich", rows("rich")),
        ),
        clock_ms=lambda: clock[0],
    )
    settings = ScanSettings(symbol="AUTO", min_net_edge_bps="5")

    signal = await service.scan(settings)
    assert signal["best_opportunity"]["symbol"] == "TRACEUSDT"
    assert signal["last_profitable_signal"]["observed_at_ms"] == NOW_MS

    clock[0] += 2_000
    missed = await service.scan(settings)

    assert missed["best_opportunity"] is None
    assert missed["best_near_miss"]["symbol"] == "TRACEUSDT"
    assert "non_positive_gross" in missed["best_near_miss"]["reasons"]
    assert missed["last_profitable_signal"]["symbol"] == "TRACEUSDT"
    assert missed["last_profitable_signal"]["observed_at_ms"] == NOW_MS
    assert missed["diagnostics"]["funnel"]["routes"] == 2
    assert missed["diagnostics"]["funnel"]["net_positive"] == 0
    assert missed["diagnostics"]["funnel"]["qualifying"] == 0
    assert (
        missed["diagnostics"]["rejection_counts"]["non_positive_gross"]
        == 2
    )

    # If a strict route exists before inventory activation, diagnostics name
    # the missing PAPER inventory instead of claiming that no filter rejected it.
    fresh_service = ArbitragePaperService(
        (
            AutoAdapter("cheap", rows("cheap")[0]),
            AutoAdapter("rich", rows("rich")[0]),
        ),
        clock_ms=lambda: NOW_MS,
    )
    pending = await fresh_service.scan(settings)
    assert pending["diagnostics"]["rejection_counts"]["missing_inventory"] >= 1

    reset = await service.reset()
    assert reset["best_near_miss"] is None
    assert reset["last_profitable_signal"] is None
    assert reset["diagnostics"]["funnel"]["routes"] == 0


@pytest.mark.asyncio
async def test_auto_diagnostics_explain_activation_depth_blocker() -> None:
    service = ArbitragePaperService(
        (
            AutoAdapter(
                "cheap",
                (
                    make_ticker(
                        "cheap", "SHALLOW", "99", "100",
                        volume="2000000", change="9",
                        bid_size="0.30", ask_size="0.30",
                    ),
                ),
            ),
            AutoAdapter(
                "rich",
                (
                    make_ticker(
                        "rich", "SHALLOW", "103", "104",
                        volume="2000000", change="8",
                        bid_size="0.30", ask_size="0.30",
                    ),
                ),
            ),
        ),
        clock_ms=lambda: NOW_MS,
    )

    result = await service.scan(
        ScanSettings(
            symbol="AUTO",
            notional="25",
            allocation_per_symbol_venue_usdt="50",
            bbo_depth_multiplier="2",
            activation_observations=1,
            max_active_symbols=1,
            min_net_edge_bps="5",
            auto_execute=True,
        )
    )

    assert result["best_opportunity"]["symbol"] == "SHALLOWUSDT"
    assert result["active_symbols"] == []
    assert result["candidate_evidence"] == []
    assert result["diagnostics"]["funnel"]["activation_depth_qualified"] == 0
    assert (
        result["diagnostics"]["rejection_counts"][
            "insufficient_activation_depth"
        ]
        == 1
    )


@pytest.mark.asyncio
async def test_auto_diagnostics_require_inventory_on_the_sell_venue() -> None:
    def deep(venue: str, bid: str, ask: str, snapshot: str) -> MarketTicker:
        return make_ticker(
            venue,
            "ROUTE",
            bid,
            ask,
            volume="2000000",
            change="9",
            snapshot_id=snapshot,
            bid_size="100",
            ask_size="100",
        )

    service = ArbitragePaperService(
        (
            SequencedAutoAdapter(
                "alpha",
                ((deep("alpha", "99", "100", "a1"),),
                 (deep("alpha", "99", "100", "a2"),)),
            ),
            SequencedAutoAdapter(
                "beta",
                ((deep("beta", "99", "100", "b1"),),
                 (deep("beta", "99", "100", "b2"),)),
            ),
            SequencedAutoAdapter(
                "gamma",
                ((make_ticker(
                    "gamma", "ROUTE", "99", "100",
                    volume="2000000", change="9", snapshot_id="g1",
                    bid_size="0.01", ask_size="0.01",
                ),),
                 (deep("gamma", "110", "111", "g2"),)),
            ),
        ),
        clock_ms=lambda: NOW_MS,
    )
    settings = ScanSettings(
        symbol="AUTO",
        activation_observations=1,
        max_active_symbols=1,
        min_net_edge_bps="5",
        auto_execute=True,
    )

    positioned = await service.scan(settings)
    assert positioned["active_symbols"] == ["ROUTEUSDT"]
    assert "ROUTE" not in positioned["balances"]["gamma"]

    result = await service.scan(settings)
    assert result["best_opportunity"]["sell_venue"] == "gamma"
    assert result["metrics"]["trade_count"] == 0
    assert result["diagnostics"]["funnel"]["qualifying"] == 2
    assert result["diagnostics"]["funnel"]["inventory_ready"] == 0
    assert result["diagnostics"]["rejection_counts"]["missing_inventory"] == 2
    assert "balance_corridor" not in result["diagnostics"]["rejection_counts"]


@pytest.mark.asyncio
async def test_auto_uses_configured_24h_volume_floor() -> None:
    rows = {
        venue: (
            make_ticker(
                venue,
                "MIDVOL",
                "99",
                "100",
                volume="750000",
                change="9",
                snapshot_id=f"mid-{venue}",
            ),
        )
        for venue in ("alpha", "beta")
    }

    default_service = ArbitragePaperService(
        (AutoAdapter("alpha", rows["alpha"]), AutoAdapter("beta", rows["beta"])),
        clock_ms=lambda: NOW_MS,
    )
    excluded = await default_service.scan(ScanSettings(symbol="AUTO"))
    assert excluded["universe"] == []

    custom_service = ArbitragePaperService(
        (AutoAdapter("alpha", rows["alpha"]), AutoAdapter("beta", rows["beta"])),
        clock_ms=lambda: NOW_MS,
    )
    included = await custom_service.scan(
        ScanSettings(
            symbol="AUTO",
            min_24h_volume_usdt="500000",
            activation_observations=1,
            auto_execute=True,
            max_active_symbols=1,
        )
    )
    assert [item["symbol"] for item in included["universe"]] == ["MIDVOLUSDT"]
    assert included["active_symbols"] == ["MIDVOLUSDT"]


@pytest.mark.asyncio
async def test_auto_uses_custom_activation_trade_and_allocation_settings() -> None:
    def rows(venue: str) -> tuple[tuple[MarketTicker, ...], ...]:
        return tuple(
            (
                make_ticker(
                    venue,
                    "FAST",
                    "99" if venue == "cheap" else "103",
                    "100" if venue == "cheap" else "104",
                    volume="5000000",
                    change="9",
                    snapshot_id=f"custom-{venue}-{index}",
                ),
            )
            for index in range(3)
        )

    service = ArbitragePaperService(
        (
            SequencedAutoAdapter("cheap", rows("cheap")),
            SequencedAutoAdapter("rich", rows("rich")),
        ),
        clock_ms=lambda: NOW_MS,
    )
    settings = ScanSettings(
        symbol="AUTO",
        notional="30",
        min_net_edge_bps="1",
        auto_execute=True,
        activation_observations=3,
        evidence_window_minutes=7,
        max_active_symbols=1,
        allocation_per_symbol_venue_usdt="60",
    )

    for expected in (1, 2):
        result = await service.scan(settings)
        assert result["candidate_evidence"][0]["qualifying_observations"] == expected
        assert result["active_inventory"] == []

    activated = await service.scan(settings)

    assert activated["metrics"]["trade_count"] == 1
    assert D(activated["journal"][0]["notional_usdt"]) <= D("30")
    inventory = activated["active_inventory"][0]
    assert inventory["evidence_observations"] == 3
    assert inventory["target_per_venue_usdt"] == "60"
    assert D(inventory["total_quote_spent_usdt"]) == D("120")
    assert activated["candidate_evidence"][0]["required_observations"] == 3
    assert activated["candidate_evidence"][0]["window_ms"] == 7 * 60 * 1000
    policy = activated["market_data_policy"]
    assert policy["auto_max_active_symbols"] == 1
    assert policy["auto_allocation_per_symbol_venue_usdt"] == "60"
    assert policy["auto_max_trade_usdt"] == "30"
    assert policy["auto_activation_min_bbo_notional_usdt"] == "60"
    assert policy["auto_base_target_per_venue_usdt"] == "60"
    assert policy["auto_usdt_reserve_target_per_venue"] == "440"
    assert policy["auto_execution_base_cap_per_venue_usdt"] == "90"
    assert policy["auto_execution_usdt_floor_per_venue"] == "410"

    # A later allocation setting applies only to new activations.  The active
    # position retains the target with which it was actually funded.
    resized = await service.scan(
        ScanSettings(
            symbol="AUTO",
            notional="30",
            min_net_edge_bps="1",
            auto_execute=True,
            activation_observations=3,
            evidence_window_minutes=7,
            max_active_symbols=1,
            allocation_per_symbol_venue_usdt="70",
        )
    )
    assert resized["active_inventory"][0]["target_per_venue_usdt"] == "60"
    assert (
        resized["market_data_policy"]["auto_allocation_per_symbol_venue_usdt"]
        == "70"
    )


@pytest.mark.asyncio
async def test_auto_repeated_same_snapshot_does_not_satisfy_activation_gate() -> None:
    service = ArbitragePaperService(
        (
            AutoAdapter(
                "bybit",
                (make_ticker("bybit", "FAST", "99", "100", volume="5000000", change="9"),),
            ),
            AutoAdapter(
                "binance",
                (make_ticker("binance", "FAST", "103", "104", volume="5000000", change="8"),),
            ),
        ),
        clock_ms=lambda: NOW_MS,
    )
    settings = ScanSettings(
        symbol="AUTO", auto_execute=True, min_net_edge_bps="1"
    )

    for _ in range(6):
        result = await service.scan(settings)

    assert result["candidate_evidence"][0]["qualifying_observations"] == 1
    assert result["active_inventory"] == []
    assert result["metrics"]["trade_count"] == 0
    assert result["balances"]["bybit"] == {"USDT": "500"}
    assert result["balances"]["binance"] == {"USDT": "500"}


@pytest.mark.asyncio
async def test_auto_activates_at_most_two_symbols() -> None:
    def rows(venue: str, index: int) -> tuple[MarketTicker, ...]:
        return tuple(
            make_ticker(
                venue,
                base,
                "99" if venue == "cheap" else "103",
                "100" if venue == "cheap" else "104",
                volume="5000000",
                change=change,
                snapshot_id=f"{base}-{venue}-{index}",
            )
            for base, change in (("AAA", "9"), ("BBB", "8"), ("CCC", "7"))
        )

    service = ArbitragePaperService(
        (
            SequencedAutoAdapter(
                "cheap", tuple(rows("cheap", index) for index in range(5))
            ),
            SequencedAutoAdapter(
                "rich", tuple(rows("rich", index) for index in range(5))
            ),
        ),
        clock_ms=lambda: NOW_MS,
    )
    settings = ScanSettings(
        symbol="AUTO", auto_execute=True, min_net_edge_bps="1"
    )

    for _ in range(5):
        result = await service.scan(settings)

    assert result["metrics"]["active_inventory_count"] == 2
    assert [row["symbol"] for row in result["active_inventory"]] == [
        "AAAUSDT",
        "BBBUSDT",
    ]
    assert {row["symbol"] for row in result["candidate_evidence"]} == {
        "AAAUSDT",
        "BBBUSDT",
    }
    assert result["metrics"]["trade_count"] == 1
    assert D(result["journal"][0]["notional_usdt"]) <= D("25")
    for venue in ("cheap", "rich"):
        assert D(result["balances"][venue]["USDT"]) >= D("375")
        assert "AAA" in result["balances"][venue]
        assert "BBB" in result["balances"][venue]
        assert "CCC" not in result["balances"][venue]
    policy = result["market_data_policy"]
    assert policy["auto_base_target_per_venue_usdt"] == "100"
    assert policy["auto_usdt_reserve_target_per_venue"] == "400"
    assert policy["auto_execution_base_cap_per_venue_usdt"] == "125"
    assert policy["auto_execution_usdt_floor_per_venue"] == "375"


@pytest.mark.asyncio
async def test_auto_liquidates_deterministic_excess_after_active_limit_reduction(
) -> None:
    def rows(venue: str, snapshot: int) -> tuple[MarketTicker, ...]:
        return tuple(
            make_ticker(
                venue,
                base,
                "99" if venue == "cheap" else "103",
                "100" if venue == "cheap" else "104",
                volume="5000000",
                change=change,
                snapshot_id=f"resize-{venue}-{base}-{snapshot}",
            )
            for base, change in (("AAA", "9"), ("BBB", "8"), ("CCC", "7"))
        )

    service = ArbitragePaperService(
        (
            SequencedAutoAdapter("cheap", (rows("cheap", 1), rows("cheap", 2))),
            SequencedAutoAdapter("rich", (rows("rich", 1), rows("rich", 2))),
        ),
        clock_ms=lambda: NOW_MS,
    )
    initial = ScanSettings(
        symbol="AUTO",
        min_net_edge_bps="1",
        auto_execute=True,
        activation_observations=1,
        max_active_symbols=3,
        allocation_per_symbol_venue_usdt="50",
    )
    activated = await service.scan(initial)
    assert activated["active_symbols"] == ["AAAUSDT", "BBBUSDT", "CCCUSDT"]

    reduced = await service.scan(
        ScanSettings(
            symbol="AUTO",
            min_net_edge_bps="1",
            auto_execute=True,
            activation_observations=1,
            max_active_symbols=1,
            allocation_per_symbol_venue_usdt="50",
        )
    )

    assert reduced["active_symbols"] == ["AAAUSDT"]
    liquidation_rows = [
        row
        for row in reduced["inventory_journal"]
        if row["event"] == "inventory_liquidation"
    ]
    assert {row["symbol"] for row in liquidation_rows} == {
        "BBBUSDT",
        "CCCUSDT",
    }
    assert len(liquidation_rows) == 4


@pytest.mark.asyncio
async def test_pending_excess_inventory_cannot_be_retraded_after_partial_exit(
) -> None:
    def ticker(
        venue: str,
        base: str,
        bid: str,
        ask: str,
        snapshot: int,
        *,
        bid_size: str = "100000",
    ) -> MarketTicker:
        original = make_ticker(
            venue,
            base,
            bid,
            ask,
            volume="5000000",
            change="9",
            snapshot_id=f"pending-{venue}-{base}-{snapshot}",
        )
        return MarketTicker(
            venue=original.venue,
            symbol=original.symbol,
            base_asset=original.base_asset,
            quote_asset=original.quote_asset,
            timestamp_ms=original.timestamp_ms,
            bid=original.bid,
            ask=original.ask,
            bid_size=bid_size,
            ask_size=original.ask_size,
            quote_volume=original.quote_volume,
            volume_usdt=original.volume_usdt,
            snapshot_id=original.snapshot_id,
            change_24h_pct=original.change_24h_pct,
        )

    initial_cheap = (
        ticker("cheap", "AAA", "99", "100", 1),
        ticker("cheap", "BBB", "99", "100", 1),
    )
    initial_rich = (
        ticker("rich", "AAA", "102", "103", 1),
        ticker("rich", "BBB", "105", "106", 1),
    )
    resized_cheap = (
        ticker("cheap", "AAA", "99", "100", 2),
        ticker("cheap", "BBB", "99", "100", 2),
    )
    resized_rich = (
        ticker("rich", "AAA", "102", "103", 2),
        # Only a partial forced exit is possible on this venue, leaving BBB
        # inventory that would otherwise be tempting to trade again.
        ticker("rich", "BBB", "105", "106", 2, bid_size="0.1"),
    )
    service = ArbitragePaperService(
        (
            SequencedAutoAdapter("cheap", (initial_cheap, resized_cheap)),
            SequencedAutoAdapter("rich", (initial_rich, resized_rich)),
        ),
        clock_ms=lambda: NOW_MS,
    )
    activated = await service.scan(
        ScanSettings(
            symbol="AUTO",
            min_net_edge_bps="1",
            auto_execute=True,
            activation_observations=1,
            max_active_symbols=2,
            allocation_per_symbol_venue_usdt="50",
        )
    )

    resized = await service.scan(
        ScanSettings(
            symbol="AUTO",
            min_net_edge_bps="1",
            auto_execute=True,
            activation_observations=1,
            max_active_symbols=1,
            allocation_per_symbol_venue_usdt="50",
        )
    )

    pending = next(
        row
        for row in resized["active_inventory"]
        if row["symbol"] == "BBBUSDT"
    )
    assert pending["state"] == "pending_liquidation"
    assert D(resized["balances"]["rich"]["BBB"]) > 0
    # BBB has the better edge, so this specifically proves the pending-state
    # filter; any later execution may use retained AAA but never pending BBB.
    later_rows = resized["journal"][len(activated["journal"]) :]
    assert later_rows
    assert {row["symbol"] for row in later_rows} == {"AAAUSDT"}


@pytest.mark.asyncio
async def test_auto_skips_allocation_without_full_bbo_capacity() -> None:
    def thin(venue: str, bid: str, ask: str, index: int) -> MarketTicker:
        ticker = make_ticker(
            venue,
            "THIN",
            bid,
            ask,
            volume="5000000",
            change="9",
            snapshot_id=f"thin-{venue}-{index}",
        )
        return MarketTicker(
            venue=ticker.venue,
            symbol=ticker.symbol,
            base_asset=ticker.base_asset,
            quote_asset=ticker.quote_asset,
            timestamp_ms=ticker.timestamp_ms,
            bid=ticker.bid,
            ask=ticker.ask,
            bid_size="0.2",
            ask_size="0.2",
            quote_volume=ticker.quote_volume,
            volume_usdt=ticker.volume_usdt,
            snapshot_id=ticker.snapshot_id,
            change_24h_pct=ticker.change_24h_pct,
        )

    service = ArbitragePaperService(
        (
            SequencedAutoAdapter(
                "cheap",
                tuple((thin("cheap", "99", "100", index),) for index in range(5)),
            ),
            SequencedAutoAdapter(
                "rich",
                tuple((thin("rich", "103", "104", index),) for index in range(5)),
            ),
        ),
        clock_ms=lambda: NOW_MS,
    )
    settings = ScanSettings(
        symbol="AUTO", auto_execute=True, min_net_edge_bps="1"
    )

    for _ in range(5):
        result = await service.scan(settings)

    assert result["candidate_evidence"] == []
    assert result["active_inventory"] == []
    assert result["metrics"]["trade_count"] == 0
    assert result["balances"]["cheap"] == {"USDT": "500"}
    assert result["balances"]["rich"] == {"USDT": "500"}


@pytest.mark.asyncio
async def test_auto_liquidity_gate_scales_with_configured_trade_notional() -> None:
    def medium_depth(venue: str, bid: str, ask: str) -> MarketTicker:
        ticker = make_ticker(
            venue,
            "MEDIUM",
            bid,
            ask,
            volume="5000000",
            change="9",
            snapshot_id=f"medium-{venue}",
        )
        return MarketTicker(
            venue=ticker.venue,
            symbol=ticker.symbol,
            base_asset=ticker.base_asset,
            quote_asset=ticker.quote_asset,
            timestamp_ms=ticker.timestamp_ms,
            bid=ticker.bid,
            ask=ticker.ask,
            # About 550 USDT BBO capacity: enough for the old 25 * 20 gate,
            # but not for the configured 30 * 20 requirement.
            bid_size="5.5",
            ask_size="5.5",
            quote_volume=ticker.quote_volume,
            volume_usdt=ticker.volume_usdt,
            snapshot_id=ticker.snapshot_id,
            change_24h_pct=ticker.change_24h_pct,
        )

    service = ArbitragePaperService(
        (
            AutoAdapter("cheap", (medium_depth("cheap", "99", "100"),)),
            AutoAdapter("rich", (medium_depth("rich", "103", "104"),)),
        ),
        clock_ms=lambda: NOW_MS,
    )

    result = await service.scan(
        ScanSettings(
            symbol="AUTO",
            notional="30",
            min_net_edge_bps="1",
            auto_execute=True,
            activation_observations=1,
            max_active_symbols=1,
            allocation_per_symbol_venue_usdt="60",
            bbo_depth_multiplier="20",
        )
    )

    assert result["candidate_evidence"] == []
    assert result["active_inventory"] == []
    assert (
        result["market_data_policy"]["auto_activation_min_bbo_notional_usdt"]
        == "600"
    )


@pytest.mark.asyncio
async def test_auto_skips_allocation_when_exit_bid_is_thin() -> None:
    def thin_bid(venue: str, bid: str, ask: str, index: int) -> MarketTicker:
        ticker = make_ticker(
            venue,
            "THIN",
            bid,
            ask,
            volume="5000000",
            change="9",
            snapshot_id=f"thin-bid-{venue}-{index}",
        )
        return MarketTicker(
            venue=ticker.venue,
            symbol=ticker.symbol,
            base_asset=ticker.base_asset,
            quote_asset=ticker.quote_asset,
            timestamp_ms=ticker.timestamp_ms,
            bid=ticker.bid,
            ask=ticker.ask,
            bid_size="0.1",
            ask_size="100",
            quote_volume=ticker.quote_volume,
            volume_usdt=ticker.volume_usdt,
            snapshot_id=ticker.snapshot_id,
            change_24h_pct=ticker.change_24h_pct,
        )

    service = ArbitragePaperService(
        (
            SequencedAutoAdapter(
                "cheap",
                tuple((thin_bid("cheap", "99", "100", index),) for index in range(5)),
            ),
            SequencedAutoAdapter(
                "rich",
                tuple((thin_bid("rich", "103", "104", index),) for index in range(5)),
            ),
        ),
        clock_ms=lambda: NOW_MS,
    )
    settings = ScanSettings(
        symbol="AUTO", auto_execute=True, min_net_edge_bps="1"
    )

    for _ in range(5):
        result = await service.scan(settings)

    assert result["candidate_evidence"] == []
    assert result["active_inventory"] == []
    assert result["metrics"]["trade_count"] == 0


@pytest.mark.asyncio
async def test_auto_liquidates_inventory_after_hour_without_signal() -> None:
    current_ms = [NOW_MS]
    expired_ms = NOW_MS + 60 * 60 * 1000 + 1

    def signal(venue: str, index: int) -> tuple[MarketTicker, ...]:
        return (
            make_ticker(
                venue,
                "FAST",
                "99" if venue == "cheap" else "103",
                "100" if venue == "cheap" else "104",
                volume="5000000",
                change="9",
                snapshot_id=f"fast-{venue}-{index}",
            ),
        )

    def no_signal(venue: str) -> tuple[MarketTicker, ...]:
        return (
            make_ticker(
                venue,
                "FAST",
                "99",
                "100",
                # Falling below the configured universe floor stops renewing
                # the active symbol's bounded-rank last_seen timestamp.
                volume="500000",
                change="9",
                snapshot_id=f"calm-{venue}",
                timestamp_ms=expired_ms,
            ),
        )

    cheap_rows = tuple(signal("cheap", index) for index in range(5)) + (
        no_signal("cheap"),
    )
    rich_rows = tuple(signal("rich", index) for index in range(5)) + (
        no_signal("rich"),
    )
    service = ArbitragePaperService(
        (
            SequencedAutoAdapter("cheap", cheap_rows),
            SequencedAutoAdapter("rich", rich_rows),
        ),
        clock_ms=lambda: current_ms[0],
    )
    settings = ScanSettings(
        symbol="AUTO",
        auto_execute=True,
        min_net_edge_bps="1",
        max_symbols=2,
        max_active_symbols=2,
    )

    for _ in range(5):
        activated = await service.scan(settings)
    assert activated["active_symbols"] == ["FASTUSDT"]

    current_ms[0] = expired_ms
    expired = await service.scan(settings)

    assert expired["active_symbols"] == []
    assert expired["metrics"]["active_inventory_count"] == 0
    assert expired["candidate_evidence"][0]["qualifying_observations"] == 0
    assert D(expired["balances"]["cheap"]["FAST"]) == 0
    assert D(expired["balances"]["rich"]["FAST"]) == 0
    assert D(expired["balances"]["cheap"]["USDT"]) < D("500")
    assert D(expired["balances"]["rich"]["USDT"]) < D("500")
    assert len(expired["inventory_journal"]) == 4
    assert {row["event"] for row in expired["inventory_journal"]} == {
        "inventory_activation",
        "inventory_liquidation",
    }
    assert D(expired["metrics"]["strategy_equity_usdt"]) == (
        D(expired["balances"]["cheap"]["USDT"])
        + D(expired["balances"]["rich"]["USDT"])
    )
    assert D(expired["metrics"]["strategy_pnl_usdt"]) < 0


@pytest.mark.asyncio
async def test_auto_uses_separate_inventory_idle_timeout_for_expiry() -> None:
    current_ms = [NOW_MS]
    expired_ms = NOW_MS + 60 * 1000 + 1

    def signal(venue: str) -> MarketTicker:
        return make_ticker(
            venue,
            "FAST",
            "99" if venue == "cheap" else "103",
            "100" if venue == "cheap" else "104",
            volume="5000000",
            change="9",
            snapshot_id=f"short-signal-{venue}",
        )

    def calm(venue: str) -> MarketTicker:
        return make_ticker(
            venue,
            "FAST",
            "99",
            "100",
            volume="500000",
            change="0",
            snapshot_id=f"short-calm-{venue}",
            timestamp_ms=expired_ms,
        )

    def expired_calm(venue: str) -> MarketTicker:
        original = calm(venue)
        return MarketTicker(
            venue=original.venue,
            symbol=original.symbol,
            base_asset=original.base_asset,
            quote_asset=original.quote_asset,
            timestamp_ms=NOW_MS + 2 * 60 * 1000 + 1,
            bid=original.bid,
            ask=original.ask,
            bid_size=original.bid_size,
            ask_size=original.ask_size,
            quote_volume=original.quote_volume,
            volume_usdt=original.volume_usdt,
            snapshot_id=f"expired-{venue}",
            change_24h_pct=original.change_24h_pct,
        )

    service = ArbitragePaperService(
        (
            SequencedAutoAdapter(
                "cheap",
                ((signal("cheap"),), (calm("cheap"),), (expired_calm("cheap"),)),
            ),
            SequencedAutoAdapter(
                "rich",
                ((signal("rich"),), (calm("rich"),), (expired_calm("rich"),)),
            ),
        ),
        clock_ms=lambda: current_ms[0],
    )
    settings = ScanSettings(
        symbol="AUTO",
        min_net_edge_bps="1",
        auto_execute=True,
        activation_observations=1,
        evidence_window_minutes=1,
        inventory_idle_timeout_minutes=2,
        max_symbols=2,
        max_active_symbols=1,
        allocation_per_symbol_venue_usdt="50",
    )

    activated = await service.scan(settings)
    assert activated["active_symbols"] == ["FASTUSDT"]

    current_ms[0] = expired_ms
    retained = await service.scan(settings)
    assert retained["active_symbols"] == ["FASTUSDT"]

    current_ms[0] = NOW_MS + 2 * 60 * 1000 + 1
    expired = await service.scan(settings)
    assert expired["active_symbols"] == []
    assert expired["candidate_evidence"][0]["qualifying_observations"] == 0


@pytest.mark.asyncio
async def test_auto_liquidation_does_not_reuse_the_same_bbo_snapshot() -> None:
    current_ms = [NOW_MS]
    expired_ms = NOW_MS + 60 * 60 * 1000 + 1

    def ticker(
        venue: str,
        index: int,
        *,
        expired: bool = False,
    ) -> MarketTicker:
        original = make_ticker(
            venue,
            "FAST",
            (
                "99"
                if expired
                else ("99" if venue == "cheap" else "103")
            ),
            (
                "100"
                if expired
                else ("100" if venue == "cheap" else "104")
            ),
            volume="5000000",
            change="9" if not expired else "0",
            snapshot_id=(
                f"signal-{venue}-{index}" if not expired else f"exit-{venue}"
            ),
            timestamp_ms=expired_ms if expired else NOW_MS,
        )
        if not expired:
            return original
        return MarketTicker(
            venue=original.venue,
            symbol=original.symbol,
            base_asset=original.base_asset,
            quote_asset=original.quote_asset,
            timestamp_ms=original.timestamp_ms,
            bid=original.bid,
            ask=original.ask,
            bid_size="0.1",
            ask_size=original.ask_size,
            quote_volume=original.quote_volume,
            volume_usdt=original.volume_usdt,
            snapshot_id=original.snapshot_id,
            change_24h_pct=original.change_24h_pct,
        )

    service = ArbitragePaperService(
        (
            SequencedAutoAdapter(
                "cheap",
                tuple((ticker("cheap", index),) for index in range(5))
                + tuple((ticker("cheap", 0, expired=True),) for _ in range(2)),
            ),
            SequencedAutoAdapter(
                "rich",
                tuple((ticker("rich", index),) for index in range(5))
                + tuple((ticker("rich", 0, expired=True),) for _ in range(2)),
            ),
        ),
        clock_ms=lambda: current_ms[0],
    )
    settings = ScanSettings(
        symbol="AUTO", auto_execute=True, min_net_edge_bps="1"
    )
    for _ in range(5):
        await service.scan(settings)

    current_ms[0] = expired_ms
    first_exit = await service.scan(settings)
    cheap_after_first = D(first_exit["balances"]["cheap"]["FAST"])
    rich_after_first = D(first_exit["balances"]["rich"]["FAST"])
    second_exit = await service.scan(settings)

    assert D(second_exit["balances"]["cheap"]["FAST"]) == cheap_after_first
    assert D(second_exit["balances"]["rich"]["FAST"]) == rich_after_first
    assert second_exit["active_inventory"][0]["state"] == "pending_liquidation"
    liquidation_rows = [
        row
        for row in second_exit["inventory_journal"]
        if row["event"] == "inventory_liquidation"
    ]
    assert len(liquidation_rows) == 2


@pytest.mark.asyncio
async def test_auto_rejects_future_ticker_timestamps() -> None:
    future_ms = NOW_MS + 60_000
    service = ArbitragePaperService(
        (
            AutoAdapter(
                "cheap",
                (
                    make_ticker(
                        "cheap", "FAST", "99", "100",
                        volume="5000000", change="9", timestamp_ms=future_ms,
                    ),
                ),
            ),
            AutoAdapter(
                "rich",
                (
                    make_ticker(
                        "rich", "FAST", "103", "104",
                        volume="5000000", change="8", timestamp_ms=future_ms,
                    ),
                ),
            ),
        ),
        clock_ms=lambda: NOW_MS,
    )

    result = await service.scan(
        ScanSettings(symbol="AUTO", min_net_edge_bps="1")
    )

    assert result["metrics"]["book_count"] == 0
    assert result["best_opportunity"] is None
    assert result["candidate_evidence"] == []


@pytest.mark.asyncio
async def test_auto_accepts_receipt_timestamp_after_scan_started() -> None:
    clock_values = iter((NOW_MS + 100, NOW_MS + 100))
    receipt_ms = NOW_MS + 50
    service = ArbitragePaperService(
        (
            AutoAdapter(
                "cheap",
                (
                    make_ticker(
                        "cheap", "FAST", "99", "100",
                        volume="5000000", change="9", timestamp_ms=receipt_ms,
                    ),
                ),
            ),
            AutoAdapter(
                "rich",
                (
                    make_ticker(
                        "rich", "FAST", "103", "104",
                        volume="5000000", change="8", timestamp_ms=receipt_ms,
                    ),
                ),
            ),
        ),
        clock_ms=lambda: next(clock_values),
    )

    result = await service.scan(
        ScanSettings(symbol="AUTO", min_net_edge_bps="1")
    )

    assert result["metrics"]["book_count"] == 2
    assert result["best_opportunity"]["symbol"] == "FASTUSDT"
    assert result["last_scan_ms"] == NOW_MS + 100
