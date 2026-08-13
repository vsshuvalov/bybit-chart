"""Atomic, in-memory paper execution for two-leg spot arbitrage.

This module contains no exchange client, networking, credentials, or order
submission code.  It can only mutate virtual balances supplied by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from packages.arbitrage.models import (
    ONE,
    ZERO,
    ArbitrageOpportunity,
    OrderBook,
    Side,
    decimal_string,
    decimal_value,
    normalize_venue,
)


class PaperExecutionError(RuntimeError):
    """Base class for rejected virtual executions."""


class InsufficientBalanceError(PaperExecutionError):
    """A paper leg would overdraw quote cash or short the base asset."""


def _asset_name(asset: str) -> str:
    if not isinstance(asset, str):
        raise TypeError("asset must be a string")
    normalized = asset.strip().upper()
    if not normalized:
        raise ValueError("asset must not be empty")
    return normalized


def _json_balances(balances: Mapping[str, Mapping[str, Decimal]]) -> dict[str, dict[str, str]]:
    return {
        venue: {
            asset: decimal_string(amount)
            for asset, amount in sorted(assets.items())
        }
        for venue, assets in sorted(balances.items())
    }


class PaperPortfolio:
    """Virtual per-venue asset balances with no borrowing or shorting."""

    def __init__(
        self,
        initial_balances: Mapping[str, Mapping[str, Decimal | str | int | float]] | None = None,
        *,
        balances: Mapping[str, Mapping[str, Decimal | str | int | float]] | None = None,
    ) -> None:
        if initial_balances is not None and balances is not None:
            raise ValueError("pass either initial_balances or balances, not both")
        source = balances if balances is not None else initial_balances
        normalized: dict[str, dict[str, Decimal]] = {}
        for venue, assets in (source or {}).items():
            normalized_venue = normalize_venue(venue)
            if not isinstance(assets, Mapping):
                raise TypeError("each venue balance must be an asset mapping")
            venue_balances = normalized.setdefault(normalized_venue, {})
            for asset, raw_amount in assets.items():
                normalized_asset = _asset_name(asset)
                amount = decimal_value(
                    raw_amount,
                    name=f"initial balance {normalized_asset}@{normalized_venue}",
                )
                if amount < ZERO:
                    raise ValueError("initial balances must not be negative")
                venue_balances[normalized_asset] = amount
        self._balances = normalized

    @property
    def balances(self) -> dict[str, dict[str, Decimal]]:
        """Return a defensive snapshot of all virtual balances."""

        return self.snapshot()

    def snapshot(self) -> dict[str, dict[str, Decimal]]:
        return {venue: dict(assets) for venue, assets in self._balances.items()}

    def balance(self, venue: str, asset: str) -> Decimal:
        normalized_venue = normalize_venue(venue)
        normalized_asset = _asset_name(asset)
        return self._balances.get(normalized_venue, {}).get(normalized_asset, ZERO)

    def deposit(
        self,
        venue: str,
        asset: str,
        amount: Decimal | str | int | float,
    ) -> None:
        """Add virtual funds; useful for deterministic scenario setup."""

        normalized_venue = normalize_venue(venue)
        normalized_asset = _asset_name(asset)
        value = decimal_value(amount, name="deposit amount")
        if value <= ZERO:
            raise ValueError("deposit amount must be greater than zero")
        proposed = self.snapshot()
        venue_balances = proposed.setdefault(normalized_venue, {})
        venue_balances[normalized_asset] = venue_balances.get(normalized_asset, ZERO) + value
        self._balances = proposed

    def to_dict(self) -> dict[str, Any]:
        return {"balances": _json_balances(self._balances)}

    def _propose(self, deltas: Mapping[tuple[str, str], Decimal]) -> dict[str, dict[str, Decimal]]:
        proposed = self.snapshot()
        for (venue, asset), delta in deltas.items():
            normalized_venue = normalize_venue(venue)
            normalized_asset = _asset_name(asset)
            venue_balances = proposed.setdefault(normalized_venue, {})
            updated = venue_balances.get(normalized_asset, ZERO) + delta
            if updated < ZERO:
                raise InsufficientBalanceError(
                    f"insufficient {normalized_asset} balance on {normalized_venue}: "
                    f"required {-delta}, available {venue_balances.get(normalized_asset, ZERO)}"
                )
            venue_balances[normalized_asset] = updated
        return proposed

    def _commit(self, proposed: dict[str, dict[str, Decimal]]) -> None:
        self._balances = proposed


@dataclass(frozen=True, slots=True)
class PaperLeg:
    venue: str
    side: Side
    base_asset: str
    quote_asset: str
    quantity: Decimal
    vwap: Decimal
    notional: Decimal
    fee: Decimal

    @property
    def fee_rate(self) -> Decimal:
        """Return the effective quote-currency fee rate for this fill."""

        return self.fee / self.notional if self.notional > ZERO else ZERO

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "side": self.side.value,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "quantity": decimal_string(self.quantity),
            "vwap": decimal_string(self.vwap),
            "notional": decimal_string(self.notional),
            "fee": decimal_string(self.fee),
            # Paper spot fees are modelled as quote-currency debits on both
            # legs.  Keep the historical ``fee`` field and add explicit,
            # JSON-safe metadata so API consumers do not have to infer the
            # unit or recalculate the rate with binary floating point.
            "fee_quote": decimal_string(self.fee),
            "fee_asset": self.quote_asset,
            "fee_rate": decimal_string(self.fee_rate),
            "fee_rate_bps": decimal_string(self.fee_rate * Decimal("10000")),
        }


@dataclass(frozen=True, slots=True)
class PaperExecution:
    execution_id: str
    timestamp_ms: int
    symbol: str
    buy_leg: PaperLeg
    sell_leg: PaperLeg
    realized_pnl: Decimal
    expected_net_profit: Decimal
    balances_after: Mapping[str, Mapping[str, Decimal]]

    @property
    def total_fee_quote(self) -> Decimal:
        """Combined buy and sell fees, denominated in the shared quote asset."""

        return self.buy_leg.fee + self.sell_leg.fee

    def to_dict(self) -> dict[str, Any]:
        result = {
            "execution_id": self.execution_id,
            "timestamp_ms": self.timestamp_ms,
            "symbol": self.symbol,
            "buy_leg": self.buy_leg.to_dict(),
            "sell_leg": self.sell_leg.to_dict(),
            "realized_pnl": decimal_string(self.realized_pnl),
            "expected_net_profit": decimal_string(self.expected_net_profit),
            "balances_after": _json_balances(self.balances_after),
            "buy_fee_quote": decimal_string(self.buy_leg.fee),
            "sell_fee_quote": decimal_string(self.sell_leg.fee),
            "total_fee_quote": decimal_string(self.total_fee_quote),
            "fee_quote_asset": self.buy_leg.quote_asset,
            "buy_fee_rate": decimal_string(self.buy_leg.fee_rate),
            "sell_fee_rate": decimal_string(self.sell_leg.fee_rate),
            "buy_fee_rate_bps": decimal_string(
                self.buy_leg.fee_rate * Decimal("10000")
            ),
            "sell_fee_rate_bps": decimal_string(
                self.sell_leg.fee_rate * Decimal("10000")
            ),
        }
        # The current cross-venue scanner admits USDT-quoted pairs.  These
        # aliases make the journal contract direct for the UI while the
        # ``*_quote`` fields above remain correct for reusable non-USDT paper
        # executions.
        if self.buy_leg.quote_asset == "USDT" and self.sell_leg.quote_asset == "USDT":
            result.update(
                {
                    "buy_fee_usdt": decimal_string(self.buy_leg.fee),
                    "sell_fee_usdt": decimal_string(self.sell_leg.fee),
                    "total_fee_usdt": decimal_string(self.total_fee_quote),
                }
            )
        return result


class PaperArbitrageExecutor:
    """Execute both virtual legs as one all-or-nothing state transition."""

    def __init__(
        self,
        portfolio: PaperPortfolio,
        taker_fees: Mapping[str, Decimal | str | int | float] | None = None,
    ) -> None:
        if not isinstance(portfolio, PaperPortfolio):
            raise TypeError("portfolio must be a PaperPortfolio")
        self.portfolio = portfolio
        self.taker_fees: dict[str, Decimal] = {}
        for venue, raw_fee in (taker_fees or {}).items():
            normalized_venue = normalize_venue(venue)
            fee = decimal_value(raw_fee, name=f"taker fee for {normalized_venue}")
            if fee < ZERO or fee >= ONE:
                raise ValueError("taker fees must be in [0, 1)")
            self.taker_fees[normalized_venue] = fee
        self.journal: list[PaperExecution] = []
        self.realized_pnl = ZERO

    def _fee_rate(
        self,
        venue: str,
        planned_fee: Decimal,
        planned_notional: Decimal,
    ) -> Decimal:
        explicit = self.taker_fees.get(normalize_venue(venue))
        if explicit is not None:
            return explicit
        return planned_fee / planned_notional if planned_notional > ZERO else ZERO

    def execute(
        self,
        opportunity: ArbitrageOpportunity,
        buy_book: OrderBook | None = None,
        sell_book: OrderBook | None = None,
        *,
        timestamp_ms: int | None = None,
    ) -> PaperExecution:
        """Atomically apply a matched buy and sell to virtual balances.

        Passing current books re-prices both legs from depth.  Omitting them
        executes the immutable quote captured in the opportunity.  Any
        validation, liquidity, or balance failure leaves balances, PnL, and
        the journal untouched.
        """

        if not isinstance(opportunity, ArbitrageOpportunity):
            raise TypeError("opportunity must be an ArbitrageOpportunity")
        if (buy_book is None) != (sell_book is None):
            raise ValueError("buy_book and sell_book must be supplied together")
        if opportunity.base_asset == opportunity.quote_asset:
            raise PaperExecutionError("base and quote assets must differ")

        if buy_book is not None and sell_book is not None:
            if buy_book.venue != opportunity.buy_venue or sell_book.venue != opportunity.sell_venue:
                raise PaperExecutionError("books do not match opportunity venues")
            if buy_book.symbol != opportunity.symbol or sell_book.symbol != opportunity.symbol:
                raise PaperExecutionError("books do not match opportunity symbol")
            buy_quote = buy_book.executable_vwap(Side.BUY, opportunity.quantity)
            sell_quote = sell_book.executable_vwap(Side.SELL, opportunity.quantity)
            buy_notional = buy_quote.notional
            sell_notional = sell_quote.notional
            buy_vwap = buy_quote.average_price
            sell_vwap = sell_quote.average_price
        else:
            buy_notional = opportunity.buy_notional
            sell_notional = opportunity.sell_notional
            buy_vwap = opportunity.buy_vwap
            sell_vwap = opportunity.sell_vwap

        buy_rate = self._fee_rate(
            opportunity.buy_venue,
            opportunity.buy_fee,
            opportunity.buy_notional,
        )
        sell_rate = self._fee_rate(
            opportunity.sell_venue,
            opportunity.sell_fee,
            opportunity.sell_notional,
        )
        buy_fee = buy_notional * buy_rate
        sell_fee = sell_notional * sell_rate
        buy_debit = buy_notional + buy_fee
        sell_credit = sell_notional - sell_fee

        available_quote = self.portfolio.balance(opportunity.buy_venue, opportunity.quote_asset)
        available_base = self.portfolio.balance(opportunity.sell_venue, opportunity.base_asset)
        if available_quote < buy_debit:
            raise InsufficientBalanceError(
                f"insufficient {opportunity.quote_asset} on {opportunity.buy_venue}: "
                f"required {buy_debit}, available {available_quote}"
            )
        if available_base < opportunity.quantity:
            raise InsufficientBalanceError(
                f"insufficient {opportunity.base_asset} on {opportunity.sell_venue}: "
                f"required {opportunity.quantity}, available {available_base}"
            )

        deltas = {
            (opportunity.buy_venue, opportunity.quote_asset): -buy_debit,
            (opportunity.buy_venue, opportunity.base_asset): opportunity.quantity,
            (opportunity.sell_venue, opportunity.base_asset): -opportunity.quantity,
            (opportunity.sell_venue, opportunity.quote_asset): sell_credit,
        }
        proposed = self.portfolio._propose(deltas)
        realized = sell_credit - buy_debit

        if timestamp_ms is None:
            execution_timestamp = max(
                buy_book.timestamp_ms if buy_book is not None else opportunity.buy_timestamp_ms,
                sell_book.timestamp_ms if sell_book is not None else opportunity.sell_timestamp_ms,
            )
        else:
            if isinstance(timestamp_ms, bool):
                raise TypeError("timestamp_ms must be an integer")
            try:
                execution_timestamp = int(timestamp_ms)
            except (TypeError, ValueError) as exc:
                raise TypeError("timestamp_ms must be an integer") from exc
            if execution_timestamp < 0:
                raise ValueError("timestamp_ms must not be negative")

        buy_leg = PaperLeg(
            venue=opportunity.buy_venue,
            side=Side.BUY,
            base_asset=opportunity.base_asset,
            quote_asset=opportunity.quote_asset,
            quantity=opportunity.quantity,
            vwap=buy_vwap,
            notional=buy_notional,
            fee=buy_fee,
        )
        sell_leg = PaperLeg(
            venue=opportunity.sell_venue,
            side=Side.SELL,
            base_asset=opportunity.base_asset,
            quote_asset=opportunity.quote_asset,
            quantity=opportunity.quantity,
            vwap=sell_vwap,
            notional=sell_notional,
            fee=sell_fee,
        )
        execution = PaperExecution(
            execution_id=f"paper-{len(self.journal) + 1}",
            timestamp_ms=execution_timestamp,
            symbol=opportunity.symbol,
            buy_leg=buy_leg,
            sell_leg=sell_leg,
            realized_pnl=realized,
            expected_net_profit=opportunity.net_profit,
            balances_after={venue: dict(assets) for venue, assets in proposed.items()},
        )

        # Commit is intentionally last: both legs, journal and PnL form one
        # deterministic in-memory transaction after all failure points above.
        self.portfolio._commit(proposed)
        self.journal.append(execution)
        self.realized_pnl += realized
        return execution

    execute_opportunity = execute

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio": self.portfolio.to_dict(),
            "realized_pnl": decimal_string(self.realized_pnl),
            "journal": [entry.to_dict() for entry in self.journal],
        }


# Concise aliases for callers building a pure paper prototype.
PaperExecutor = PaperArbitrageExecutor
PaperArbitrageEngine = PaperArbitrageExecutor
PaperAccount = PaperPortfolio
