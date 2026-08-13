from __future__ import annotations

from pathlib import Path
import tempfile

import pytest
from fastapi.testclient import TestClient

from packages.api.app import create_app
from packages.arbitrage import OrderBook, PriceLevel
from packages.arbitrage.service import ArbitragePaperService


pytestmark = pytest.mark.contract
NOW_MS = 1_800_000_000_000


class FakeAdapter:
    def __init__(self, venue: str, bid: str, ask: str) -> None:
        self.venue = venue
        self.book = OrderBook(
            venue,
            "BTCUSDT",
            NOW_MS,
            bids=(PriceLevel(bid, "20"),),
            asks=(PriceLevel(ask, "20"),),
        )

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        return self.book

    async def aclose(self) -> None:
        return None


def make_service() -> ArbitragePaperService:
    return ArbitragePaperService(
        (FakeAdapter("alpha", "99", "100"), FakeAdapter("beta", "102", "103")),
        initial_balances={
            "alpha": {"USDT": "10000", "BTC": "10"},
            "beta": {"USDT": "10000", "BTC": "10"},
        },
        taker_fees={"alpha": "0.001", "beta": "0.001"},
        clock_ms=lambda: NOW_MS,
    )


def test_arbitrage_api_full_paper_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as td:
        app = create_app(data_dir=Path(td), arbitrage_service=make_service())
        with TestClient(app) as client:
            status = client.get("/api/v1/arbitrage/status")
            assert status.status_code == 200
            assert status.json()["mode"] == "paper"
            assert status.json()["live_trading_enabled"] is False

            scan = client.post(
                "/api/v1/arbitrage/scan",
                json={
                    "symbol": "BTCUSDT",
                    "notional": "500",
                    "min_net_edge_bps": "1",
                    "risk_buffer_bps": "2",
                    "auto_execute": True,
                },
            )
            assert scan.status_code == 200
            body = scan.json()
            assert body["best_opportunity"]["route"] == "alpha->beta"
            assert body["metrics"]["trade_count"] == 1

            start = client.post(
                "/api/v1/arbitrage/start",
                json={"symbol": "BTCUSDT", "interval_ms": 500},
            )
            assert start.status_code == 200
            assert start.json()["running"] is True
            duplicate = client.post(
                "/api/v1/arbitrage/start",
                json={"symbol": "BTCUSDT", "interval_ms": 500},
            )
            assert duplicate.status_code == 409
            scan_while_running = client.post(
                "/api/v1/arbitrage/scan",
                json={"symbol": "SOLUSDT"},
            )
            assert scan_while_running.status_code == 409
            assert "monitor is running" in scan_while_running.json()["detail"]
            assert client.post("/api/v1/arbitrage/stop").json()["running"] is False

            reset = client.post("/api/v1/arbitrage/reset")
            assert reset.status_code == 200
            assert reset.json()["metrics"]["trade_count"] == 0


def test_standalone_app_serves_health_and_dashboard() -> None:
    app = create_app(arbitrage_service=make_service())
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["live_trading_enabled"] is False

        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert dashboard.headers["content-type"].startswith("text/html")
        assert "Arbitrage Lab" in dashboard.text
        assert "Без API-ключей" in dashboard.text


def test_arbitrage_api_rejects_unsafe_or_malformed_scan_inputs() -> None:
    with tempfile.TemporaryDirectory() as td:
        app = create_app(data_dir=td, arbitrage_service=make_service())
        with TestClient(app) as client:
            assert client.post(
                "/api/v1/arbitrage/scan", json={"symbol": "BTCUSD"}
            ).status_code == 422
            assert client.post(
                "/api/v1/arbitrage/scan", json={"symbol": "DOGEUSDT"}
            ).status_code == 422
            assert client.post(
                "/api/v1/arbitrage/scan", json={"notional": -1}
            ).status_code == 422
            assert client.post(
                "/api/v1/arbitrage/scan", json={"min_net_edge_bps": 10_000}
            ).status_code == 422
            assert client.post(
                "/api/v1/arbitrage/scan", json={"risk_buffer_bps": 10_000}
            ).status_code == 422
            assert client.post(
                "/api/v1/arbitrage/scan",
                json={"symbol": "AUTO", "max_symbols": 51},
            ).status_code == 422
            assert client.post(
                "/api/v1/arbitrage/scan",
                json={"symbol": "AUTO", "interval_ms": 1000},
            ).status_code == 422
            assert client.post(
                "/api/v1/arbitrage/scan", json={"api_key": "must-not-exist"}
            ).status_code == 422


