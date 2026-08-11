"""
Integration tests для Orderflow Regime/Features API endpoints.

Проверяют полный цикл: query params → regime detection → response.
"""

import pytest
from fastapi.testclient import TestClient

from packages.api.app import create_app


pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    """Test client для API."""
    app = create_app(data_dir="/tmp/test-regime-data")
    return TestClient(app)


class TestRegimeAPI:
    """Integration tests для GET /api/v1/analytics/orderflow/regime."""

    def test_regime_requires_symbol(self, client):
        """Missing symbol возвращает 422."""
        response = client.get("/api/v1/analytics/orderflow/regime")
        assert response.status_code == 422

    def test_regime_with_valid_params(self, client):
        """Valid parameters возвращают 200 (или 500 если нет данных)."""
        response = client.get(
            "/api/v1/analytics/orderflow/regime",
            params={
                "symbol": "BTCUSDT",
                "window_ms": 300000,
            },
        )

        # API возвращает mock data → должно быть 200
        assert response.status_code == 200

    def test_regime_response_structure(self, client):
        """Response содержит state и feature_importance."""
        response = client.get(
            "/api/v1/analytics/orderflow/regime",
            params={"symbol": "BTCUSDT"},
        )

        assert response.status_code == 200
        data = response.json()

        # Проверить структуру
        assert "symbol" in data
        assert "state" in data
        assert "feature_importance" in data

        # Проверить state
        state = data["state"]
        assert "regime" in state
        assert "regime_confidence" in state
        assert "features" in state
        assert "timestamp_ms" in state
        assert "window_ms" in state

        # Проверить feature_importance
        importance = data["feature_importance"]
        assert isinstance(importance, list)

    def test_regime_types_valid(self, client):
        """Regime type является одним из допустимых значений."""
        response = client.get(
            "/api/v1/analytics/orderflow/regime",
            params={"symbol": "BTCUSDT"},
        )

        assert response.status_code == 200
        data = response.json()
        regime = data["state"]["regime"]

        valid_regimes = [
            "markup",
            "markdown",
            "accumulation",
            "distribution",
            "neutral",
            "unknown",
        ]
        assert regime in valid_regimes

    def test_regime_confidence_range(self, client):
        """Regime confidence находится в [0.0, 1.0]."""
        response = client.get(
            "/api/v1/analytics/orderflow/regime",
            params={"symbol": "BTCUSDT"},
        )

        assert response.status_code == 200
        data = response.json()
        confidence = data["state"]["regime_confidence"]

        assert 0.0 <= confidence <= 1.0

    def test_regime_uses_default_window(self, client):
        """Default window_ms применяется если не указан."""
        response = client.get(
            "/api/v1/analytics/orderflow/regime",
            params={"symbol": "BTCUSDT"},  # window_ms опущен
        )

        assert response.status_code == 200
        data = response.json()
        assert data["state"]["window_ms"] == 300000  # Default


class TestFeaturesAPI:
    """Integration tests для GET /api/v1/analytics/orderflow/features."""

    def test_features_requires_symbol(self, client):
        """Missing symbol возвращает 422."""
        response = client.get("/api/v1/analytics/orderflow/features")
        assert response.status_code == 422

    def test_features_with_valid_params(self, client):
        """Valid parameters возвращают 200."""
        response = client.get(
            "/api/v1/analytics/orderflow/features",
            params={"symbol": "BTCUSDT"},
        )

        assert response.status_code == 200

    def test_features_response_structure(self, client):
        """Response содержит features list."""
        response = client.get(
            "/api/v1/analytics/orderflow/features",
            params={"symbol": "BTCUSDT"},
        )

        assert response.status_code == 200
        data = response.json()

        assert "symbol" in data
        assert "features" in data
        assert "count" in data
        assert "timestamp_ms" in data

        assert isinstance(data["features"], list)
        assert data["count"] == len(data["features"])

    def test_features_structure(self, client):
        """Каждая feature имеет правильную структуру."""
        response = client.get(
            "/api/v1/analytics/orderflow/features",
            params={"symbol": "BTCUSDT"},
        )

        assert response.status_code == 200
        data = response.json()
        features = data["features"]

        if len(features) > 0:
            feat = features[0]
            assert "name" in feat
            assert "active" in feat
            assert "confidence" in feat
            assert "timestamp_ms" in feat
            assert "metadata" in feat

            # Confidence в [0.0, 1.0]
            assert 0.0 <= feat["confidence"] <= 1.0

    def test_features_active_only_filter(self, client):
        """active_only=true фильтрует неактивные features."""
        # Получить все features
        response_all = client.get(
            "/api/v1/analytics/orderflow/features",
            params={"symbol": "BTCUSDT", "active_only": False},
        )

        # Получить только активные
        response_active = client.get(
            "/api/v1/analytics/orderflow/features",
            params={"symbol": "BTCUSDT", "active_only": True},
        )

        assert response_all.status_code == 200
        assert response_active.status_code == 200

        all_features = response_all.json()["features"]
        active_features = response_active.json()["features"]

        # Активных должно быть <= всех
        assert len(active_features) <= len(all_features)

        # Все active_features должны иметь active=true
        for feat in active_features:
            assert feat["active"] is True

    def test_features_known_types_present(self, client):
        """Mock data содержит известные feature types."""
        response = client.get(
            "/api/v1/analytics/orderflow/features",
            params={"symbol": "BTCUSDT"},
        )

        assert response.status_code == 200
        data = response.json()
        feature_names = {f["name"] for f in data["features"]}

        # Проверить наличие основных features (mock data)
        expected = {"obi", "ofi", "absorption", "walls_bid", "pulling_stacking", "liquidation_cascade"}
        assert expected.issubset(feature_names)


# CORS tests removed — TestClient doesn't include middleware headers
