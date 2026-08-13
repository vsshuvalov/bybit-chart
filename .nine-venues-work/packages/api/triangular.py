"""FastAPI contract for venue-local triangular arbitrage in PAPER mode."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.arbitrage.triangular_service import (
    SUPPORTED_START_ASSETS,
    SUPPORTED_VENUES,
    TriangularPaperService,
    TriangularScanSettings,
)


class TriangularScanRequest(BaseModel):
    """Safe public-data settings; credentials and live orders are absent."""

    model_config = ConfigDict(extra="forbid")

    venue: str = "all"
    start_asset: str = "USDT"
    start_amount: Decimal = Field(default=Decimal("1000"), gt=0, le=1_000_000)
    min_net_edge_bps: Decimal = Field(default=Decimal("5"), ge=0, lt=10_000)
    risk_buffer_bps: Decimal = Field(default=Decimal("2"), ge=0, lt=10_000)
    auto_execute: bool = False
    interval_ms: int = Field(default=10_000, ge=10_000, le=60_000)
    max_tickers: int = Field(default=50, ge=3, le=50)

    @field_validator("venue")
    @classmethod
    def validate_venue(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("venue must be a string")
        venue = value.strip().lower()
        allowed = {"all", *SUPPORTED_VENUES}
        if venue not in allowed:
            raise ValueError(f"venue must be one of: {', '.join(sorted(allowed))}")
        return venue

    @field_validator("start_asset")
    @classmethod
    def validate_start_asset(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("start_asset must be a string")
        asset = value.strip().upper()
        if asset not in SUPPORTED_START_ASSETS:
            raise ValueError(
                "start_asset must be one of: "
                + ", ".join(sorted(SUPPORTED_START_ASSETS))
            )
        return asset

    def settings(self) -> TriangularScanSettings:
        return TriangularScanSettings(
            venue=self.venue,
            start_asset=self.start_asset,
            start_amount=self.start_amount,
            min_net_edge_bps=self.min_net_edge_bps,
            risk_buffer_bps=self.risk_buffer_bps,
            auto_execute=self.auto_execute,
            interval_ms=self.interval_ms,
            max_tickers=self.max_tickers,
        )


def register_triangular_endpoints(
    app: FastAPI,
    service: TriangularPaperService | None = None,
) -> None:
    """Register a separate API namespace for same-venue three-leg cycles."""

    app.state.triangular_service = service

    def get_service() -> TriangularPaperService:
        current = app.state.triangular_service
        if current is None:
            current = TriangularPaperService()
            app.state.triangular_service = current
        return current

    @app.get("/api/v1/triangular/status")
    async def triangular_status() -> dict[str, Any]:
        return get_service().status()

    @app.post("/api/v1/triangular/scan")
    async def triangular_scan(request: TriangularScanRequest) -> dict[str, Any]:
        return await get_service().scan(request.settings())

    @app.post("/api/v1/triangular/start")
    async def triangular_start(request: TriangularScanRequest) -> dict[str, Any]:
        try:
            return await get_service().start(request.settings())
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/triangular/stop")
    async def triangular_stop() -> dict[str, Any]:
        return await get_service().stop()

    @app.post("/api/v1/triangular/reset")
    async def triangular_reset() -> dict[str, Any]:
        return await get_service().reset()

    async def close_triangular_service() -> None:
        current = app.state.triangular_service
        if current is not None:
            await current.close()

    app.add_event_handler("shutdown", close_triangular_service)
