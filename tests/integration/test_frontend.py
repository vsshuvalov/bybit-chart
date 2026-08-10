"""
Тесты Frontend integration (Stage 4 / P4-S4-001).

Проверяют: наличие frontend файлов, API endpoints для frontend.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.contract


class TestFrontendFiles:
    """Тесты наличия frontend файлов."""

    def test_index_html_exists(self):
        """index.html существует."""
        frontend_dir = Path(__file__).parent.parent.parent / "frontend"
        index_path = frontend_dir / "index.html"
        assert index_path.exists()

    def test_readme_exists(self):
        """README.md существует."""
        frontend_dir = Path(__file__).parent.parent.parent / "frontend"
        readme_path = frontend_dir / "README.md"
        assert readme_path.exists()

    def test_serve_py_exists(self):
        """serve.py существует и исполняемый."""
        frontend_dir = Path(__file__).parent.parent.parent / "frontend"
        serve_path = frontend_dir / "serve.py"
        assert serve_path.exists()
        assert serve_path.stat().st_mode & 0o111  # исполняемый


class TestAPIForFrontend:
    """Тесты API endpoints, используемых frontend."""

    def test_cors_headers_missing(self):
        """CORS headers не настроены (для production нужно добавить)."""
        from packages.api.app import create_app
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get("/health")

            # CORS headers отсутствуют (это ожидаемо для MVP)
            assert "access-control-allow-origin" not in response.headers

    def test_api_endpoints_return_json(self):
        """API endpoints возвращают JSON с правильным Content-Type."""
        from packages.api.app import create_app
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            # /health
            response = client.get("/health")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/json")

            # /api/v1/symbols
            response = client.get("/api/v1/symbols")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/json")
