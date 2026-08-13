from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from packages.api.app import create_app
from packages.arbitrage.triangular import MarketTicker
from packages.arbitrage.triangular_service import TriangularPaperService


pytestmark = pytest.mark.contract
NOW_MS = 1_800_000_000_000


class FakeAdapter:
    venue = "bybit"

    async def fetch_tickers(self) -> tuple[MarketTicker, ...]:
        common = {
            "venue": self.venue,
            "timestamp_ms": NOW_MS,
            "bid_size": "100",
            "ask_size": "100",
            "quote_volume": "1000000",
            "volume_usdt": "1000000",
        }
        return (
            MarketTicker(
                symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
                bid="99", ask="100", snapshot_id="1", **common,
            ),
            MarketTicker(
                symbol="ETHBTC", base_asset="ETH", quote_asset="BTC",
                bid="0.49", ask="0.5", snapshot_id="2", **common,
            ),
            MarketTicker(
                symbol="ETHUSDT", base_asset="ETH", quote_asset="USDT",
                bid="51.5", ask="52", snapshot_id="3", **common,
            ),
        )

    async def aclose(self) -> None:
        return None


def make_service() -> TriangularPaperService:
    return TriangularPaperService(
        (FakeAdapter(),),
        initial_balances={"bybit": {"USDT": "10000"}},
        taker_fees={"bybit": "0.001"},
        clock_ms=lambda: NOW_MS,
    )


def test_triangular_api_full_paper_lifecycle() -> None:
    app = create_app(triangular_service=make_service())
    with TestClient(app) as client:
        status = client.get("/api/v1/triangular/status")
        assert status.status_code == 200
        assert status.json()["strategy"] == "triangular"

        scan = client.post(
            "/api/v1/triangular/scan",
            json={
                "venue": "bybit",
                "start_asset": "USDT",
                "start_amount": "500",
                "min_net_edge_bps": "1",
                "risk_buffer_bps": "2",
                "max_tickers": 50,
                "auto_execute": True,
            },
        )
        assert scan.status_code == 200
        body = scan.json()
        assert body["best_opportunity"]["path"] == "USDT → BTC → ETH → USDT"
        assert body["metrics"]["trade_count"] == 1

        start = client.post(
            "/api/v1/triangular/start",
            json={"venue": "bybit", "interval_ms": 10_000},
        )
        assert start.status_code == 200
        assert start.json()["running"] is True
        duplicate = client.post(
            "/api/v1/triangular/start",
            json={"venue": "bybit", "interval_ms": 10_000},
        )
        assert duplicate.status_code == 409
        assert client.post("/api/v1/triangular/stop").json()["running"] is False
        assert client.post("/api/v1/triangular/reset").json()["metrics"]["trade_count"] == 0


def test_triangular_api_rejects_unsafe_or_out_of_scope_inputs() -> None:
    app = create_app(triangular_service=make_service())
    with TestClient(app) as client:
        invalid_payloads = (
            {"venue": "unknown"},
            {"start_asset": "DOGE"},
            {"start_amount": 0},
            {"min_net_edge_bps": 10_000},
            {"risk_buffer_bps": 10_000},
            {"max_tickers": 51},
            {"max_tickers": 2},
            {"interval_ms": 9_999},
            {"api_key": "must-not-exist"},
        )
        for payload in invalid_payloads:
            response = client.post("/api/v1/triangular/scan", json=payload)
            assert response.status_code == 422, payload


def test_app_serves_triangular_dashboard_route() -> None:
    app = create_app(triangular_service=make_service())
    with TestClient(app) as client:
        response = client.get("/triangular.html")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "Треугольный арбитраж" in response.text
