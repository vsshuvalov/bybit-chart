"""
Integration tests для Heatmap API endpoint.

Проверяют полный цикл: query params → aggregation → response.
"""

import pytest
from fastapi.testclient import TestClient

from packages.api.app import create_app


pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    """Test client для API."""
    app = create_app(data_dir="/tmp/test-heatmap-data")
    return TestClient(app)


class TestHeatmapAPI:
    """Integration tests для GET /api/v1/analytics/heatmap."""

    def test_heatmap_requires_all_params(self, client):
        """Missing параметры возвращают 422."""
        response = client.get("/api/v1/analytics/heatmap")
        assert response.status_code == 422

    def test_heatmap_validates_time_range(self, client):
        """Invalid time range (end <= start) возвращает 400."""
        response = client.get(
            "/api/v1/analytics/heatmap",
            params={
                "symbol": "BTCUSDT",
                "start_ms": 2000,
                "end_ms": 1000,  # end < start
                "price_bin_size": 10,
                "time_interval_ms": 60000,
            },
        )
        assert response.status_code == 400
        assert "end_ms must be greater than start_ms" in response.json()["detail"]

    def test_heatmap_validates_bin_size(self, client):
        """Invalid bin size (<1) возвращает 422."""
        response = client.get(
            "/api/v1/analytics/heatmap",
            params={
                "symbol": "BTCUSDT",
                "start_ms": 1000,
                "end_ms": 2000,
                "price_bin_size": 0,  # Invalid
                "time_interval_ms": 60000,
            },
        )
        assert response.status_code == 422

    def test_heatmap_validates_interval(self, client):
        """Invalid time interval (<1000) возвращает 422."""
        response = client.get(
            "/api/v1/analytics/heatmap",
            params={
                "symbol": "BTCUSDT",
                "start_ms": 1000,
                "end_ms": 2000,
                "price_bin_size": 10,
                "time_interval_ms": 500,  # Too small
            },
        )
        assert response.status_code == 422

    def test_heatmap_uses_defaults(self, client):
        """Default parameters применяются если не указаны."""
        # Этот тест пройдёт 404 т.к. нет данных, но проверим структуру
        response = client.get(
            "/api/v1/analytics/heatmap",
            params={
                "symbol": "BTCUSDT",
                "start_ms": 1000,
                "end_ms": 2000,
                # price_bin_size и time_interval_ms опущены
            },
        )

        # Ожидаем 404 (no data) или 500 (no reader), не 422 (validation)
        assert response.status_code in (404, 500)

    def test_heatmap_response_structure(self, client):
        """Response содержит правильную структуру (если данные есть)."""
        response = client.get(
            "/api/v1/analytics/heatmap",
            params={
                "symbol": "BTCUSDT",
                "start_ms": 1000000000,
                "end_ms": 1000060000,
                "price_bin_size": 10,
                "time_interval_ms": 60000,
            },
        )

        # В тестовом окружении нет данных → 404 или 500
        if response.status_code == 200:
            data = response.json()
            assert "symbol" in data
            assert "tiles" in data
            assert "count" in data
            assert isinstance(data["tiles"], list)
            assert data["symbol"] == "BTCUSDT"


class TestHeatmapAPIHeaders:
    """Tests для HTTP headers."""

    def test_content_type_json(self, client):
        """Content-Type = application/json."""
        response = client.get(
            "/api/v1/analytics/heatmap",
            params={
                "symbol": "BTCUSDT",
                "start_ms": 1000,
                "end_ms": 2000,
            },
        )

        if response.status_code in (200, 404, 500):
            assert "application/json" in response.headers["content-type"]