def test_arbitrage_api_accepts_custom_auto_controls_and_rejects_bad_budget() -> None:
    with tempfile.TemporaryDirectory() as td:
        app = create_app(data_dir=td, arbitrage_service=make_service())
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/arbitrage/scan",
                json={
                    "symbol": "AUTO",
                    "notional": "30",
                    "activation_observations": 3,
                    "evidence_window_minutes": 15,
                    "inventory_idle_timeout_minutes": 90,
                    "max_symbols": 10,
                    "max_active_symbols": 3,
                    "allocation_per_symbol_venue_usdt": "60",
                    "min_24h_volume_usdt": "1500000",
                    "bbo_depth_multiplier": "3",
                    "initial_balance_per_venue_usdt": "750",
                },
            )
            assert response.status_code == 200
            settings = response.json()["settings"]
            assert settings["notional"] == "30"
            assert settings["activation_observations"] == 3
            assert settings["evidence_window_minutes"] == 15
            assert settings["inventory_idle_timeout_minutes"] == 90
            assert settings["max_active_symbols"] == 3
            assert settings["allocation_per_symbol_venue_usdt"] == "60"
            assert settings["min_24h_volume_usdt"] == "1500000"
            assert settings["bbo_depth_multiplier"] == "3"
            assert settings["initial_balance_per_venue_usdt"] == "750"
            # Injected deterministic portfolios keep their explicit balances;
            # the configurable seed applies only to the default AUTO account.
            assert response.json()["balances"]["alpha"]["USDT"] == "10000"
            assert response.json()["balances"]["beta"]["USDT"] == "10000"

            invalid_budget = client.post(
                "/api/v1/arbitrage/scan",
                json={
                    "symbol": "AUTO",
                    "notional": "60",
                    "max_active_symbols": 5,
                    "allocation_per_symbol_venue_usdt": "90",
                },
            )
            assert invalid_budget.status_code == 422
            assert "budget exceeds initial balance" in invalid_budget.text

            assert client.post(
                "/api/v1/arbitrage/scan",
                json={"symbol": "AUTO", "notional": "9"},
            ).status_code == 422
            assert client.post(
                "/api/v1/arbitrage/scan",
                json={"symbol": "AUTO", "min_24h_volume_usdt": 99_999},
            ).status_code == 422
            assert client.post(
                "/api/v1/arbitrage/scan",
                json={"symbol": "AUTO", "bbo_depth_multiplier": 101},
            ).status_code == 422
            assert client.post(
                "/api/v1/arbitrage/scan",
                json={"symbol": "AUTO", "inventory_idle_timeout_minutes": 0},
            ).status_code == 422
            assert client.post(
                "/api/v1/arbitrage/scan",
                json={
                    "symbol": "AUTO",
                    "notional": "60",
                    "allocation_per_symbol_venue_usdt": "50",
                },
            ).status_code == 422
            assert client.post(
                "/api/v1/arbitrage/scan",
                json={
                    "symbol": "AUTO",
                    "max_symbols": 2,
                    "max_active_symbols": 3,
                },
            ).status_code == 422


def test_arbitrage_reset_can_atomically_replace_auto_seed_balance() -> None:
    class AutoOnlyAdapter(FakeAdapter):
        async def fetch_tickers(self) -> tuple[()]:
            return ()

    service = ArbitragePaperService(
        (
            AutoOnlyAdapter("alpha", "99", "100"),
            AutoOnlyAdapter("beta", "99", "100"),
        ),
        clock_ms=lambda: NOW_MS,
    )
    app = create_app(arbitrage_service=service)
    with TestClient(app) as client:
        reset = client.post(
            "/api/v1/arbitrage/reset",
            json={"initial_balance_per_venue_usdt": "900"},
        )
        assert reset.status_code == 200
        body = reset.json()
        assert body["settings"]["initial_balance_per_venue_usdt"] == "900"
        assert body["balances"]["alpha"]["USDT"] == "900"
        assert body["balances"]["beta"]["USDT"] == "900"

        # Omitting the field on later API calls preserves the configured seed
        # instead of silently applying the model's original 500 USDT default.
        scan = client.post(
            "/api/v1/arbitrage/scan",
            json={"symbol": "AUTO", "auto_execute": False},
        )
        assert scan.status_code == 200
        assert scan.json()["settings"]["initial_balance_per_venue_usdt"] == "900"
        assert scan.json()["balances"]["alpha"]["USDT"] == "900"
