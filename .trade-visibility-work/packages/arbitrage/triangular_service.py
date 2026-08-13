"""Orchestration for public-data, same-venue triangular PAPER arbitrage."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
import time
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from packages.arbitrage.adapters import (
    BinancePublicAdapter,
    BitgetPublicAdapter,
    BybitPublicAdapter,
    OkxPublicAdapter,
)
from packages.arbitrage.models import decimal_string, decimal_value
from packages.arbitrage.triangular import (
    MarketTicker,
    TriangularConfig,
    TriangularEngine,
    TriangularOpportunity,
    TriangularPaperExecutor,
    TriangularPaperPortfolio,
    select_liquid_tickers,
)


BPS = Decimal("10000")
SUPPORTED_VENUES = ("bybit", "binance", "okx", "bitget")
SUPPORTED_START_ASSETS = frozenset({"USDT", "BTC", "ETH", "BNB", "BRL"})

# Conservative placeholders for theory testing. They are deliberately not
# presented as actual account fee tiers.
DEFAULT_TRIANGULAR_TAKER_FEES: dict[str, Decimal] = {
    venue: Decimal("0.001") for venue in SUPPORTED_VENUES
}
DEFAULT_TRIANGULAR_BALANCES: dict[str, dict[str, Decimal]] = {
    venue: {
        "USDT": Decimal("10000"),
        "USDC": Decimal("10000"),
        "BTC": Decimal("0.5"),
        "ETH": Decimal("10"),
        "BNB": Decimal("20"),
        "SOL": Decimal("100"),
        "BRL": Decimal("50000"),
    }
    for venue in SUPPORTED_VENUES
}


def _clock_ms() -> int:
    return time.time_ns() // 1_000_000


class PublicTickerAdapter(Protocol):
    venue: str

    async def fetch_tickers(self) -> Sequence[MarketTicker]: ...

    async def aclose(self) -> None: ...


def _asset(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("start_asset must be a string")
    result = value.strip().upper()
    if not result or not result.isascii() or not result.isalnum():
        raise ValueError("start_asset must contain only ASCII letters and digits")
    return result


@dataclass(frozen=True, slots=True)
class TriangularScanSettings:
    """Validated settings for one triangular scan or recurring monitor."""

    venue: str = "all"
    start_asset: str = "USDT"
    start_amount: Decimal = Decimal("1000")
    min_net_edge_bps: Decimal = Decimal("5")
    risk_buffer_bps: Decimal = Decimal("2")
    auto_execute: bool = False
    interval_ms: int = 10_000
    max_tickers: int = 50

    def __post_init__(self) -> None:
        if not isinstance(self.venue, str):
            raise TypeError("venue must be a string")
        venue = self.venue.strip().lower()
        if not venue:
            raise ValueError("venue must not be empty")
        asset = _asset(self.start_asset)
        amount = decimal_value(self.start_amount, name="start_amount")
        min_edge = decimal_value(self.min_net_edge_bps, name="min_net_edge_bps")
        risk = decimal_value(self.risk_buffer_bps, name="risk_buffer_bps")
        if amount <= 0:
            raise ValueError("start_amount must be greater than zero")
        if min_edge < 0 or min_edge >= BPS:
            raise ValueError("min_net_edge_bps must be in [0, 10000)")
        if risk < 0 or risk >= BPS:
            raise ValueError("risk_buffer_bps must be in [0, 10000)")
        if isinstance(self.interval_ms, bool):
            raise TypeError("interval_ms must be an integer")
        interval = int(self.interval_ms)
        if interval < 10_000:
            raise ValueError("interval_ms must be at least 10000")
        if isinstance(self.max_tickers, bool):
            raise TypeError("max_tickers must be an integer")
        limit = int(self.max_tickers)
        if not 3 <= limit <= 50:
            raise ValueError("max_tickers must be between 3 and 50")
        object.__setattr__(self, "venue", venue)
        object.__setattr__(self, "start_asset", asset)
        object.__setattr__(self, "start_amount", amount)
        object.__setattr__(self, "min_net_edge_bps", min_edge)
        object.__setattr__(self, "risk_buffer_bps", risk)
        object.__setattr__(self, "interval_ms", interval)
        object.__setattr__(self, "max_tickers", limit)

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "start_asset": self.start_asset,
            "start_amount": decimal_string(self.start_amount),
            "min_net_edge_bps": decimal_string(self.min_net_edge_bps),
            "risk_buffer_bps": decimal_string(self.risk_buffer_bps),
            "auto_execute": self.auto_execute,
            "interval_ms": self.interval_ms,
            "max_tickers": self.max_tickers,
        }


class TriangularPaperService:
    """Fetch one ticker universe per venue and simulate complete 3-leg cycles."""

    def __init__(
        self,
        adapters: Iterable[PublicTickerAdapter] | None = None,
        *,
        initial_balances: Mapping[
            str, Mapping[str, Decimal | str | int | float]
        ]
        | None = None,
        taker_fees: Mapping[str, Decimal | str | int | float] | None = None,
        max_staleness_ms: int = 10_000,
        max_leg_skew_ms: int = 2_000,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.adapters = tuple(
            adapters
            if adapters is not None
            else (
                BybitPublicAdapter(),
                BinancePublicAdapter(),
                OkxPublicAdapter(),
                BitgetPublicAdapter(),
            )
        )
        if not self.adapters:
            raise ValueError("at least one public venue adapter is required")
        venue_names = [adapter.venue.lower() for adapter in self.adapters]
        if len(set(venue_names)) != len(venue_names):
            raise ValueError("venue adapter names must be unique")
        if isinstance(max_staleness_ms, bool) or int(max_staleness_ms) < 0:
            raise ValueError("max_staleness_ms must not be negative")
        if isinstance(max_leg_skew_ms, bool) or int(max_leg_skew_ms) < 0:
            raise ValueError("max_leg_skew_ms must not be negative")

        self.clock_ms = clock_ms or _clock_ms
        self.max_staleness_ms = int(max_staleness_ms)
        self.max_leg_skew_ms = int(max_leg_skew_ms)
        raw_fees = DEFAULT_TRIANGULAR_TAKER_FEES if taker_fees is None else taker_fees
        self.taker_fees = {
            venue.lower(): decimal_value(fee, name=f"taker fee for {venue}")
            for venue, fee in raw_fees.items()
        }
        if initial_balances is None:
            self._initial_balances = {
                venue: dict(
                    DEFAULT_TRIANGULAR_BALANCES.get(
                        venue,
                        {
                            "USDT": Decimal("10000"),
                            "BTC": Decimal("0.5"),
                            "ETH": Decimal("10"),
                            "BNB": Decimal("20"),
                            "BRL": Decimal("50000"),
                        },
                    )
                )
                for venue in venue_names
            }
        else:
            self._initial_balances = initial_balances
        self._portfolio = TriangularPaperPortfolio(self._initial_balances)
        self._executor = TriangularPaperExecutor(self._portfolio)
        self._execution_opportunities: list[TriangularOpportunity] = []
        self._executed_snapshots: set[str] = set()

        self._scan_lock = asyncio.Lock()
        self._monitor_task: asyncio.Task[None] | None = None
        self._running = False
        self._run_generation = 0
        self._scanning = False
        self._settings = TriangularScanSettings()
        self._last_scan_ms: int | None = None
        self._scan_count = 0
        self._tickers: dict[str, tuple[MarketTicker, ...]] = {}
        self._opportunities: list[TriangularOpportunity] = []
        self._venue_state: dict[str, dict[str, Any]] = {
            venue: self._idle_venue_state(venue) for venue in venue_names
        }
        self._errors: dict[str, str] = {}

    @staticmethod
    def _idle_venue_state(venue: str) -> dict[str, Any]:
        return {
            "name": venue,
            "ok": False,
            "status": "idle",
            "latency_ms": None,
            "timestamp_ms": None,
            "ticker_age_ms": None,
            "ticker_count": 0,
            "selected_ticker_count": 0,
            "error": None,
        }

    @property
    def running(self) -> bool:
        return self._running

    async def _fetch_tickers(
        self, adapter: PublicTickerAdapter
    ) -> tuple[str, tuple[MarketTicker, ...] | None, int, Exception | None]:
        venue = adapter.venue.lower()
        started = time.perf_counter_ns()
        try:
            tickers = tuple(await adapter.fetch_tickers())
            if not tickers:
                raise ValueError("all-tickers response is empty")
            if any(ticker.venue.lower() != venue for ticker in tickers):
                raise ValueError(f"adapter {venue} returned a ticker for another venue")
            latency = (time.perf_counter_ns() - started) // 1_000_000
            return venue, tickers, latency, None
        except Exception as exc:  # one venue must not cancel the whole round
            latency = (time.perf_counter_ns() - started) // 1_000_000
            return venue, None, latency, exc

    def _config(self, settings: TriangularScanSettings) -> TriangularConfig:
        return TriangularConfig(
            taker_fees=self.taker_fees,
            min_net_edge=settings.min_net_edge_bps / BPS,
            risk_buffer=settings.risk_buffer_bps / BPS,
            max_start_amount=settings.start_amount,
            max_staleness_ms=self.max_staleness_ms,
            max_leg_skew_ms=self.max_leg_skew_ms,
            default_taker_fee=Decimal("0.001"),
        )

    async def scan(
        self,
        settings: TriangularScanSettings | None = None,
        *,
        run_generation: int | None = None,
    ) -> dict[str, Any]:
        selected = settings or self._settings
        if not isinstance(selected, TriangularScanSettings):
            raise TypeError("settings must be TriangularScanSettings")
        known_venues = {adapter.venue.lower() for adapter in self.adapters}
        if selected.venue != "all" and selected.venue not in known_venues:
            raise ValueError(f"venue {selected.venue!r} is not configured")

        async with self._scan_lock:
            self._settings = selected
            self._scanning = True
            self._errors = {}
            try:
                active_adapters = tuple(
                    adapter
                    for adapter in self.adapters
                    if selected.venue == "all"
                    or adapter.venue.lower() == selected.venue
                )
                for adapter in self.adapters:
                    venue = adapter.venue.lower()
                    if adapter not in active_adapters:
                        state = self._idle_venue_state(venue)
                        state["status"] = "not_selected"
                        self._venue_state[venue] = state

                results = await asyncio.gather(
                    *(self._fetch_tickers(adapter) for adapter in active_adapters)
                )
                if (
                    run_generation is not None
                    and run_generation != self._run_generation
                ):
                    return self.status()

                now_ms = self.clock_ms()
                selected_by_venue: dict[str, tuple[MarketTicker, ...]] = {}
                opportunities: list[TriangularOpportunity] = []
                engine = TriangularEngine(self._config(selected))

                for venue, tickers, latency_ms, error in results:
                    if error is not None:
                        message = f"{type(error).__name__}: {error}"
                        self._errors[venue] = message
                        state = self._idle_venue_state(venue)
                        state.update(
                            status="error",
                            latency_ms=latency_ms,
                            error=message,
                        )
                        self._venue_state[venue] = state
                        continue

                    assert tickers is not None
                    fresh = tuple(
                        ticker
                        for ticker in tickers
                        if max(0, now_ms - ticker.timestamp_ms)
                        <= self.max_staleness_ms
                    )
                    stale_count = len(tickers) - len(fresh)
                    if stale_count:
                        self._errors[f"{venue}_stale"] = (
                            f"excluded {stale_count} stale ticker(s) older than "
                            f"{self.max_staleness_ms} ms"
                        )
                    universe = tuple(
                        select_liquid_tickers(
                            fresh,
                            max_tickers=selected.max_tickers,
                            start_asset=selected.start_asset,
                        )
                    )
                    selected_by_venue[venue] = universe
                    newest_timestamp = max(
                        (ticker.timestamp_ms for ticker in fresh), default=None
                    )
                    age_ms = (
                        None
                        if newest_timestamp is None
                        else max(0, now_ms - newest_timestamp)
                    )
                    ok = bool(fresh)
                    state = self._idle_venue_state(venue)
                    state.update(
                        ok=ok,
                        status="online" if ok else "stale",
                        latency_ms=latency_ms,
                        timestamp_ms=newest_timestamp,
                        ticker_age_ms=age_ms,
                        ticker_count=len(fresh),
                        selected_ticker_count=len(universe),
                        error=None if ok else "no fresh valid tickers",
                    )
                    self._venue_state[venue] = state
                    if not universe:
                        continue
                    opportunities.extend(
                        engine.scan(
                            universe,
                            start_asset=selected.start_asset,
                            start_amount=selected.start_amount,
                            venue=venue,
                            now_ms=now_ms,
                        )
                    )

                self._tickers = selected_by_venue
                self._opportunities = sorted(
                    opportunities,
                    key=lambda item: (item.net_profit, item.net_edge),
                    reverse=True,
                )

                if selected.auto_execute and self._opportunities:
                    unexecuted = [
                        opportunity
                        for opportunity in self._opportunities
                        if opportunity.snapshot_key not in self._executed_snapshots
                    ]
                    if not unexecuted:
                        self._errors["duplicate_snapshot"] = (
                            "paper execution skipped: every profitable cycle "
                            "uses already executed ticker snapshots"
                        )
                    else:
                        best: TriangularOpportunity | None = None
                        for opportunity in unexecuted:
                            available = self._portfolio.balance(
                                opportunity.venue,
                                opportunity.start_asset,
                            )
                            if available <= 0:
                                continue
                            if available >= opportunity.start_amount:
                                best = opportunity
                                break
                            affordable = engine.scan(
                                selected_by_venue[opportunity.venue],
                                start_asset=selected.start_asset,
                                start_amount=available,
                                venue=opportunity.venue,
                                now_ms=now_ms,
                            )
                            best = next(
                                (
                                    candidate
                                    for candidate in affordable
                                    if candidate.route == opportunity.route
                                    and candidate.snapshot_key
                                    == opportunity.snapshot_key
                                ),
                                None,
                            )
                            if best is not None:
                                break
                        if best is None:
                            self._errors["paper_execution"] = (
                                "no profitable unexecuted cycle can be funded "
                                "by the virtual start-asset balances"
                            )
                            best = None
                        try:
                            if best is not None:
                                self._executor.execute(best, timestamp_ms=now_ms)
                                self._execution_opportunities.append(best)
                                self._executed_snapshots.add(best.snapshot_key)
                        except Exception as exc:
                            self._errors["paper_execution"] = (
                                f"{type(exc).__name__}: {exc}"
                            )

                self._scan_count += 1
                self._last_scan_ms = now_ms
            finally:
                self._scanning = False
        return self.status()

    async def start(self, settings: TriangularScanSettings) -> dict[str, Any]:
        if self._running:
            raise RuntimeError("triangular paper monitor is already running")
        self._run_generation += 1
        generation = self._run_generation
        self._running = True
        try:
            await self.scan(settings, run_generation=generation)
        except BaseException:
            if generation == self._run_generation:
                self._running = False
            raise
        if generation != self._run_generation or not self._running:
            return self.status()
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(generation), name="triangular-paper-monitor"
        )
        return self.status()

    async def _monitor_loop(self, generation: int) -> None:
        try:
            while self._running and generation == self._run_generation:
                await asyncio.sleep(self._settings.interval_ms / 1000)
                if self._running and generation == self._run_generation:
                    await self.scan(self._settings, run_generation=generation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._errors["monitor"] = f"{type(exc).__name__}: {exc}"
        finally:
            if generation == self._run_generation:
                self._running = False

    async def stop(self) -> dict[str, Any]:
        self._running = False
        self._run_generation += 1
        task, self._monitor_task = self._monitor_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        return self.status()

    async def reset(self) -> dict[str, Any]:
        await self.stop()
        async with self._scan_lock:
            self._portfolio = TriangularPaperPortfolio(self._initial_balances)
            self._executor = TriangularPaperExecutor(self._portfolio)
            self._execution_opportunities = []
            self._executed_snapshots = set()
            self._tickers = {}
            self._opportunities = []
            self._last_scan_ms = None
            self._scan_count = 0
            self._errors = {}
            self._venue_state = {
                venue: self._idle_venue_state(venue) for venue in self._venue_state
            }
        return self.status()

    async def close(self) -> None:
        await self.stop()
        await asyncio.gather(
            *(adapter.aclose() for adapter in self.adapters),
            return_exceptions=True,
        )

    @staticmethod
    def _opportunity_dict(
        opportunity: TriangularOpportunity,
    ) -> dict[str, Any]:
        result = opportunity.to_dict()
        result.update(
            {
                "path": " → ".join(opportunity.route),
                "gross_edge_bps": decimal_string(opportunity.gross_edge * BPS),
                "net_edge_bps": decimal_string(opportunity.net_edge * BPS),
                "expected_pnl": decimal_string(opportunity.net_profit),
            }
        )
        return result

    @staticmethod
    def _ticker_dict(ticker: MarketTicker) -> dict[str, Any]:
        return {
            "venue": ticker.venue,
            "symbol": ticker.symbol,
            "base_asset": ticker.base_asset,
            "quote_asset": ticker.quote_asset,
            "timestamp_ms": ticker.timestamp_ms,
            "bid": decimal_string(ticker.bid),
            "ask": decimal_string(ticker.ask),
            "bid_size": decimal_string(ticker.bid_size),
            "ask_size": decimal_string(ticker.ask_size),
            "quote_volume": decimal_string(ticker.quote_volume),
            "volume_usdt": decimal_string(ticker.volume_usdt),
            "snapshot_id": ticker.snapshot_id,
        }

    def _balances(self) -> dict[str, Any]:
        raw = self._portfolio.to_dict()
        if isinstance(raw, Mapping) and "balances" in raw:
            return dict(raw["balances"])
        return dict(raw)

    def _journal(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, execution in enumerate(self._executor.journal):
            row = execution.to_dict()
            opportunity = (
                self._execution_opportunities[index]
                if index < len(self._execution_opportunities)
                else None
            )
            if opportunity is not None:
                row.update(
                    {
                        "venue": opportunity.venue,
                        "path": " → ".join(opportunity.route),
                        "net_edge_bps": decimal_string(
                            opportunity.net_edge * BPS
                        ),
                        "pnl": decimal_string(opportunity.net_profit),
                        "status": "paper_filled",
                    }
                )
            rows.append(row)
        return rows

    def status(self) -> dict[str, Any]:
        opportunities = [
            self._opportunity_dict(item) for item in self._opportunities
        ]
        journal = self._journal()
        realized_pnl = self._executor.realized_pnl
        ticker_universe = {
            venue: {
                "count": len(tickers),
                "symbols": [ticker.symbol for ticker in tickers],
                "tickers": [self._ticker_dict(ticker) for ticker in tickers],
            }
            for venue, tickers in self._tickers.items()
        }
        return {
            "mode": "paper",
            "strategy": "triangular",
            "public_data_only": True,
            "live_trading_enabled": False,
            "running": self._running,
            "scanning": self._scanning,
            "last_scan_ms": self._last_scan_ms,
            "settings": self._settings.to_dict(),
            "fee_source": "configured_assumptions",
            "market_data_policy": {
                "source": "one_public_all_tickers_request_per_venue",
                "max_tickers_per_venue": self._settings.max_tickers,
                "max_staleness_ms": self.max_staleness_ms,
                "max_leg_skew_ms": self.max_leg_skew_ms,
                "monitor_min_interval_ms": 10_000,
                "execution_depth": "best_bid_ask_only",
                "instrument_rules": "not_loaded_paper_prototype",
            },
            "venues": list(self._venue_state.values()),
            "ticker_universe": ticker_universe,
            "best_opportunity": opportunities[0] if opportunities else None,
            "opportunities": opportunities[:20],
            "balances": self._balances(),
            "metrics": {
                "scan_count": self._scan_count,
                "trade_count": len(self._executor.journal),
                "winning_trades": sum(
                    1 for item in self._execution_opportunities if item.net_profit > 0
                ),
                "realized_pnl": decimal_string(realized_pnl),
            },
            "journal": journal,
            "errors": dict(self._errors),
        }
