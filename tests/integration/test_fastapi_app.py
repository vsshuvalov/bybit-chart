"""
Тесты FastAPI приложения (P3-S3-002).

Проверяют: health check, /api/v1/symbols endpoint.
"""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts.schemas import RawTrade, TakerSide
from packages.api.app import create_app
from packages.bybit.collector import EventCollector

pytestmark = pytest.mark.contract


class TestFastAPIApp:
    """Тесты FastAPI endpoints."""

    def test_health_check(self):
        """GET /health возвращает 200 OK."""
        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["service"] == "bybit-chart-query-api"
            assert "version" in data

    def test_list_symbols_empty(self):
        """GET /api/v1/symbols на пустом каталоге возвращает []."""
        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get("/api/v1/symbols")

            assert response.status_code == 200
            data = response.json()
            assert data["symbols"] == []
            assert data["count"] == 0

    def test_list_symbols_with_data(self):
        """GET /api/v1/symbols возвращает список symbols из Parquet данных."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            # Создаём BTCUSDT partition
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")
            trade = RawTrade(
                symbol="BTCUSDT",
                trade_id="test-1",
                sequence=1,
                exchange_timestamp_ms=1000,
                outer_timestamp_ms=1001,
                receive_timestamp_ms=1002,
                price_ticks=100,
                qty_steps=10,
                taker_side=TakerSide.BUY,
            )
            collector.append_trade(trade)
            collector.flush()
            collector.wal.roll_segment()
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            # FastAPI client
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get("/api/v1/symbols")

            assert response.status_code == 200
            data = response.json()
            assert data["symbols"] == ["BTCUSDT"]
            assert data["count"] == 1

    def test_list_symbols_multiple_partitions(self):
        """GET /api/v1/symbols с несколькими partitions."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            # BTCUSDT
            collector1 = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")
            trade1 = RawTrade(
                symbol="BTCUSDT",
                trade_id="t1",
                sequence=1,
                exchange_timestamp_ms=1000,
                outer_timestamp_ms=1001,
                receive_timestamp_ms=1002,
                price_ticks=100,
                qty_steps=10,
                taker_side=TakerSide.BUY,
            )
            collector1.append_trade(trade1)
            collector1.flush()
            collector1.wal.roll_segment()
            collector1.wal.close_and_publish_segment(
                0, collector1.wal.offsets.closed, use_real_deserialization=True
            )
            collector1.close()

            # ETHUSDT
            collector2 = EventCollector(base_dir / "ETHUSDT", "ETHUSDT")
            trade2 = RawTrade(
                symbol="ETHUSDT",
                trade_id="t2",
                sequence=1,
                exchange_timestamp_ms=2000,
                outer_timestamp_ms=2001,
                receive_timestamp_ms=2002,
                price_ticks=200,
                qty_steps=20,
                taker_side=TakerSide.SELL,
            )
            collector2.append_trade(trade2)
            collector2.flush()
            collector2.wal.roll_segment()
            collector2.wal.close_and_publish_segment(
                0, collector2.wal.offsets.closed, use_real_deserialization=True
            )
            collector2.close()

            # FastAPI client
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get("/api/v1/symbols")

            assert response.status_code == 200
            data = response.json()
            assert data["symbols"] == ["BTCUSDT", "ETHUSDT"]
            assert data["count"] == 2
