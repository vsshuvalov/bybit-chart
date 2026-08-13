"""Standalone FastAPI application for venue-neutral PAPER arbitrage."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from packages.api.arbitrage import register_arbitrage_endpoints
from packages.api.triangular import register_triangular_endpoints


ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_FILE = ROOT_DIR / "frontend" / "arbitrage.html"
TRIANGULAR_FRONTEND_FILE = ROOT_DIR / "frontend" / "triangular.html"


def create_app(
    data_dir: Path | str | None = None,
    arbitrage_service=None,
    triangular_service=None,
) -> FastAPI:
    """Build the standalone API.

    ``data_dir`` is accepted only for compatibility with the extracted
    integration tests. The prototype keeps all paper state in memory.
    """

    del data_dir
    app = FastAPI(
        title="Crypto Arbitrage PAPER Lab",
        description=(
            "Cross-exchange and triangular analysis on public market data. "
            "Virtual balances only. "
            "Live order submission is intentionally unavailable."
        ),
        version="0.2.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )
    register_arbitrage_endpoints(app, arbitrage_service)
    register_triangular_endpoints(app, triangular_service)

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "healthy",
            "service": "arbitrage-paper",
            "live_trading_enabled": False,
            "strategies": ["cross_exchange", "triangular"],
        }

    @app.get("/", include_in_schema=False, response_class=FileResponse)
    @app.get("/arbitrage.html", include_in_schema=False, response_class=FileResponse)
    async def dashboard() -> FileResponse:
        return FileResponse(FRONTEND_FILE)

    @app.get(
        "/triangular.html", include_in_schema=False, response_class=FileResponse
    )
    async def triangular_dashboard() -> FileResponse:
        return FileResponse(TRIANGULAR_FRONTEND_FILE)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "packages.api.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
