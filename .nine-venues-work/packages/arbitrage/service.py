"""Orchestration for the public-data, paper-only arbitrage prototype.

The service deliberately depends on adapters that expose a single operation:
fetching a public order book.  It has no concept of API credentials or live
order submission.  All executions are atomic mutations of an in-memory
``PaperPortfolio``.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field, replace
from decimal import Decimal
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from packages.arbitrage.adapters import (
    BingXPublicAdapter,
    BinancePublicAdapter,
    BitgetPublicAdapter,
    BybitPublicAdapter,
    GatePublicAdapter,
    HuobiPublicAdapter,
    KuCoinPublicAdapter,
    MEXCPublicAdapter,
    OkxPublicAdapter,
    PublicVenueAdapter,
)
from packages.arbitrage.engine import ArbitrageConfig, ArbitrageEngine, split_symbol
from packages.arbitrage.diagnostics import (
    PairAssessment,
    aggregate_assessments,
    assess_pairs,
)
from packages.arbitrage.models import (
    ArbitrageOpportunity,
    OrderBook,
    PriceLevel,
    Side,
    decimal_string,
    decimal_value,
    normalize_symbol,
)
from packages.arbitrage.paper import PaperArbitrageExecutor, PaperPortfolio
from packages.arbitrage.triangular import MarketTicker
from packages.arbitrage.universe import (
    CrossVenueSymbolStats,
    select_cross_venue_universe,
)


BPS = Decimal("10000")
AUTO_SYMBOL = "AUTO"
DEFAULT_MAX_SYMBOLS = 50
AUTO_LIQUIDITY_POOL_SIZE = 150
AUTO_PAPER_INITIAL_USDT = Decimal("500")
MIN_AUTO_INITIAL_BALANCE_PER_VENUE_USDT = Decimal("100")
MAX_AUTO_INITIAL_BALANCE_PER_VENUE_USDT = Decimal("1000000")
DEFAULT_AUTO_MAX_TRADE_USDT = Decimal("25")
DEFAULT_AUTO_ACTIVATION_OBSERVATIONS = 5
DEFAULT_AUTO_EVIDENCE_WINDOW_MINUTES = 60
DEFAULT_AUTO_INVENTORY_IDLE_TIMEOUT_MINUTES = 60
DEFAULT_AUTO_MAX_ACTIVE_SYMBOLS = 2
DEFAULT_AUTO_ALLOCATION_PER_SYMBOL_VENUE_USDT = Decimal("50")
DEFAULT_AUTO_MIN_24H_VOLUME_USDT = Decimal("1000000")
DEFAULT_AUTO_BBO_DEPTH_MULTIPLIER = Decimal("2")
AUTO_REBALANCE_SAFETY_MULTIPLE = Decimal("1.5")

DEFAULT_TAKER_FEES: dict[str, Decimal] = {
    # Conservative placeholders for theory testing, not account fee quotes.
    "bybit": Decimal("0.001"),
    "binance": Decimal("0.001"),
    "okx": Decimal("0.001"),
    "bitget": Decimal("0.001"),
    "huobi": Decimal("0.002"),
    "kucoin": Decimal("0.001"),
    "mexc": Decimal("0.001"),
    "bingx": Decimal("0.001"),
    "gate": Decimal("0.002"),
}

DEFAULT_INITIAL_BALANCES: dict[str, dict[str, Decimal]] = {
    venue: {"USDT": AUTO_PAPER_INITIAL_USDT}
    for venue in DEFAULT_TAKER_FEES
}

# Common, deliberately coarse paper increments across the four prototype
# venues.  They prevent arbitrary fractional quantities, but they remain
# assumptions; live instrument metadata is required before any real trading.
DEFAULT_COMMON_QUANTITY_STEPS: dict[str, Decimal] = {
    "BTCUSDT": Decimal("0.0001"),
    "ETHUSDT": Decimal("0.001"),
    "SOLUSDT": Decimal("0.01"),
}
DEFAULT_MIN_NOTIONALS: dict[str, Decimal] = {
    symbol: Decimal("10") for symbol in DEFAULT_COMMON_QUANTITY_STEPS
}


def _clock_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(slots=True)
class _CandidateEvidence:
    """Consecutive fresh liquid/volatile-universe observations.

    Profitability is deliberately absent from the activation gate.  Edge and
    route fields are merely informational snapshots when the strict arbitrage
    engine happens to find a qualifying route for the same symbol.
    """

    symbol: str
    observations: list[tuple[int, tuple[Any, ...]]] = field(default_factory=list)
    last_seen_scan: int | None = None
    last_seen_ms: int | None = None
    latest_net_edge_bps: Decimal = Decimal("0")
    best_net_edge_bps: Decimal = Decimal("0")
    latest_route: str | None = None


@dataclass(slots=True)
class _RouteProfitEvidence:
    """Unique strict opportunities retained for one directed AUTO route."""

    symbol: str
    buy_venue: str
    sell_venue: str
    observations: list[tuple[int, tuple[Any, ...], Decimal]] = field(
        default_factory=list
    )


@dataclass(frozen=True, slots=True)
class _InventoryAllocation:
    venue: str
    price: Decimal
    quantity: Decimal
    gross_notional_usdt: Decimal
    fee_usdt: Decimal
    quote_spent_usdt: Decimal


@dataclass(slots=True)
class _ActiveInventory:
    symbol: str
    base_asset: str
    activated_scan: int
    activated_ms: int
    last_seen_ms: int
    evidence_observations: int
    target_per_venue_usdt: Decimal
    allocations: tuple[_InventoryAllocation, ...]
    state: str = "active"


@dataclass(frozen=True, slots=True)
class _InventoryJournalEntry:
    """A balance-changing AUTO allocation or liquidation fill."""

    timestamp_ms: int
    event: str
    symbol: str
    venue: str
    side: str
    quantity: Decimal
    price: Decimal
    gross_notional_usdt: Decimal
    fee_usdt: Decimal
    cash_flow_usdt: Decimal


@dataclass(frozen=True, slots=True)
class _RebalanceJournalEntry:
    """One economically gated, balance-neutral PAPER inventory rotation.

    This is not an arbitrage fill or a free transfer.  Base is sold on the
    accumulated buy exchange and the same quantity is bought on the depleted
    sell exchange as one atomic virtual operation.
    """

    timestamp_ms: int
    symbol: str
    buy_venue: str
    sell_venue: str
    base_asset: str
    quantity: Decimal
    source_sell_price: Decimal
    destination_buy_price: Decimal
    source_sale_notional_usdt: Decimal
    destination_buy_notional_usdt: Decimal
    source_sell_fee_usdt: Decimal
    destination_buy_fee_usdt: Decimal
    future_exit_fee_estimate_usdt: Decimal
    quote_outflow_usdt: Decimal
    setup_cost_usdt: Decimal
    projected_route_profit_usdt: Decimal
    required_projected_profit_usdt: Decimal
    safety_multiple: Decimal
    evidence_count: int
    source_cash_flow_usdt: Decimal
    destination_cash_flow_usdt: Decimal


@dataclass(frozen=True, slots=True)
class ScanSettings:
    """Validated inputs for one scan or a recurring paper monitor."""

    symbol: str = "BTCUSDT"
    notional: Decimal = DEFAULT_AUTO_MAX_TRADE_USDT
    min_net_edge_bps: Decimal = Decimal("5")
    risk_buffer_bps: Decimal = Decimal("2")
    auto_execute: bool = False
    interval_ms: int = 2000
    max_symbols: int = DEFAULT_MAX_SYMBOLS
    activation_observations: int = DEFAULT_AUTO_ACTIVATION_OBSERVATIONS
    evidence_window_minutes: int = DEFAULT_AUTO_EVIDENCE_WINDOW_MINUTES
    inventory_idle_timeout_minutes: int = (
        DEFAULT_AUTO_INVENTORY_IDLE_TIMEOUT_MINUTES
    )
    max_active_symbols: int = DEFAULT_AUTO_MAX_ACTIVE_SYMBOLS
    allocation_per_symbol_venue_usdt: Decimal = (
        DEFAULT_AUTO_ALLOCATION_PER_SYMBOL_VENUE_USDT
    )
    min_24h_volume_usdt: Decimal = DEFAULT_AUTO_MIN_24H_VOLUME_USDT
    bbo_depth_multiplier: Decimal = DEFAULT_AUTO_BBO_DEPTH_MULTIPLIER
    initial_balance_per_venue_usdt: Decimal = AUTO_PAPER_INITIAL_USDT
    rebalance_safety_multiple: Decimal = AUTO_REBALANCE_SAFETY_MULTIPLE

    def __post_init__(self) -> None:
        symbol = normalize_symbol(self.symbol)
        notional = decimal_value(self.notional, name="notional")
        min_edge = decimal_value(self.min_net_edge_bps, name="min_net_edge_bps")
        risk_buffer = decimal_value(self.risk_buffer_bps, name="risk_buffer_bps")
        allocation = decimal_value(
            self.allocation_per_symbol_venue_usdt,
            name="allocation_per_symbol_venue_usdt",
        )
        minimum_volume = decimal_value(
            self.min_24h_volume_usdt,
            name="min_24h_volume_usdt",
        )
        depth_multiplier = decimal_value(
            self.bbo_depth_multiplier,
            name="bbo_depth_multiplier",
        )
        initial_balance = decimal_value(
            self.initial_balance_per_venue_usdt,
            name="initial_balance_per_venue_usdt",
        )
        rebalance_safety_multiple = decimal_value(
            self.rebalance_safety_multiple,
            name="rebalance_safety_multiple",
        )
        if notional <= 0:
            raise ValueError("notional must be greater than zero")
        if min_edge < 0:
            raise ValueError("min_net_edge_bps must not be negative")
        if risk_buffer < 0:
            raise ValueError("risk_buffer_bps must not be negative")
        if isinstance(self.interval_ms, bool):
            raise TypeError("interval_ms must be an integer")
        interval = int(self.interval_ms)
        if interval < 500:
            raise ValueError("interval_ms must be at least 500")
        if symbol == AUTO_SYMBOL and interval < 2_000:
            raise ValueError("AUTO interval_ms must be at least 2000")
        if isinstance(self.max_symbols, bool):
            raise TypeError("max_symbols must be an integer")
        max_symbols = int(self.max_symbols)
        if not 1 <= max_symbols <= DEFAULT_MAX_SYMBOLS:
            raise ValueError("max_symbols must be between 1 and 50")
        if isinstance(self.activation_observations, bool):
            raise TypeError("activation_observations must be an integer")
        activation_observations = int(self.activation_observations)
        if not 1 <= activation_observations <= 100:
            raise ValueError("activation_observations must be between 1 and 100")
        if isinstance(self.evidence_window_minutes, bool):
            raise TypeError("evidence_window_minutes must be an integer")
        evidence_window_minutes = int(self.evidence_window_minutes)
        if not 1 <= evidence_window_minutes <= 1_440:
            raise ValueError(
                "evidence_window_minutes must be between 1 and 1440"
            )
        if isinstance(self.inventory_idle_timeout_minutes, bool):
            raise TypeError("inventory_idle_timeout_minutes must be an integer")
        inventory_idle_timeout_minutes = int(
            self.inventory_idle_timeout_minutes
        )
        if not 1 <= inventory_idle_timeout_minutes <= 10_080:
            raise ValueError(
                "inventory_idle_timeout_minutes must be between 1 and 10080"
            )
        if isinstance(self.max_active_symbols, bool):
            raise TypeError("max_active_symbols must be an integer")
        max_active_symbols = int(self.max_active_symbols)
        if not 1 <= max_active_symbols <= DEFAULT_MAX_SYMBOLS:
            raise ValueError("max_active_symbols must be between 1 and 50")
        if allocation <= 0:
            raise ValueError(
                "allocation_per_symbol_venue_usdt must be greater than zero"
            )
        if not (
            MIN_AUTO_INITIAL_BALANCE_PER_VENUE_USDT
            <= initial_balance
            <= MAX_AUTO_INITIAL_BALANCE_PER_VENUE_USDT
        ):
            raise ValueError(
                "initial_balance_per_venue_usdt must be between 100 and "
                "1000000"
            )
        if allocation > initial_balance:
            raise ValueError(
                "allocation_per_symbol_venue_usdt must not exceed "
                "initial_balance_per_venue_usdt"
            )
        if not Decimal("100000") <= minimum_volume <= Decimal("100000000"):
            raise ValueError(
                "min_24h_volume_usdt must be between 100000 and 100000000"
            )
        if not Decimal("1") <= depth_multiplier <= Decimal("100"):
            raise ValueError("bbo_depth_multiplier must be between 1 and 100")
        if not Decimal("1.5") <= rebalance_safety_multiple <= Decimal("10"):
            raise ValueError(
                "rebalance_safety_multiple must be between 1.5 and 10"
            )
        if symbol == AUTO_SYMBOL:
            if notional < Decimal("10"):
                raise ValueError("AUTO notional must be at least 10 USDT")
            if allocation < notional:
                raise ValueError(
                    "AUTO allocation_per_symbol_venue_usdt must be greater "
                    "than or equal to notional"
                )
            if max_active_symbols > max_symbols:
                raise ValueError(
                    "AUTO max_active_symbols must not exceed max_symbols"
                )
            committed = Decimal(max_active_symbols) * allocation + notional
            if committed > initial_balance:
                raise ValueError(
                    "AUTO budget exceeds initial balance per venue: "
                    "max_active_symbols * allocation_per_symbol_venue_usdt "
                    "+ notional must be <= initial_balance_per_venue_usdt"
                )
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "notional", notional)
        object.__setattr__(self, "min_net_edge_bps", min_edge)
        object.__setattr__(self, "risk_buffer_bps", risk_buffer)
        object.__setattr__(self, "interval_ms", interval)
        object.__setattr__(self, "max_symbols", max_symbols)
        object.__setattr__(
            self, "activation_observations", activation_observations
        )
        object.__setattr__(
            self, "evidence_window_minutes", evidence_window_minutes
        )
        object.__setattr__(
            self,
            "inventory_idle_timeout_minutes",
            inventory_idle_timeout_minutes,
        )
        object.__setattr__(self, "max_active_symbols", max_active_symbols)
        object.__setattr__(
            self, "allocation_per_symbol_venue_usdt", allocation
        )
        object.__setattr__(self, "min_24h_volume_usdt", minimum_volume)
        object.__setattr__(self, "bbo_depth_multiplier", depth_multiplier)
        object.__setattr__(
            self,
            "initial_balance_per_venue_usdt",
            initial_balance,
        )
        object.__setattr__(
            self,
            "rebalance_safety_multiple",
            rebalance_safety_multiple,
        )

    @property
    def evidence_window_ms(self) -> int:
        return self.evidence_window_minutes * 60 * 1_000

    @property
    def inventory_idle_timeout_ms(self) -> int:
        return self.inventory_idle_timeout_minutes * 60 * 1_000

    @property
    def activation_min_bbo_notional_usdt(self) -> Decimal:
        return max(
            self.allocation_per_symbol_venue_usdt,
            self.notional * self.bbo_depth_multiplier,
        )

    @property
    def auto_base_target_usdt(self) -> Decimal:
        return (
            Decimal(self.max_active_symbols)
            * self.allocation_per_symbol_venue_usdt
        )

    @property
    def auto_usdt_reserve_target(self) -> Decimal:
        return self.initial_balance_per_venue_usdt - self.auto_base_target_usdt

    @property
    def auto_execution_base_cap_usdt(self) -> Decimal:
        return self.auto_base_target_usdt + self.notional

    @property
    def auto_execution_usdt_floor(self) -> Decimal:
        return self.auto_usdt_reserve_target - self.notional

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "notional": decimal_string(self.notional),
            "min_net_edge_bps": decimal_string(self.min_net_edge_bps),
            "risk_buffer_bps": decimal_string(self.risk_buffer_bps),
            "auto_execute": self.auto_execute,
            "interval_ms": self.interval_ms,
            "max_symbols": self.max_symbols,
            "activation_observations": self.activation_observations,
            "evidence_window_minutes": self.evidence_window_minutes,
            "inventory_idle_timeout_minutes": (
                self.inventory_idle_timeout_minutes
            ),
            "max_active_symbols": self.max_active_symbols,
            "allocation_per_symbol_venue_usdt": decimal_string(
                self.allocation_per_symbol_venue_usdt
            ),
            "min_24h_volume_usdt": decimal_string(
                self.min_24h_volume_usdt
            ),
            "bbo_depth_multiplier": decimal_string(
                self.bbo_depth_multiplier
            ),
            "initial_balance_per_venue_usdt": decimal_string(
                self.initial_balance_per_venue_usdt
            ),
            "rebalance_safety_multiple": decimal_string(
                self.rebalance_safety_multiple
            ),
        }


class ArbitragePaperService:
    """Fetch public books, discover all venue pairs, and simulate both legs."""

    def __init__(
        self,
        adapters: Iterable[PublicVenueAdapter] | None = None,
        *,
        initial_balances: Mapping[str, Mapping[str, Decimal | str | int | float]] | None = None,
        taker_fees: Mapping[str, Decimal | str | int | float] | None = None,
        max_staleness_ms: int = 5_000,
        max_pair_skew_ms: int = 2_000,
        depth: int = 50,
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
                HuobiPublicAdapter(),
                KuCoinPublicAdapter(),
                MEXCPublicAdapter(),
                BingXPublicAdapter(),
                GatePublicAdapter(),
            )
        )
        if len(self.adapters) < 2:
            raise ValueError("at least two public venue adapters are required")
        venue_names = [adapter.venue.lower() for adapter in self.adapters]
        if len(set(venue_names)) != len(venue_names):
            raise ValueError("venue adapter names must be unique")
        if isinstance(depth, bool) or int(depth) <= 0:
            raise ValueError("depth must be a positive integer")
        if isinstance(max_staleness_ms, bool) or int(max_staleness_ms) < 0:
            raise ValueError("max_staleness_ms must not be negative")
        if isinstance(max_pair_skew_ms, bool) or int(max_pair_skew_ms) < 0:
            raise ValueError("max_pair_skew_ms must not be negative")

        self.depth = int(depth)
        self.max_staleness_ms = int(max_staleness_ms)
        self.max_pair_skew_ms = int(max_pair_skew_ms)
        self.clock_ms = clock_ms or _clock_ms
        default_fees = {
            venue: DEFAULT_TAKER_FEES.get(venue, Decimal("0.001"))
            for venue in venue_names
        }
        self.taker_fees = {
            venue.lower(): decimal_value(fee, name=f"taker fee for {venue}")
            for venue, fee in (
                default_fees if taker_fees is None else taker_fees
            ).items()
        }
        self._auto_inventory_enabled = initial_balances is None
        self._initial_balance_per_venue_usdt = AUTO_PAPER_INITIAL_USDT
        self._initial_balances = (
            {
                venue: {"USDT": self._initial_balance_per_venue_usdt}
                for venue in venue_names
            }
            if initial_balances is None
            else initial_balances
        )
        self._portfolio = PaperPortfolio(self._initial_balances)
        self._executor = PaperArbitrageExecutor(self._portfolio, self.taker_fees)
        self._execution_opportunities: list[ArbitrageOpportunity] = []
        self._executed_snapshot_pairs: set[tuple[Any, ...]] = set()

        self._scan_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._monitor_task: asyncio.Task[None] | None = None
        self._running = False
        self._run_generation = 0
        self._scanning = False
        self._settings = ScanSettings(symbol=AUTO_SYMBOL)
        self._last_scan_ms: int | None = None
        self._scan_count = 0
        self._books: dict[tuple[str, str], OrderBook] = {}
        self._tradable_book_keys: set[tuple[str, str]] = set()
        self._universe: list[CrossVenueSymbolStats] = []
        self._candidate_evidence: dict[str, _CandidateEvidence] = {}
        self._route_profit_evidence: dict[
            tuple[str, str, str], _RouteProfitEvidence
        ] = {}
        self._active_inventory: dict[str, _ActiveInventory] = {}
        self._inventory_journal: list[_InventoryJournalEntry] = []
        self._rebalance_journal: list[_RebalanceJournalEntry] = []
        self._consumed_rebalance_snapshot_pairs: set[tuple[Any, ...]] = set()
        self._consumed_rebalance_profit_evidence: set[tuple[Any, ...]] = set()
        self._consumed_liquidation_snapshots: set[tuple[Any, ...]] = set()
        self._opportunities: list[ArbitrageOpportunity] = []
        self._pair_assessments: list[PairAssessment] = []
        self._last_profitable_signal: tuple[ArbitrageOpportunity, int] | None = None
        self._last_execution_candidate_count = 0
        self._last_execution_candidate_keys: set[tuple[str, str, str]] = set()
        self._last_executed_count = 0
        self._current_executable_opportunity: ArbitrageOpportunity | None = None
        self._execution_blockers: list[dict[str, Any]] = []

        self._venue_state: dict[str, dict[str, Any]] = {
            adapter.venue.lower(): {
                "name": adapter.venue.lower(),
                "ok": False,
                "status": "idle",
                "latency_ms": None,
                "timestamp_ms": None,
                "book_age_ms": None,
                "ticker_count": 0,
                "selected_ticker_count": 0,
                "error": None,
            }
            for adapter in self.adapters
        }
        self._errors: dict[str, str] = {}

    @property
    def initial_balance_per_venue_usdt(self) -> Decimal:
        """Configured PAPER seed retained across requests until reset."""

        return self._initial_balance_per_venue_usdt

    @property
    def running(self) -> bool:
        return self._running

    def _paper_balances_are_pristine(self) -> bool:
        """Return whether changing the configured seed cannot erase activity."""

        if not self._auto_inventory_enabled:
            return False
        expected = PaperPortfolio(self._initial_balances).snapshot()
        return (
            not self._executor.journal
            and not self._inventory_journal
            and not self._rebalance_journal
            and not self._active_inventory
            and self._portfolio.snapshot() == expected
        )

    def _set_pristine_initial_balance(self, amount: Decimal) -> None:
        """Atomically reseed an untouched AUTO portfolio for every adapter."""

        if amount == self._initial_balance_per_venue_usdt:
            return
        if not self._paper_balances_are_pristine():
            raise RuntimeError(
                "initial PAPER balance can only be changed before balance "
                "activity; stop and reset with the new balance first"
            )
        self._initial_balance_per_venue_usdt = amount
        self._initial_balances = {
            adapter.venue.lower(): {"USDT": amount}
            for adapter in self.adapters
        }
        self._portfolio = PaperPortfolio(self._initial_balances)
        self._executor = PaperArbitrageExecutor(self._portfolio, self.taker_fees)

    def _apply_initial_balance_setting(self, settings: ScanSettings) -> None:
        if not self._auto_inventory_enabled or settings.symbol != AUTO_SYMBOL:
            return
        self._set_pristine_initial_balance(
            settings.initial_balance_per_venue_usdt
        )

    async def _fetch_book(
        self, adapter: PublicVenueAdapter, symbol: str
    ) -> tuple[str, OrderBook | None, int, Exception | None]:
        venue = adapter.venue.lower()
        started = time.perf_counter_ns()
        try:
            adapter_max_depth = getattr(adapter, "max_depth", self.depth)
            requested_depth = min(self.depth, int(adapter_max_depth))
            book = await adapter.fetch_order_book(
                symbol,
                depth=requested_depth,
            )
            if book.venue != venue:
                raise ValueError(
                    f"adapter {venue} returned a book for venue {book.venue}"
                )
            if book.symbol != symbol:
                raise ValueError(
                    f"adapter {venue} returned {book.symbol}, expected {symbol}"
                )
            return venue, book, (time.perf_counter_ns() - started) // 1_000_000, None
        except Exception as exc:  # one failed venue must not cancel the round
            return venue, None, (time.perf_counter_ns() - started) // 1_000_000, exc

    async def _fetch_tickers(
        self, adapter: PublicVenueAdapter
    ) -> tuple[
        str,
        tuple[MarketTicker, ...] | None,
        int,
        int,
        Exception | None,
    ]:
        venue = adapter.venue.lower()
        started = time.perf_counter_ns()
        try:
            tickers = tuple(await adapter.fetch_tickers())
            if not tickers:
                raise ValueError("all-tickers response is empty")
            if any(ticker.venue != venue for ticker in tickers):
                raise ValueError(f"adapter {venue} returned another venue's ticker")
            completed_ns = time.perf_counter_ns()
            latency_ms = (completed_ns - started) // 1_000_000
            return venue, tickers, latency_ms, completed_ns, None
        except Exception as exc:
            completed_ns = time.perf_counter_ns()
            latency_ms = (completed_ns - started) // 1_000_000
            return venue, None, latency_ms, completed_ns, exc

    def _config(
        self,
        settings: ScanSettings,
        symbols: Sequence[str] | None = None,
    ) -> ArbitrageConfig:
        auto = settings.symbol == AUTO_SYMBOL
        selected_symbols = tuple(symbols or ())
        return ArbitrageConfig(
            taker_fees=self.taker_fees,
            min_net_edge=settings.min_net_edge_bps / BPS,
            risk_buffer=settings.risk_buffer_bps / BPS,
            max_notional=settings.notional,
            max_staleness_ms=self.max_staleness_ms,
            default_taker_fee=Decimal("0.001"),
            quantity_steps={} if auto else DEFAULT_COMMON_QUANTITY_STEPS,
            min_notionals=(
                {symbol: Decimal("10") for symbol in selected_symbols}
                if auto
                else DEFAULT_MIN_NOTIONALS
            ),
        )

    @staticmethod
    def _book_identity(book: OrderBook) -> tuple[Any, ...]:
        if book.snapshot_id is not None:
            return (book.venue, book.symbol, "id", book.snapshot_id)
        # Conservative fallback for synthetic/custom adapters: unchanged
        # depth is treated as the same liquidity even if its receipt time moves.
        return (
            book.venue,
            book.symbol,
            "depth",
            tuple((level.price, level.quantity) for level in book.bids),
            tuple((level.price, level.quantity) for level in book.asks),
        )

    def _opportunity_snapshot_key(
        self,
        opportunity: ArbitrageOpportunity,
        books: Mapping[tuple[str, str], OrderBook],
    ) -> tuple[Any, ...]:
        return (
            opportunity.symbol,
            opportunity.buy_venue,
            self._book_identity(
                books[(opportunity.symbol, opportunity.buy_venue)]
            ),
            opportunity.sell_venue,
            self._book_identity(
                books[(opportunity.symbol, opportunity.sell_venue)]
            ),
        )

    @staticmethod
    def _route_key(
        opportunity: ArbitrageOpportunity,
    ) -> tuple[str, str, str]:
        return (
            opportunity.symbol,
            opportunity.buy_venue,
            opportunity.sell_venue,
        )

    def _record_route_profit_evidence(
        self,
        opportunities: Sequence[ArbitrageOpportunity],
        books: Mapping[tuple[str, str], OrderBook],
        settings: ScanSettings,
        *,
        now_ms: int,
    ) -> None:
        """Retain unique strict route profits inside the evidence window."""

        cutoff_ms = now_ms - settings.evidence_window_ms
        for evidence in self._route_profit_evidence.values():
            evidence.observations = [
                item for item in evidence.observations if item[0] >= cutoff_ms
            ]
        for opportunity in opportunities:
            route_key = self._route_key(opportunity)
            snapshot_key = self._opportunity_snapshot_key(opportunity, books)
            evidence = self._route_profit_evidence.setdefault(
                route_key,
                _RouteProfitEvidence(
                    symbol=opportunity.symbol,
                    buy_venue=opportunity.buy_venue,
                    sell_venue=opportunity.sell_venue,
                ),
            )
            if all(
                recorded_key != snapshot_key
                for _timestamp, recorded_key, _profit in evidence.observations
            ):
                evidence.observations.append(
                    (now_ms, snapshot_key, opportunity.net_profit)
                )

    @staticmethod
    def _allocation_quantity(
        active: _ActiveInventory,
        venue: str,
    ) -> Decimal:
        return sum(
            (
                allocation.quantity
                for allocation in active.allocations
                if allocation.venue == venue
            ),
            Decimal("0"),
        )

    def _attempt_safe_auto_rebalance(
        self,
        opportunities: Sequence[ArbitrageOpportunity],
        books: Mapping[tuple[str, str], OrderBook],
        settings: ScanSettings,
        *,
        now_ms: int,
    ) -> dict[tuple[str, str, str], dict[str, Any]]:
        """Rotate depleted inventory with two real PAPER BBO legs.

        The operation conserves total base quantity: excess inventory is sold
        on the route's accumulated buy exchange and the identical quantity is
        bought on the depleted sell exchange.  It is allowed only when unique,
        unconsumed strict-profit observations inside the configured evidence
        window cover the complete modeled cost by the safety multiple.
        """

        attempts: dict[tuple[str, str, str], dict[str, Any]] = {}
        if not self._auto_inventory_enabled:
            return attempts
        rebalanced_this_scan = False
        minimum_notional = Decimal("10")
        for opportunity in opportunities:
            route_key = self._route_key(opportunity)
            active = self._active_inventory.get(opportunity.symbol)
            if active is None or active.state != "active":
                continue
            sell_book = books.get((opportunity.symbol, opportunity.sell_venue))
            source_book = books.get((opportunity.symbol, opportunity.buy_venue))
            if source_book is None or sell_book is None:
                continue
            available_destination = self._portfolio.balance(
                opportunity.sell_venue,
                opportunity.base_asset,
            )
            # No rotation is needed while the destination can cover the full
            # current strict opportunity.  Once a fill has shifted inventory,
            # rotate up to one full trade from the accumulated source back to
            # the destination; moving only the tiny arithmetic shortfall would
            # leave the source-side balance corridor blocked indefinitely.
            if available_destination >= opportunity.quantity:
                continue

            snapshot_key = self._opportunity_snapshot_key(opportunity, books)
            attempt: dict[str, Any] = {
                "status": "not_attempted",
                "snapshot_key_consumed": False,
            }
            attempts[route_key] = attempt
            if not settings.auto_execute:
                attempt["reason"] = "auto_execute_disabled"
                continue
            if rebalanced_this_scan:
                attempt["reason"] = "one_rebalance_per_scan"
                continue
            if snapshot_key in self._executed_snapshot_pairs:
                attempt["reason"] = "execution_snapshot_already_used"
                continue
            if snapshot_key in self._consumed_rebalance_snapshot_pairs:
                attempt["reason"] = "rebalance_snapshot_already_used"
                continue

            source_target = self._allocation_quantity(
                active,
                opportunity.buy_venue,
            )
            source_available = self._portfolio.balance(
                opportunity.buy_venue,
                opportunity.base_asset,
            )
            source_excess = max(Decimal("0"), source_available - source_target)
            destination_shortfall = max(
                Decimal("0"),
                opportunity.quantity - available_destination,
            )
            quantity = min(source_excess, opportunity.quantity)
            attempt.update(
                {
                    "source_excess_base_quantity": decimal_string(source_excess),
                    "destination_shortfall_base_quantity": decimal_string(
                        destination_shortfall
                    ),
                    "proposed_quantity": decimal_string(quantity),
                }
            )
            if quantity <= 0 or quantity * opportunity.buy_vwap < minimum_notional:
                attempt["reason"] = "insufficient_excess_source_inventory"
                continue
            try:
                source_sale = source_book.executable_vwap(Side.SELL, quantity)
                destination_buy = sell_book.executable_vwap(Side.BUY, quantity)
            except Exception as exc:
                attempt["reason"] = "insufficient_rebalance_depth"
                attempt["detail"] = f"{type(exc).__name__}: {exc}"
                continue

            source_fee_rate = self.taker_fees.get(
                opportunity.buy_venue,
                Decimal("0.001"),
            )
            destination_fee_rate = self.taker_fees.get(
                opportunity.sell_venue,
                Decimal("0.001"),
            )
            source_sell_fee = source_sale.notional * source_fee_rate
            destination_buy_fee = destination_buy.notional * destination_fee_rate
            source_credit = source_sale.notional - source_sell_fee
            destination_debit = destination_buy.notional + destination_buy_fee
            quote_outflow = max(
                Decimal("0"),
                destination_debit - source_credit,
            )
            future_exit_fee = (
                quantity * sell_book.best_bid * destination_fee_rate
            )
            setup_cost = quote_outflow + future_exit_fee
            required_profit = setup_cost * settings.rebalance_safety_multiple

            evidence = self._route_profit_evidence.get(route_key)
            usable = [] if evidence is None else [
                item
                for item in evidence.observations
                if item[1] not in self._consumed_rebalance_profit_evidence
            ]
            selected_evidence: list[tuple[int, tuple[Any, ...], Decimal]] = []
            projected_profit = Decimal("0")
            for item in usable:
                selected_evidence.append(item)
                projected_profit += item[2]
                if projected_profit >= required_profit:
                    break
            attempt.update(
                {
                    "projected_route_profit_usdt": decimal_string(
                        projected_profit
                    ),
                    "setup_cost_usdt": decimal_string(setup_cost),
                    "required_projected_profit_usdt": decimal_string(
                        required_profit
                    ),
                    "safety_multiple": decimal_string(
                        settings.rebalance_safety_multiple
                    ),
                    "evidence_count": len(selected_evidence),
                }
            )
            if projected_profit < required_profit:
                attempt["reason"] = "rebalance_not_economic"
                continue
            destination_usdt = self._portfolio.balance(
                opportunity.sell_venue,
                opportunity.quote_asset,
            )
            if (
                destination_usdt - destination_debit
                < settings.auto_execution_usdt_floor
            ):
                attempt["reason"] = "insufficient_destination_quote_reserve"
                continue

            deltas = {
                (opportunity.buy_venue, opportunity.base_asset): -quantity,
                (opportunity.buy_venue, opportunity.quote_asset): source_credit,
                (opportunity.sell_venue, opportunity.quote_asset): (
                    -destination_debit
                ),
                (opportunity.sell_venue, opportunity.base_asset): quantity,
            }
            proposed = self._portfolio._propose(deltas)
            # Commit all balances before journals/consumption markers so a
            # failed proposal leaves every observable state untouched.
            self._portfolio._commit(proposed)
            self._consumed_rebalance_snapshot_pairs.add(snapshot_key)
            self._consumed_rebalance_profit_evidence.update(
                item[1] for item in selected_evidence
            )
            self._rebalance_journal.append(
                _RebalanceJournalEntry(
                    timestamp_ms=now_ms,
                    symbol=opportunity.symbol,
                    buy_venue=opportunity.buy_venue,
                    sell_venue=opportunity.sell_venue,
                    base_asset=opportunity.base_asset,
                    quantity=quantity,
                    source_sell_price=source_sale.average_price,
                    destination_buy_price=destination_buy.average_price,
                    source_sale_notional_usdt=source_sale.notional,
                    destination_buy_notional_usdt=destination_buy.notional,
                    source_sell_fee_usdt=source_sell_fee,
                    destination_buy_fee_usdt=destination_buy_fee,
                    future_exit_fee_estimate_usdt=future_exit_fee,
                    quote_outflow_usdt=quote_outflow,
                    setup_cost_usdt=setup_cost,
                    projected_route_profit_usdt=projected_profit,
                    required_projected_profit_usdt=required_profit,
                    safety_multiple=settings.rebalance_safety_multiple,
                    evidence_count=len(selected_evidence),
                    source_cash_flow_usdt=source_credit,
                    destination_cash_flow_usdt=-destination_debit,
                )
            )
            attempt["status"] = "paper_rebalanced"
            attempt["reason"] = None
            attempt["snapshot_key_consumed"] = True
            rebalanced_this_scan = True
        return attempts

    def _build_execution_blockers(
        self,
        opportunities: Sequence[ArbitrageOpportunity],
        execution_candidates: Sequence[ArbitrageOpportunity],
        books: Mapping[tuple[str, str], OrderBook],
        settings: ScanSettings,
        rebalance_attempts: Mapping[
            tuple[str, str, str], Mapping[str, Any]
        ] | None = None,
    ) -> list[dict[str, Any]]:
        """Explain why a strict current market signal cannot PAPER-fill."""

        candidate_keys = {
            self._route_key(opportunity) for opportunity in execution_candidates
        }
        attempts = rebalance_attempts or {}
        rows: list[dict[str, Any]] = []
        for opportunity in opportunities[:20]:
            route_key = self._route_key(opportunity)
            snapshot_key = self._opportunity_snapshot_key(opportunity, books)
            base = {
                "symbol": opportunity.symbol,
                "route": opportunity.route,
                "buy_venue": opportunity.buy_venue,
                "sell_venue": opportunity.sell_venue,
                "base_asset": opportunity.base_asset,
                "required_base_quantity": decimal_string(
                    opportunity.quantity
                ),
                "available_base_quantity": decimal_string(
                    self._portfolio.balance(
                        opportunity.sell_venue,
                        opportunity.base_asset,
                    )
                ),
            }
            available = self._portfolio.balance(
                opportunity.sell_venue,
                opportunity.base_asset,
            )
            base["shortfall_base_quantity"] = decimal_string(
                max(Decimal("0"), opportunity.quantity - available)
            )
            active = self._active_inventory.get(opportunity.symbol)
            if active is None:
                rows.append(
                    {
                        **base,
                        "code": "inventory_not_active",
                        "message": (
                            "strict market signal exists, but this symbol has "
                            "no active PAPER inventory"
                        ),
                    }
                )
                continue
            if snapshot_key in self._consumed_rebalance_snapshot_pairs:
                attempt = attempts.get(route_key)
                rows.append(
                    {
                        **base,
                        "code": "rebalance_snapshot_consumed",
                        "message": (
                            "this snapshot was used to rebalance PAPER "
                            "inventory; execution waits for fresh liquidity"
                        ),
                        **(
                            {"rebalance": dict(attempt)}
                            if attempt is not None
                            else {}
                        ),
                    }
                )
                continue
            if active.state != "active":
                rows.append(
                    {
                        **base,
                        "code": "inventory_pending_liquidation",
                        "message": "PAPER inventory is pending liquidation",
                    }
                )
                continue
            if snapshot_key in self._executed_snapshot_pairs:
                rows.append(
                    {
                        **base,
                        "code": "duplicate_execution_snapshot",
                        "message": (
                            "this exact public liquidity snapshot was already "
                            "used by a PAPER execution"
                        ),
                    }
                )
                continue
            if route_key in candidate_keys:
                if not settings.auto_execute:
                    rows.append(
                        {
                            **base,
                            "code": "auto_execute_disabled",
                            "message": "AUTO-PAPER execution is disabled",
                        }
                    )
                continue
            attempt = attempts.get(route_key)
            if available < opportunity.quantity:
                row = {
                    **base,
                    "code": "insufficient_sell_inventory",
                    "message": (
                        f"not enough {opportunity.base_asset} on "
                        f"{opportunity.sell_venue} for the strict route"
                    ),
                }
                if attempt is not None:
                    row["rebalance"] = dict(attempt)
                rows.append(row)
                continue
            rows.append(
                {
                    **base,
                    "code": "balance_corridor",
                    "message": (
                        "the route is profitable but outside the configured "
                        "per-exchange PAPER reserve/cap corridor"
                    ),
                }
            )
        return rows

    @staticmethod
    def _ticker_book(ticker: MarketTicker) -> OrderBook:
        """Convert executable top-of-book ticker data into a one-level book."""

        return OrderBook(
            venue=ticker.venue,
            symbol=ticker.symbol,
            timestamp_ms=ticker.timestamp_ms,
            bids=(PriceLevel(ticker.bid, ticker.bid_size),),
            asks=(PriceLevel(ticker.ask, ticker.ask_size),),
            snapshot_id=ticker.snapshot_id,
        )

    def _record_auto_candidate_evidence(
        self,
        books: Mapping[tuple[str, str], OrderBook],
        settings: ScanSettings,
        *,
        scan_number: int,
        now_ms: int,
        profitable_opportunities: Sequence[ArbitrageOpportunity] = (),
    ) -> tuple[str, ...]:
        """Record consecutive fresh observations of viable ranked symbols.

        AUTO pre-positioning does not require a profitable edge.  Within the
        already liquid/volatile universe, however, a current strict profitable
        route receives first claim on a scarce inventory slot; remaining slots
        follow deterministic universe rank.  Every target must still pass the
        full bid/ask BBO gate on at least two venues.  This bounded target set
        permits displaced holdings to age out instead of remaining funded
        forever.  A repeated BBO is still only one independent observation.
        """

        cutoff_ms = now_ms - settings.evidence_window_ms
        for evidence in self._candidate_evidence.values():
            evidence.observations = [
                item for item in evidence.observations if item[0] >= cutoff_ms
            ]

        best_by_symbol: dict[str, ArbitrageOpportunity] = {}
        for opportunity in profitable_opportunities:
            best_by_symbol.setdefault(opportunity.symbol, opportunity)

        target_symbols: list[str] = []
        universe_symbols = {stats.symbol for stats in self._universe}
        for opportunity in profitable_opportunities:
            if len(target_symbols) >= settings.max_active_symbols:
                break
            if (
                opportunity.symbol in universe_symbols
                and opportunity.symbol not in target_symbols
                and self._activation_plan(
                    opportunity.symbol,
                    books,
                    settings,
                    check_budget=False,
                )
            ):
                target_symbols.append(opportunity.symbol)
        for stats in self._universe:
            if len(target_symbols) >= settings.max_active_symbols:
                break
            if stats.symbol not in target_symbols and self._activation_plan(
                stats.symbol,
                books,
                settings,
                check_budget=False,
            ):
                target_symbols.append(stats.symbol)

        target_set = set(target_symbols)
        for symbol in target_symbols:
            evidence = self._candidate_evidence.setdefault(
                symbol,
                _CandidateEvidence(symbol=symbol),
            )
            symbol_books = tuple(
                self._book_identity(book)
                for (candidate_symbol, _venue), book in sorted(books.items())
                if candidate_symbol == symbol
            )
            snapshot_key = (symbol, *symbol_books)
            if all(key != snapshot_key for _timestamp, key in evidence.observations):
                evidence.observations.append((now_ms, snapshot_key))
            evidence.last_seen_scan = scan_number
            evidence.last_seen_ms = now_ms
            opportunity = best_by_symbol.get(symbol)
            if opportunity is not None:
                edge_bps = opportunity.net_edge * BPS
                evidence.latest_net_edge_bps = edge_bps
                evidence.best_net_edge_bps = max(
                    evidence.best_net_edge_bps,
                    edge_bps,
                )
                evidence.latest_route = (
                    f"{opportunity.buy_venue}->{opportunity.sell_venue}"
                )
            active = self._active_inventory.get(symbol)
            if active is not None and active.state != "pending_liquidation":
                active.last_seen_ms = now_ms
                active.state = "active"

        # Evidence must be consecutive while a symbol remains a viable target.
        # Falling out of the bounded target rank resets its activation streak.
        for symbol, evidence in self._candidate_evidence.items():
            if symbol not in target_set:
                evidence.observations = []
        return tuple(target_symbols)

    def _activation_plan(
        self,
        symbol: str,
        books: Mapping[tuple[str, str], OrderBook],
        settings: ScanSettings,
        *,
        check_budget: bool = True,
    ) -> tuple[_InventoryAllocation, ...]:
        """Build a fully funded configured PAPER buy on every eligible venue."""

        base_asset, quote_asset = split_symbol(symbol)
        if quote_asset != "USDT":
            return ()
        allocations: list[_InventoryAllocation] = []
        for (candidate_symbol, venue), book in sorted(books.items()):
            if candidate_symbol != symbol:
                continue
            quote_available = self._portfolio.balance(venue, quote_asset)
            if check_budget and (
                quote_available - settings.allocation_per_symbol_venue_usdt
                < settings.auto_usdt_reserve_target
            ):
                continue
            fee_rate = self.taker_fees.get(venue, Decimal("0.001"))
            gross_notional = settings.allocation_per_symbol_venue_usdt / (
                Decimal("1") + fee_rate
            )
            quantity = gross_notional / book.best_ask
            # Require both entry and exit BBO to absorb the greater of a full
            # configured allocation or the configurable execution multiple.
            required_bbo_notional = settings.activation_min_bbo_notional_usdt
            if (
                quantity > book.asks[0].quantity
                or book.best_ask * book.asks[0].quantity
                < required_bbo_notional
                or book.best_bid * book.bids[0].quantity
                < required_bbo_notional
            ):
                continue
            fee = gross_notional * fee_rate
            allocations.append(
                _InventoryAllocation(
                    venue=venue,
                    price=book.best_ask,
                    quantity=quantity,
                    gross_notional_usdt=gross_notional,
                    fee_usdt=fee,
                    quote_spent_usdt=gross_notional + fee,
                )
            )
        # Cross-venue execution needs pre-positioned base on at least two
        # venues.  A one-venue plan must not mutate the portfolio.
        return tuple(allocations) if len(allocations) >= 2 else ()

    def _auto_execution_balances(
        self,
        books: Mapping[tuple[str, str], OrderBook],
        settings: ScanSettings,
    ) -> dict[str, dict[str, Decimal]]:
        """Expose cash inside the bounded execution-drift corridor.

        The configured allocations establish the target inventory/cash split.
        One configured trade notional of controlled drift is permitted around
        that target.  Cross-field validation guarantees non-negative limits.
        """

        balances = self._portfolio.snapshot()
        for venue, venue_balances in balances.items():
            usdt = venue_balances.get("USDT", Decimal("0"))
            current_base_value = sum(
                (
                    self._portfolio.balance(venue, active.base_asset)
                    * books[(symbol, venue)].best_ask
                    for symbol, active in self._active_inventory.items()
                    if (symbol, venue) in books
                ),
                Decimal("0"),
            )
            venue_balances["USDT"] = max(
                Decimal("0"),
                min(
                    usdt - settings.auto_execution_usdt_floor,
                    settings.auto_execution_base_cap_usdt - current_base_value,
                ),
            )
        return balances

    def _reconcile_auto_active_limit(self, settings: ScanSettings) -> None:
        """Mark deterministic excess positions for liquidation after a resize.

        Existing allocations keep their original size, but reducing
        ``max_active_symbols`` must not strand extra positions indefinitely.
        The oldest positions are retained and the newest excess positions are
        moved to ``pending_liquidation`` on the next AUTO execution scan.
        """

        ranked = sorted(
            self._active_inventory.values(),
            key=lambda active: (
                active.activated_ms,
                active.activated_scan,
                active.symbol,
            ),
        )
        keep = {active.symbol for active in ranked[: settings.max_active_symbols]}
        for active in ranked:
            if active.symbol not in keep:
                active.state = "pending_liquidation"

    def _auto_active_slots(self, settings: ScanSettings) -> int:
        """Return slots after counting positions that still consume capital."""

        return max(
            0,
            settings.max_active_symbols - len(self._active_inventory),
        )

    def _activate_ready_auto_inventory(
        self,
        books: Mapping[tuple[str, str], OrderBook],
        current_signal_symbols: Sequence[str],
        settings: ScanSettings,
        *,
        scan_number: int,
        now_ms: int,
    ) -> None:
        """Convert PAPER USDT into no more than the configured active assets."""

        slots = self._auto_active_slots(settings)
        if not self._auto_inventory_enabled or slots <= 0:
            return
        ready = [
            evidence
            for symbol, evidence in self._candidate_evidence.items()
            if symbol in current_signal_symbols
            and symbol not in self._active_inventory
            and len(evidence.observations) >= settings.activation_observations
        ]
        target_rank = {
            symbol: index for index, symbol in enumerate(current_signal_symbols)
        }
        ready.sort(
            key=lambda item: (
                target_rank.get(item.symbol, len(target_rank)),
                item.symbol,
            )
        )
        for evidence in ready:
            if slots <= 0:
                break
            allocations = self._activation_plan(evidence.symbol, books, settings)
            if not allocations:
                continue
            base_asset, _quote_asset = split_symbol(evidence.symbol)
            deltas: dict[tuple[str, str], Decimal] = {}
            for allocation in allocations:
                deltas[(allocation.venue, "USDT")] = (
                    deltas.get((allocation.venue, "USDT"), Decimal("0"))
                    - allocation.quote_spent_usdt
                )
                deltas[(allocation.venue, base_asset)] = (
                    deltas.get((allocation.venue, base_asset), Decimal("0"))
                    + allocation.quantity
                )
            proposed = self._portfolio._propose(deltas)
            self._portfolio._commit(proposed)
            for allocation in allocations:
                self._inventory_journal.append(
                    _InventoryJournalEntry(
                        timestamp_ms=now_ms,
                        event="inventory_activation",
                        symbol=evidence.symbol,
                        venue=allocation.venue,
                        side="buy",
                        quantity=allocation.quantity,
                        price=allocation.price,
                        gross_notional_usdt=allocation.gross_notional_usdt,
                        fee_usdt=allocation.fee_usdt,
                        cash_flow_usdt=-allocation.quote_spent_usdt,
                    )
                )
            self._active_inventory[evidence.symbol] = _ActiveInventory(
                symbol=evidence.symbol,
                base_asset=base_asset,
                activated_scan=scan_number,
                activated_ms=now_ms,
                last_seen_ms=now_ms,
                evidence_observations=len(evidence.observations),
                target_per_venue_usdt=(
                    settings.allocation_per_symbol_venue_usdt
                ),
                allocations=allocations,
            )
            slots -= 1

    def _liquidate_expired_auto_inventory(
        self,
        books: Mapping[tuple[str, str], OrderBook],
        settings: ScanSettings,
        *,
        now_ms: int,
    ) -> None:
        """Return inactive PAPER assets to USDT at executable public BBO."""

        if not self._auto_inventory_enabled:
            return
        for symbol, active in tuple(self._active_inventory.items()):
            if (
                active.state != "pending_liquidation"
                and now_ms - active.last_seen_ms
                <= settings.inventory_idle_timeout_ms
            ):
                continue
            active.state = "pending_liquidation"
            deltas: dict[tuple[str, str], Decimal] = {}
            for venue in sorted(self._portfolio.snapshot()):
                quantity = self._portfolio.balance(venue, active.base_asset)
                book = books.get((symbol, venue))
                if quantity <= 0 or book is None:
                    continue
                liquidation_key = (
                    symbol,
                    venue,
                    self._book_identity(book),
                )
                if liquidation_key in self._consumed_liquidation_snapshots:
                    continue
                executable_quantity = min(quantity, book.bids[0].quantity)
                if executable_quantity <= 0:
                    continue
                gross_credit = executable_quantity * book.best_bid
                fee_rate = self.taker_fees.get(venue, Decimal("0.001"))
                net_credit = gross_credit * (Decimal("1") - fee_rate)
                deltas[(venue, active.base_asset)] = -executable_quantity
                deltas[(venue, "USDT")] = net_credit
                self._consumed_liquidation_snapshots.add(liquidation_key)
                self._inventory_journal.append(
                    _InventoryJournalEntry(
                        timestamp_ms=now_ms,
                        event="inventory_liquidation",
                        symbol=symbol,
                        venue=venue,
                        side="sell",
                        quantity=executable_quantity,
                        price=book.best_bid,
                        gross_notional_usdt=gross_credit,
                        fee_usdt=gross_credit * fee_rate,
                        cash_flow_usdt=net_credit,
                    )
                )
            if deltas:
                proposed = self._portfolio._propose(deltas)
                self._portfolio._commit(proposed)
            remaining = sum(
                (
                    self._portfolio.balance(venue, active.base_asset)
                    for venue in self._portfolio.snapshot()
                ),
                Decimal("0"),
            )
            if remaining == 0:
                del self._active_inventory[symbol]

    async def _collect_manual_books(
        self,
        settings: ScanSettings,
        now_ms: int | None = None,
    ) -> dict[tuple[str, str], OrderBook]:
        results = await asyncio.gather(
            *(self._fetch_book(adapter, settings.symbol) for adapter in self.adapters)
        )
        # Freshness is measured against request completion.  Receipt-stamped
        # books (notably Binance) are otherwise inevitably newer than a clock
        # sampled before the HTTP request began.
        now_ms = self.clock_ms()
        books: dict[tuple[str, str], OrderBook] = {}
        for venue, book, latency_ms, error in results:
            if error is not None:
                message = f"{type(error).__name__}: {error}"
                self._errors[venue] = message
                self._venue_state[venue] = {
                    "name": venue,
                    "ok": False,
                    "status": "error",
                    "latency_ms": latency_ms,
                    "timestamp_ms": None,
                    "book_age_ms": None,
                    "ticker_count": 0,
                    "selected_ticker_count": 0,
                    "error": message,
                }
                continue
            assert book is not None
            age_ms = max(0, now_ms - book.timestamp_ms)
            fresh = age_ms <= self.max_staleness_ms
            if fresh:
                books[(book.symbol, venue)] = book
            else:
                self._errors[venue] = (
                    f"stale order book: age {age_ms} ms exceeds "
                    f"{self.max_staleness_ms} ms"
                )
            self._venue_state[venue] = {
                "name": venue,
                "ok": fresh,
                "status": "online" if fresh else "stale",
                "latency_ms": latency_ms,
                "timestamp_ms": book.timestamp_ms,
                "book_age_ms": age_ms,
                "ticker_count": 1,
                "selected_ticker_count": 1 if fresh else 0,
                "error": None if fresh else self._errors[venue],
            }
        self._universe = []
        self._tradable_book_keys = set(books)
        return books

    async def _collect_auto_books(
        self,
        settings: ScanSettings,
        now_ms: int | None = None,
    ) -> dict[tuple[str, str], OrderBook]:
        # Gate needs a bounded wave of real order books after its metadata
        # request. Acquire it first, then take the lightweight all-ticker
        # snapshots from the other venues so cross-venue receipt times remain
        # close enough to represent the same REST observation window.
        gate_adapters = tuple(
            adapter for adapter in self.adapters
            if adapter.venue.lower() == "gate"
        )
        other_adapters = tuple(
            adapter for adapter in self.adapters
            if adapter.venue.lower() != "gate"
        )
        gate_results = await asyncio.gather(
            *(self._fetch_tickers(adapter) for adapter in gate_adapters)
        )
        other_results = await asyncio.gather(
            *(self._fetch_tickers(adapter) for adapter in other_adapters)
        )
        results = (*gate_results, *other_results)
        now_ms = self.clock_ms()
        latest_completion_ns = max(
            (completed_ns for *_head, completed_ns, _error in results),
            default=time.perf_counter_ns(),
        )
        fresh_by_venue: dict[str, tuple[MarketTicker, ...]] = {}
        latencies: dict[str, int] = {}
        raw_counts: dict[str, int] = {}
        for venue, tickers, latency_ms, completed_ns, error in results:
            latencies[venue] = latency_ms
            if error is not None:
                message = f"{type(error).__name__}: {error}"
                self._errors[venue] = message
                self._venue_state[venue] = {
                    "name": venue,
                    "ok": False,
                    "status": "error",
                    "latency_ms": latency_ms,
                    "timestamp_ms": None,
                    "book_age_ms": None,
                    "ticker_count": 0,
                    "selected_ticker_count": 0,
                    "error": message,
                }
                continue
            assert tickers is not None
            receipt_ms = now_ms - max(
                0,
                (latest_completion_ns - completed_ns) // 1_000_000,
            )
            raw_counts[venue] = len(tickers)
            fresh = tuple(
                replace(ticker, timestamp_ms=receipt_ms)
                for ticker in tickers
                if 0
                <= receipt_ms - ticker.timestamp_ms
                <= self.max_staleness_ms
            )
            fresh_by_venue[venue] = fresh
            stale_count = len(tickers) - len(fresh)
            if stale_count:
                self._errors[f"{venue}_stale"] = (
                    f"excluded {stale_count} stale ticker(s) older than "
                    f"{self.max_staleness_ms} ms"
                )

        self._universe = select_cross_venue_universe(
            fresh_by_venue,
            max_symbols=settings.max_symbols,
            liquidity_pool_size=AUTO_LIQUIDITY_POOL_SIZE,
            quote_asset="USDT",
            min_venues=2,
            min_liquidity_usdt=settings.min_24h_volume_usdt,
        )
        selected_venues = {
            item.symbol: set(item.venues) for item in self._universe
        }
        books: dict[tuple[str, str], OrderBook] = {}
        tradable_book_keys: set[tuple[str, str]] = set()
        for venue, tickers in fresh_by_venue.items():
            selected = tuple(
                ticker
                for ticker in tickers
                if venue in selected_venues.get(ticker.symbol, set())
                or ticker.symbol in self._active_inventory
            )
            for ticker in selected:
                key = (ticker.symbol, venue)
                books[key] = self._ticker_book(ticker)
                if venue in selected_venues.get(ticker.symbol, set()):
                    tradable_book_keys.add(key)
            newest = max((ticker.timestamp_ms for ticker in selected), default=None)
            oldest = min((ticker.timestamp_ms for ticker in selected), default=None)
            age_ms = None if oldest is None else max(0, now_ms - oldest)
            ok = bool(selected)
            self._venue_state[venue] = {
                "name": venue,
                "ok": ok,
                "status": "online" if ok else "no_common_symbols",
                "latency_ms": latencies[venue],
                "timestamp_ms": newest,
                "book_age_ms": age_ms,
                "ticker_count": raw_counts[venue],
                "selected_ticker_count": len(selected),
                "error": None if ok else "no selected common fresh USDT symbols",
            }
        self._tradable_book_keys = tradable_book_keys
        return books

    async def scan(
        self,
        settings: ScanSettings | None = None,
        *,
        run_generation: int | None = None,
    ) -> dict[str, Any]:
        """Run one complete public-data round and optionally paper-execute it."""

        selected = settings or self._settings
        if not isinstance(selected, ScanSettings):
            raise TypeError("settings must be ScanSettings")

        async with self._scan_lock:
            if self._running and run_generation is None:
                raise RuntimeError(
                    "one-shot scan is unavailable while the paper monitor is running"
                )
            self._apply_initial_balance_setting(selected)
            self._settings = selected
            self._scanning = True
            self._errors = {}
            try:
                books = (
                    await self._collect_auto_books(selected)
                    if selected.symbol == AUTO_SYMBOL
                    else await self._collect_manual_books(selected)
                )
                # Use one post-fetch timestamp for engine freshness, evidence,
                # journal entries and status.  Collection already measured
                # each ticker against a completion-time clock sample.
                now_ms = self.clock_ms()
                # A concurrent stop invalidates a start/monitor round.  It may
                # finish public reads, but it must not mutate paper balances,
                # opportunities, journal, or scan counters afterward.
                if (
                    run_generation is not None
                    and run_generation != self._run_generation
                ):
                    return self.status()
                self._books = books
                tradable_books = {
                    key: book
                    for key, book in books.items()
                    if key in self._tradable_book_keys
                }
                symbols = sorted({symbol for symbol, _venue in tradable_books})
                engine_config = self._config(selected, symbols)
                engine = ArbitrageEngine(engine_config)
                self._pair_assessments = []
                self._last_execution_candidate_count = 0
                self._last_execution_candidate_keys = set()
                self._last_executed_count = 0
                self._current_executable_opportunity = None
                self._execution_blockers = []
                if selected.symbol == AUTO_SYMBOL:
                    self._pair_assessments = assess_pairs(
                        tradable_books.values(),
                        taker_fees=engine_config.taker_fees,
                        default_taker_fee=engine_config.default_taker_fee,
                        risk_buffer=engine_config.risk_buffer,
                        min_net_edge=engine_config.min_net_edge,
                        max_notional=engine_config.max_notional,
                        min_notional=Decimal("10"),
                        max_pair_skew_ms=self.max_pair_skew_ms,
                    )
                else:
                    self._last_profitable_signal = None

                def within_pair_skew(
                    raw: Sequence[ArbitrageOpportunity],
                ) -> list[ArbitrageOpportunity]:
                    return [
                        opportunity
                        for opportunity in raw
                        if abs(
                            opportunity.buy_timestamp_ms
                            - opportunity.sell_timestamp_ms
                        )
                        <= self.max_pair_skew_ms
                    ]

                scan_number = self._scan_count + 1
                execution_candidates: list[ArbitrageOpportunity]
                if selected.symbol == AUTO_SYMBOL and self._auto_inventory_enabled:
                    # Strict discovery remains useful for execution and the UI,
                    # but inventory evidence follows fresh, viable ranked
                    # universe observations independently of profitability.
                    raw_discovery = engine.scan(
                        tradable_books.values(),
                        now_ms=now_ms,
                        balances=None,
                    )
                    discovery = within_pair_skew(raw_discovery)
                    self._record_route_profit_evidence(
                        discovery,
                        tradable_books,
                        selected,
                        now_ms=now_ms,
                    )
                    current_signal_symbols = self._record_auto_candidate_evidence(
                        tradable_books,
                        selected,
                        scan_number=scan_number,
                        now_ms=now_ms,
                        profitable_opportunities=discovery,
                    )
                    if selected.auto_execute:
                        self._reconcile_auto_active_limit(selected)
                        self._liquidate_expired_auto_inventory(
                            books,
                            selected,
                            now_ms=now_ms,
                        )
                        self._activate_ready_auto_inventory(
                            tradable_books,
                            current_signal_symbols,
                            selected,
                            scan_number=scan_number,
                            now_ms=now_ms,
                        )
                    rebalance_attempts = self._attempt_safe_auto_rebalance(
                        discovery,
                        tradable_books,
                        selected,
                        now_ms=now_ms,
                    )
                    raw_affordable = engine.scan(
                        tradable_books.values(),
                        now_ms=now_ms,
                        balances=self._auto_execution_balances(books, selected),
                    )
                    execution_candidates = [
                        opportunity
                        for opportunity in within_pair_skew(raw_affordable)
                        if (
                            opportunity.symbol in self._active_inventory
                            and self._active_inventory[opportunity.symbol].state
                            == "active"
                        )
                    ]
                    # Opportunities remain strict net-profitable routes; there
                    # may be active pre-positioned inventory with no route yet.
                    self._opportunities = discovery
                    raw_opportunities = raw_discovery
                else:
                    rebalance_attempts = {}
                    raw_opportunities = engine.scan(
                        books.values(),
                        now_ms=now_ms,
                        balances=self._portfolio,
                    )
                    execution_candidates = within_pair_skew(raw_opportunities)
                    self._opportunities = execution_candidates

                if selected.symbol == AUTO_SYMBOL:
                    self._last_execution_candidate_count = len(
                        execution_candidates
                    )
                    self._last_execution_candidate_keys = {
                        (
                            opportunity.symbol,
                            opportunity.buy_venue,
                            opportunity.sell_venue,
                        )
                        for opportunity in execution_candidates
                    }
                    if self._opportunities:
                        self._last_profitable_signal = (
                            self._opportunities[0],
                            now_ms,
                        )
                    self._current_executable_opportunity = next(
                        (
                            opportunity
                            for opportunity in execution_candidates
                            if self._opportunity_snapshot_key(
                                opportunity,
                                tradable_books,
                            )
                            not in (
                                self._executed_snapshot_pairs
                                | self._consumed_rebalance_snapshot_pairs
                            )
                        ),
                        None,
                    )
                    self._execution_blockers = self._build_execution_blockers(
                        self._opportunities,
                        execution_candidates,
                        tradable_books,
                        selected,
                        rebalance_attempts,
                    )
                else:
                    self._current_executable_opportunity = (
                        execution_candidates[0] if execution_candidates else None
                    )

                skewed_count = len(raw_opportunities) - len(
                    within_pair_skew(raw_opportunities)
                )
                if skewed_count:
                    self._errors["market_data_skew"] = (
                        f"excluded {skewed_count} opportunity(s): venue snapshots "
                        f"differ by more than {self.max_pair_skew_ms} ms"
                    )

                trade_count_before = len(self._executor.journal)
                if selected.auto_execute and execution_candidates:
                    best = next(
                        (
                            opportunity
                            for opportunity in execution_candidates
                            if self._opportunity_snapshot_key(opportunity, books)
                            not in (
                                self._executed_snapshot_pairs
                                | self._consumed_rebalance_snapshot_pairs
                            )
                        ),
                        None,
                    )
                    if best is None:
                        self._errors["duplicate_snapshot"] = (
                            "paper execution skipped: every profitable route "
                            "uses an already executed snapshot pair"
                        )
                    else:
                        snapshot_key = self._opportunity_snapshot_key(best, books)
                    try:
                        if best is not None:
                            self._executor.execute(
                                best,
                                books[(best.symbol, best.buy_venue)],
                                books[(best.symbol, best.sell_venue)],
                                timestamp_ms=now_ms,
                            )
                            self._execution_opportunities.append(best)
                            self._executed_snapshot_pairs.add(snapshot_key)
                    except Exception as exc:
                        self._errors["paper_execution"] = (
                            f"{type(exc).__name__}: {exc}"
                        )

                self._last_executed_count = (
                    len(self._executor.journal) - trade_count_before
                )
                if selected.symbol == AUTO_SYMBOL:
                    remaining_candidates = [
                        opportunity
                        for opportunity in execution_candidates
                        if self._opportunity_snapshot_key(opportunity, books)
                        not in (
                            self._executed_snapshot_pairs
                            | self._consumed_rebalance_snapshot_pairs
                        )
                    ]
                    self._current_executable_opportunity = (
                        remaining_candidates[0]
                        if remaining_candidates
                        else None
                    )
                    self._last_execution_candidate_count = len(
                        remaining_candidates
                    )
                    self._execution_blockers = self._build_execution_blockers(
                        self._opportunities,
                        remaining_candidates,
                        tradable_books,
                        selected,
                        rebalance_attempts,
                    )

                self._scan_count += 1
                self._last_scan_ms = now_ms
            finally:
                self._scanning = False
        return self.status()

    async def start(self, settings: ScanSettings) -> dict[str, Any]:
        """Start a recurring monitor after completing an immediate first scan."""

        async with self._lifecycle_lock:
            if self._running:
                raise RuntimeError("paper monitor is already running")
            self._run_generation += 1
            generation = self._run_generation
            self._running = True
        try:
            await self.scan(settings, run_generation=generation)
        except BaseException:
            async with self._lifecycle_lock:
                if generation == self._run_generation:
                    self._running = False
            raise
        async with self._lifecycle_lock:
            if generation != self._run_generation or not self._running:
                return self.status()
            self._monitor_task = asyncio.create_task(
                self._monitor_loop(generation), name="arbitrage-paper-monitor"
            )
            return self.status()

    async def _monitor_loop(self, generation: int) -> None:
        try:
            while self._running and generation == self._run_generation:
                await asyncio.sleep(self._settings.interval_ms / 1000)
                if self._running and generation == self._run_generation:
                    await self.scan(
                        self._settings,
                        run_generation=generation,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._errors["monitor"] = f"{type(exc).__name__}: {exc}"
        finally:
            if generation == self._run_generation:
                self._running = False

    async def _stop_unlocked(self) -> dict[str, Any]:
        self._running = False
        self._run_generation += 1
        task, self._monitor_task = self._monitor_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        return self.status()

    async def stop(self) -> dict[str, Any]:
        async with self._lifecycle_lock:
            return await self._stop_unlocked()

    async def reset(
        self,
        initial_balance_per_venue_usdt: Decimal | str | int | float | None = None,
    ) -> dict[str, Any]:
        """Stop the monitor and restore the entire deterministic paper state."""

        reset_settings = self._settings
        reset_balance = self._initial_balance_per_venue_usdt
        if initial_balance_per_venue_usdt is not None:
            if not self._auto_inventory_enabled:
                raise RuntimeError(
                    "custom seeded portfolios cannot be replaced by AUTO reset"
                )
            reset_balance = decimal_value(
                initial_balance_per_venue_usdt,
                name="initial_balance_per_venue_usdt",
            )
            reset_settings = replace(
                self._settings,
                initial_balance_per_venue_usdt=reset_balance,
            )

        async with self._lifecycle_lock:
            await self._stop_unlocked()
            async with self._scan_lock:
                if self._auto_inventory_enabled:
                    self._initial_balance_per_venue_usdt = reset_balance
                    self._initial_balances = {
                        adapter.venue.lower(): {"USDT": reset_balance}
                        for adapter in self.adapters
                    }
                self._settings = reset_settings
                self._portfolio = PaperPortfolio(self._initial_balances)
                self._executor = PaperArbitrageExecutor(
                    self._portfolio, self.taker_fees
                )
                self._execution_opportunities = []
                self._executed_snapshot_pairs = set()
                self._books = {}
                self._tradable_book_keys = set()
                self._universe = []
                self._candidate_evidence = {}
                self._route_profit_evidence = {}
                self._active_inventory = {}
                self._inventory_journal = []
                self._rebalance_journal = []
                self._consumed_rebalance_snapshot_pairs = set()
                self._consumed_rebalance_profit_evidence = set()
                self._consumed_liquidation_snapshots = set()
                self._opportunities = []
                self._pair_assessments = []
                self._last_profitable_signal = None
                self._last_execution_candidate_count = 0
                self._last_execution_candidate_keys = set()
                self._last_executed_count = 0
                self._current_executable_opportunity = None
                self._execution_blockers = []
                self._last_scan_ms = None
                self._scan_count = 0
                self._errors = {}
                self._venue_state = {
                    venue: {
                        "name": venue,
                        "ok": False,
                        "status": "idle",
                        "latency_ms": None,
                        "timestamp_ms": None,
                        "book_age_ms": None,
                        "ticker_count": 0,
                        "selected_ticker_count": 0,
                        "error": None,
                    }
                    for venue in self._venue_state
                }
            return self.status()

    async def close(self) -> None:
        await self.stop()
        await asyncio.gather(
            *(adapter.aclose() for adapter in self.adapters),
            return_exceptions=True,
        )

    @staticmethod
    def _opportunity_dict(opportunity: ArbitrageOpportunity) -> dict[str, Any]:
        result = opportunity.to_dict()
        result.update(
            {
                "gross_edge_bps": decimal_string(opportunity.gross_edge * BPS),
                "net_edge_bps": decimal_string(opportunity.net_edge * BPS),
                "notional_usdt": decimal_string(opportunity.buy_notional),
                "expected_pnl_usdt": decimal_string(opportunity.net_profit),
                "executable_buy_price": decimal_string(opportunity.buy_vwap),
                "executable_sell_price": decimal_string(opportunity.sell_vwap),
            }
        )
        return result

    def _journal(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for execution, opportunity in zip(
            self._executor.journal, self._execution_opportunities, strict=True
        ):
            row = execution.to_dict()
            row.update(
                {
                    "timestamp": execution.timestamp_ms,
                    "buy_venue": execution.buy_leg.venue,
                    "sell_venue": execution.sell_leg.venue,
                    "quantity": decimal_string(execution.buy_leg.quantity),
                    "notional_usdt": decimal_string(execution.buy_leg.notional),
                    "net_edge_bps": decimal_string(opportunity.net_edge * BPS),
                    "pnl_usdt": decimal_string(execution.realized_pnl),
                    "status": "paper_filled",
                }
            )
            rows.append(row)
        return rows

    def _candidate_evidence_status(self) -> list[dict[str, Any]]:
        rows = [
            {
                "symbol": evidence.symbol,
                "qualifying_observations": len(evidence.observations),
                "required_observations": self._settings.activation_observations,
                "window_ms": self._settings.evidence_window_ms,
                "last_seen_scan": evidence.last_seen_scan,
                "last_seen_ms": evidence.last_seen_ms,
                "latest_route": evidence.latest_route,
                "latest_net_edge_bps": decimal_string(
                    evidence.latest_net_edge_bps
                ),
                "best_net_edge_bps": decimal_string(evidence.best_net_edge_bps),
                "ready": len(evidence.observations)
                >= self._settings.activation_observations,
                "active": evidence.symbol in self._active_inventory,
                "observation_timestamps_ms": [
                    timestamp_ms
                    for timestamp_ms, _snapshot_key in evidence.observations
                ],
            }
            for evidence in self._candidate_evidence.values()
        ]
        return sorted(
            rows,
            key=lambda item: (
                not item["active"],
                -item["qualifying_observations"],
                -Decimal(item["latest_net_edge_bps"]),
                item["symbol"],
            ),
        )

    def _active_inventory_status(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for active in self._active_inventory.values():
            allocations = [
                {
                    "venue": allocation.venue,
                    "price": decimal_string(allocation.price),
                    "quantity": decimal_string(allocation.quantity),
                    "gross_notional_usdt": decimal_string(
                        allocation.gross_notional_usdt
                    ),
                    "fee_usdt": decimal_string(allocation.fee_usdt),
                    "quote_spent_usdt": decimal_string(
                        allocation.quote_spent_usdt
                    ),
                    "current_base_quantity": decimal_string(
                        self._portfolio.balance(
                            allocation.venue,
                            active.base_asset,
                        )
                    ),
                }
                for allocation in active.allocations
            ]
            rows.append(
                {
                    "symbol": active.symbol,
                    "base_asset": active.base_asset,
                    "state": active.state,
                    "activated_scan": active.activated_scan,
                    "activated_ms": active.activated_ms,
                    "last_seen_ms": active.last_seen_ms,
                    # Backward-compatible alias for older dashboard builds.
                    "last_signal_ms": active.last_seen_ms,
                    "evidence_observations": active.evidence_observations,
                    "target_per_venue_usdt": decimal_string(
                        active.target_per_venue_usdt
                    ),
                    "total_quote_spent_usdt": decimal_string(
                        sum(
                            (
                                allocation.quote_spent_usdt
                                for allocation in active.allocations
                            ),
                            Decimal("0"),
                        )
                    ),
                    "allocations": allocations,
                }
            )
        return sorted(rows, key=lambda item: item["symbol"])

    def _inventory_journal_status(self) -> list[dict[str, Any]]:
        return [
            {
                "timestamp_ms": entry.timestamp_ms,
                "event": entry.event,
                "symbol": entry.symbol,
                "venue": entry.venue,
                "side": entry.side,
                "quantity": decimal_string(entry.quantity),
                "price": decimal_string(entry.price),
                "gross_notional_usdt": decimal_string(
                    entry.gross_notional_usdt
                ),
                "fee_usdt": decimal_string(entry.fee_usdt),
                "cash_flow_usdt": decimal_string(entry.cash_flow_usdt),
            }
            for entry in self._inventory_journal
        ]

    def _rebalance_journal_status(self) -> list[dict[str, Any]]:
        return [
            {
                "timestamp_ms": entry.timestamp_ms,
                "event": "inventory_rebalance",
                "status": "paper_rebalanced",
                "symbol": entry.symbol,
                "route": f"{entry.buy_venue}->{entry.sell_venue}",
                "buy_venue": entry.buy_venue,
                "sell_venue": entry.sell_venue,
                "base_asset": entry.base_asset,
                "quantity": decimal_string(entry.quantity),
                "source_sell_price": decimal_string(
                    entry.source_sell_price
                ),
                "destination_buy_price": decimal_string(
                    entry.destination_buy_price
                ),
                "source_sale_notional_usdt": decimal_string(
                    entry.source_sale_notional_usdt
                ),
                "destination_buy_notional_usdt": decimal_string(
                    entry.destination_buy_notional_usdt
                ),
                "source_sell_fee_usdt": decimal_string(
                    entry.source_sell_fee_usdt
                ),
                "destination_buy_fee_usdt": decimal_string(
                    entry.destination_buy_fee_usdt
                ),
                "future_exit_fee_estimate_usdt": decimal_string(
                    entry.future_exit_fee_estimate_usdt
                ),
                "quote_outflow_usdt": decimal_string(
                    entry.quote_outflow_usdt
                ),
                "setup_cost_usdt": decimal_string(entry.setup_cost_usdt),
                "projected_route_profit_usdt": decimal_string(
                    entry.projected_route_profit_usdt
                ),
                "required_projected_profit_usdt": decimal_string(
                    entry.required_projected_profit_usdt
                ),
                "safety_multiple": decimal_string(entry.safety_multiple),
                "evidence_count": entry.evidence_count,
                "source_cash_flow_usdt": decimal_string(
                    entry.source_cash_flow_usdt
                ),
                "destination_cash_flow_usdt": decimal_string(
                    entry.destination_cash_flow_usdt
                ),
            }
            for entry in self._rebalance_journal
        ]

    def _route_profit_evidence_status(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for evidence in self._route_profit_evidence.values():
            usable = [
                item
                for item in evidence.observations
                if item[1] not in self._consumed_rebalance_profit_evidence
            ]
            rows.append(
                {
                    "symbol": evidence.symbol,
                    "route": f"{evidence.buy_venue}->{evidence.sell_venue}",
                    "buy_venue": evidence.buy_venue,
                    "sell_venue": evidence.sell_venue,
                    "unique_observations": len(evidence.observations),
                    "available_observations": len(usable),
                    "available_projected_profit_usdt": decimal_string(
                        sum((item[2] for item in usable), Decimal("0"))
                    ),
                    "window_ms": self._settings.evidence_window_ms,
                }
            )
        return sorted(
            rows,
            key=lambda item: (
                -Decimal(item["available_projected_profit_usdt"]),
                item["symbol"],
                item["route"],
            ),
        )

    def _paper_equity_usdt(self) -> Decimal | None:
        """Mark current virtual assets to the conservative executable bid."""

        total = Decimal("0")
        for venue, balances in self._portfolio.snapshot().items():
            total += balances.get("USDT", Decimal("0"))
            for asset, quantity in balances.items():
                if asset == "USDT" or quantity <= 0:
                    continue
                book = self._books.get((f"{asset}USDT", venue))
                if book is None:
                    return None
                fee_rate = self.taker_fees.get(venue, Decimal("0.001"))
                total += quantity * book.best_bid * (
                    Decimal("1") - fee_rate
                )
        return total

    def _diagnostics_status(self) -> dict[str, Any]:
        """Explain the current AUTO scan without weakening execution gates."""

        aggregate = aggregate_assessments(self._pair_assessments)
        market_valid = [
            assessment
            for assessment in self._pair_assessments
            if "pair_skew" not in assessment.reasons
            and "insufficient_depth" not in assessment.reasons
        ]
        gross_positive = sum(
            1 for assessment in market_valid if assessment.gross_edge > 0
        )
        net_positive = sum(
            1 for assessment in market_valid if assessment.net_edge > 0
        )
        inventory_ready = 0
        for assessment in self._pair_assessments:
            if not assessment.eligible:
                continue
            active = self._active_inventory.get(assessment.symbol)
            if active is None or active.state != "active":
                continue
            # The sale venue needs enough pre-positioned base to clear the
            # same AUTO minimum notional used by the execution engine.  An
            # active symbol on other venues is not route-ready inventory.
            sell_base = self._portfolio.balance(
                assessment.sell_venue,
                active.base_asset,
            )
            if sell_base * assessment.buy_price >= Decimal("10"):
                inventory_ready += 1
        activation_depth_qualified = sum(
            1
            for stats in self._universe
            if self._activation_plan(
                stats.symbol,
                self._books,
                self._settings,
                check_budget=False,
            )
        )
        funnel = {
            "symbols": len(self._universe),
            "activation_depth_qualified": activation_depth_qualified,
            "routes": aggregate["total_pairs"],
            "gross_positive": gross_positive,
            "net_positive": net_positive,
            "qualifying": aggregate["eligible_pairs"],
            "inventory_ready": inventory_ready,
            "executable": self._last_execution_candidate_count,
            "executed": self._last_executed_count,
        }
        rejection_counts = dict(aggregate["reason_counts"])
        activation_depth_blocked = max(
            0,
            len(self._universe) - activation_depth_qualified,
        )
        if activation_depth_blocked:
            rejection_counts["insufficient_activation_depth"] = (
                activation_depth_blocked
            )
        missing_inventory = max(
            0,
            aggregate["eligible_pairs"] - inventory_ready,
        )
        if missing_inventory:
            rejection_counts["missing_inventory"] = missing_inventory
        activation_pending = sum(
            1
            for evidence in self._candidate_evidence.values()
            if evidence.last_seen_scan == self._scan_count
            and len(evidence.observations)
            < self._settings.activation_observations
        )
        if activation_pending:
            rejection_counts["activation_pending"] = activation_pending
        balance_blocked = max(
            0,
            inventory_ready - self._last_execution_candidate_count,
        )
        if balance_blocked:
            rejection_counts["balance_corridor"] = balance_blocked
        if self._last_execution_candidate_count and not self._settings.auto_execute:
            rejection_counts["auto_execute_disabled"] = (
                self._last_execution_candidate_count
            )
        if "duplicate_snapshot" in self._errors:
            rejection_counts["duplicate_snapshot"] = (
                self._last_execution_candidate_count
            )
        for blocker in self._execution_blockers:
            code = str(blocker.get("code", "execution_blocked"))
            rejection_counts[code] = rejection_counts.get(code, 0) + 1
        return {
            "funnel": funnel,
            "rejection_counts": rejection_counts,
            "primary_rejections": aggregate["primary_rejections"],
            "evaluated_pair_count": aggregate["total_pairs"],
        }

    def _last_profitable_signal_status(self) -> dict[str, Any] | None:
        if self._last_profitable_signal is None:
            return None
        opportunity, observed_at_ms = self._last_profitable_signal
        result = self._opportunity_dict(opportunity)
        result["observed_at_ms"] = observed_at_ms
        return result

    def status(self) -> dict[str, Any]:
        opportunities = [self._opportunity_dict(item) for item in self._opportunities]
        rejected_assessments = [
            assessment
            for assessment in self._pair_assessments
            if not assessment.eligible
        ]
        best_near_miss = (
            rejected_assessments[0].to_dict()
            if rejected_assessments
            else None
        )
        diagnostics = self._diagnostics_status()
        journal = self._journal()
        expected_pnl = sum(
            (entry.expected_net_profit for entry in self._executor.journal),
            Decimal("0"),
        )
        winning = sum(1 for entry in self._executor.journal if entry.realized_pnl > 0)
        if self._auto_inventory_enabled:
            initial_equity = self._initial_balance_per_venue_usdt * Decimal(
                len(self._initial_balances)
            )
            strategy_equity: Decimal | None = self._paper_equity_usdt()
            strategy_pnl: Decimal | None = (
                None
                if strategy_equity is None
                else strategy_equity - initial_equity
            )
        else:
            # Custom/manual scenarios may seed base assets at an unknown cost
            # basis.  Reporting mark-to-bid minus only USDT would manufacture
            # a fake profit, so the all-portfolio metric is unavailable.
            strategy_equity = None
            strategy_pnl = None
        inventory_and_rebalance_pnl = (
            None
            if strategy_pnl is None
            else strategy_pnl - self._executor.realized_pnl
        )
        rebalance_cost = sum(
            (entry.setup_cost_usdt for entry in self._rebalance_journal),
            Decimal("0"),
        )
        return {
            "mode": "paper",
            "public_data_only": True,
            "live_trading_enabled": False,
            "running": self._running,
            "scanning": self._scanning,
            "last_scan_ms": self._last_scan_ms,
            "symbol": self._settings.symbol,
            "settings": self._settings.to_dict(),
            "selection_mode": (
                "volatile_liquid_common_usdt"
                if self._settings.symbol == AUTO_SYMBOL
                else "manual_symbol"
            ),
            "universe": [item.to_dict() for item in self._universe],
            "candidate_evidence": self._candidate_evidence_status(),
            "active_symbols": sorted(self._active_inventory),
            "active_inventory": self._active_inventory_status(),
            "inventory_journal": self._inventory_journal_status(),
            "rebalance_journal": self._rebalance_journal_status(),
            "route_profit_evidence": self._route_profit_evidence_status(),
            "fee_source": "configured_assumptions",
            "market_data_policy": {
                "max_staleness_ms": self.max_staleness_ms,
                "max_pair_skew_ms": self.max_pair_skew_ms,
                "depth": 1 if self._settings.symbol == AUTO_SYMBOL else self.depth,
                "auto_source": (
                    "one_public_all_tickers_request_per_venue; Gate uses one "
                    "metadata snapshot plus up to 20 real public order books"
                ),
                "auto_quote_asset": "USDT",
                "auto_liquidity_pool_size": AUTO_LIQUIDITY_POOL_SIZE,
                "auto_min_liquidity_usdt": decimal_string(
                    self._settings.min_24h_volume_usdt
                ),
                "auto_min_24h_volume_usdt": decimal_string(
                    self._settings.min_24h_volume_usdt
                ),
                "auto_max_symbols": DEFAULT_MAX_SYMBOLS,
                "auto_duplicate_snapshot_window_ms": 60_000,
                "auto_ranking": (
                    "top qualifying-venue liquidity pool, then median "
                    "absolute 24h price change across venues"
                ),
                "auto_paper_inventory": (
                    "balance-conserving USDT-to-base PAPER pre-positioning "
                    "after consecutive fresh observations; current strict "
                    "profitable routes receive priority within the viable "
                    "liquid/volatile universe, then deterministic rank fills "
                    "remaining slots; activation itself does not require a "
                    "profitable route"
                ),
                "auto_initial_usdt_per_venue": decimal_string(
                    self._initial_balance_per_venue_usdt
                ),
                "auto_initial_balance_per_venue_usdt": decimal_string(
                    self._initial_balance_per_venue_usdt
                ),
                "auto_max_active_symbols": self._settings.max_active_symbols,
                "auto_activation_observations": (
                    self._settings.activation_observations
                ),
                "auto_evidence_window_ms": self._settings.evidence_window_ms,
                "auto_inventory_idle_timeout_ms": (
                    self._settings.inventory_idle_timeout_ms
                ),
                "auto_allocation_per_symbol_venue_usdt": decimal_string(
                    self._settings.allocation_per_symbol_venue_usdt
                ),
                "auto_base_target_per_venue_usdt": decimal_string(
                    self._settings.auto_base_target_usdt
                ),
                "auto_usdt_reserve_target_per_venue": decimal_string(
                    self._settings.auto_usdt_reserve_target
                ),
                "auto_execution_base_cap_per_venue_usdt": decimal_string(
                    self._settings.auto_execution_base_cap_usdt
                ),
                "auto_execution_usdt_floor_per_venue": decimal_string(
                    self._settings.auto_execution_usdt_floor
                ),
                "auto_max_trade_usdt": decimal_string(self._settings.notional),
                "auto_activation_min_bbo_notional_usdt": decimal_string(
                    self._settings.activation_min_bbo_notional_usdt
                ),
                "auto_bbo_depth_multiplier": decimal_string(
                    self._settings.bbo_depth_multiplier
                ),
                "auto_rebalance": (
                    "atomic PAPER sell of excess base on the accumulated buy "
                    "exchange plus equal-quantity PAPER buy on the depleted "
                    "sell exchange; no transfer and no fabricated inventory"
                ),
                "auto_rebalance_safety_multiple": decimal_string(
                    self._settings.rebalance_safety_multiple
                ),
                "auto_rebalance_profit_evidence_window_ms": (
                    self._settings.evidence_window_ms
                ),
                "auto_expiry": (
                    "sell base at executable bid after the configured inventory "
                    "idle timeout outside the bounded top viable target rank; "
                    "retain slot while liquidation is pending"
                ),
                "quantity_rules_source": (
                    "top_of_book_without_live_instrument_steps"
                    if self._settings.symbol == AUTO_SYMBOL
                    else "conservative_static_assumptions"
                ),
                "quantity_steps": {
                    symbol: decimal_string(step)
                    for symbol, step in (
                        {}
                        if self._settings.symbol == AUTO_SYMBOL
                        else DEFAULT_COMMON_QUANTITY_STEPS
                    ).items()
                },
                "min_notionals": {
                    symbol: decimal_string(minimum)
                    for symbol, minimum in (
                        {
                            item.symbol: Decimal("10")
                            for item in self._universe
                        }
                        if self._settings.symbol == AUTO_SYMBOL
                        else DEFAULT_MIN_NOTIONALS
                    ).items()
                },
            },
            "venues": list(self._venue_state.values()),
            "best_opportunity": opportunities[0] if opportunities else None,
            "current_market_opportunity": (
                opportunities[0] if opportunities else None
            ),
            "current_executable_opportunity": (
                None
                if self._current_executable_opportunity is None
                else self._opportunity_dict(
                    self._current_executable_opportunity
                )
            ),
            "opportunities": opportunities[:20],
            "best_near_miss": best_near_miss,
            "last_profitable_signal": self._last_profitable_signal_status(),
            "diagnostics": diagnostics,
            "execution_blockers": list(self._execution_blockers),
            "balances": self._portfolio.to_dict()["balances"],
            "metrics": {
                "scan_count": self._scan_count,
                "trade_count": len(self._executor.journal),
                "winning_trades": winning,
                "realized_pnl": decimal_string(self._executor.realized_pnl),
                "arbitrage_realized_pnl": decimal_string(
                    self._executor.realized_pnl
                ),
                "strategy_equity_usdt": (
                    None
                    if strategy_equity is None
                    else decimal_string(strategy_equity)
                ),
                "strategy_pnl_usdt": (
                    None if strategy_pnl is None else decimal_string(strategy_pnl)
                ),
                "inventory_and_rebalance_pnl_usdt": (
                    None
                    if inventory_and_rebalance_pnl is None
                    else decimal_string(inventory_and_rebalance_pnl)
                ),
                "inventory_carry_pnl_usdt": (
                    None
                    if inventory_and_rebalance_pnl is None
                    else decimal_string(inventory_and_rebalance_pnl)
                ),
                "rebalance_count": len(self._rebalance_journal),
                "rebalance_modeled_cost_usdt": decimal_string(
                    rebalance_cost
                ),
                "execution_blocker_count": len(self._execution_blockers),
                "risk_adjusted_expected_pnl": decimal_string(expected_pnl),
                "symbol_count": len(self._universe) or (1 if self._books else 0),
                "book_count": len(self._books),
                "tradable_book_count": len(self._tradable_book_keys),
                "scanned_symbol_count": len(self._universe)
                or (1 if self._books else 0),
                "evaluated_symbol_count": len(
                    {
                        symbol
                        for symbol, _venue in self._tradable_book_keys
                        if sum(
                            1
                            for candidate_symbol, _candidate_venue in (
                                self._tradable_book_keys
                            )
                            if candidate_symbol == symbol
                        )
                        >= 2
                    }
                ),
                "candidate_count": len(self._candidate_evidence),
                "active_inventory_count": len(self._active_inventory),
            },
            "journal": journal,
            "errors": dict(self._errors),
        }
