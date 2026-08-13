"""FastAPI contract for the public-data, paper-only arbitrage prototype."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.arbitrage.models import normalize_symbol
from packages.arbitrage.service import (
    AUTO_PAPER_INITIAL_USDT,
    AUTO_SYMBOL,
    DEFAULT_AUTO_ACTIVATION_OBSERVATIONS,
    DEFAULT_AUTO_ALLOCATION_PER_SYMBOL_VENUE_USDT,
    DEFAULT_AUTO_EVIDENCE_WINDOW_MINUTES,
    DEFAULT_AUTO_MAX_ACTIVE_SYMBOLS,
    DEFAULT_AUTO_MAX_TRADE_USDT,
    DEFAULT_MAX_SYMBOLS,
    DEFAULT_COMMON_QUANTITY_STEPS,
    ArbitragePaperService,
    ScanSettings,
)


class ArbitrageScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = AUTO_SYMBOL
    notional: Decimal = Field(
        default=DEFAULT_AUTO_MAX_TRADE_USDT, gt=0, le=1_000_000
    )
    min_net_edge_bps: Decimal = Field(default=Decimal("5"), ge=0, lt=10_000)
    risk_buffer_bps: Decimal = Field(default=Decimal("2"), ge=0, lt=10_000)
    auto_execute: bool = False
    interval_ms: int = Field(default=2000, ge=500, le=60_000)
    max_symbols: int = Field(default=DEFAULT_MAX_SYMBOLS, ge=1, le=50)
    activation_observations: int = Field(
        default=DEFAULT_AUTO_ACTIVATION_OBSERVATIONS, ge=1, le=100
    )
    evidence_window_minutes: int = Field(
        default=DEFAULT_AUTO_EVIDENCE_WINDOW_MINUTES, ge=1, le=1_440
    )
    max_active_symbols: int = Field(
        default=DEFAULT_AUTO_MAX_ACTIVE_SYMBOLS, ge=1, le=50
    )
    allocation_per_symbol_venue_usdt: Decimal = Field(
        default=DEFAULT_AUTO_ALLOCATION_PER_SYMBOL_VENUE_USDT,
        gt=0,
        le=AUTO_PAPER_INITIAL_USDT,
    )

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        symbol = normalize_symbol(value)
        if symbol != AUTO_SYMBOL and symbol not in DEFAULT_COMMON_QUANTITY_STEPS:
            supported = ", ".join(
                (AUTO_SYMBOL, *sorted(DEFAULT_COMMON_QUANTITY_STEPS))
            )
            raise ValueError(f"prototype supports only: {supported}")
        return symbol

    @model_validator(mode="after")
    def validate_auto_settings(self) -> "ArbitrageScanRequest":
        if self.symbol != AUTO_SYMBOL:
            return self
        if self.interval_ms < 2_000:
            raise ValueError("AUTO interval_ms must be at least 2000")
        if self.notional < Decimal("10"):
            raise ValueError("AUTO notional must be at least 10 USDT")
        if self.allocation_per_symbol_venue_usdt < self.notional:
            raise ValueError(
                "AUTO allocation_per_symbol_venue_usdt must be greater than "
                "or equal to notional"
            )
        if self.max_active_symbols > self.max_symbols:
            raise ValueError("AUTO max_active_symbols must not exceed max_symbols")
        committed = (
            Decimal(self.max_active_symbols)
            * self.allocation_per_symbol_venue_usdt
            + self.notional
        )
        if committed > AUTO_PAPER_INITIAL_USDT:
            raise ValueError(
                "AUTO budget exceeds 500 USDT per venue: max_active_symbols "
                "* allocation_per_symbol_venue_usdt + notional must be <= 500"
            )
        return self

    def settings(self) -> ScanSettings:
        return ScanSettings(
            symbol=self.symbol,
            notional=self.notional,
            min_net_edge_bps=self.min_net_edge_bps,
            risk_buffer_bps=self.risk_buffer_bps,
            auto_execute=self.auto_execute,
            interval_ms=self.interval_ms,
            max_symbols=self.max_symbols,
            activation_observations=self.activation_observations,
            evidence_window_minutes=self.evidence_window_minutes,
            max_active_symbols=self.max_active_symbols,
            allocation_per_symbol_venue_usdt=(
                self.allocation_per_symbol_venue_usdt
            ),
        )


def register_arbitrage_endpoints(
    app: FastAPI,
    service: ArbitragePaperService | None = None,
) -> None:
    """Register endpoints while constructing network clients lazily.

    Lazy construction keeps unrelated API/unit tests from creating unused
    HTTP clients.  A custom service can be injected for deterministic tests.
    """

    app.state.arbitrage_service = service

    def get_service() -> ArbitragePaperService:
        current = app.state.arbitrage_service
        if current is None:
            current = ArbitragePaperService()
            app.state.arbitrage_service = current
        return current

    @app.get("/api/v1/arbitrage/status")
    async def arbitrage_status() -> dict[str, Any]:
        return get_service().status()

    @app.post("/api/v1/arbitrage/scan")
    async def arbitrage_scan(request: ArbitrageScanRequest) -> dict[str, Any]:
        try:
            return await get_service().scan(request.settings())
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/arbitrage/start")
    async def arbitrage_start(request: ArbitrageScanRequest) -> dict[str, Any]:
        try:
            return await get_service().start(request.settings())
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/arbitrage/stop")
    async def arbitrage_stop() -> dict[str, Any]:
        return await get_service().stop()

    @app.post("/api/v1/arbitrage/reset")
    async def arbitrage_reset() -> dict[str, Any]:
        return await get_service().reset()

    async def close_arbitrage_service() -> None:
        current = app.state.arbitrage_service
        if current is not None:
            await current.close()

    app.add_event_handler("shutdown", close_arbitrage_service)
