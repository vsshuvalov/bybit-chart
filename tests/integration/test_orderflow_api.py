"""
Тесты Time & Sales + Footprint API endpoints (Roadmap §9).

Проверяют: /api/v1/tape, /api/v1/footprint.
"""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts.schemas import RawTrade, TakerSide

pytestmark = pytest.mark.contract


class TestTapeEndpoint:
    """Тесты /api/v1/tape/{symbol}."""

    def test_tape_endpoint_success(self):
        """GET /api/v1/tape/{symbol} возвращает tape."""
        from packages.api.app import create_app
        from packages.bybit.collector import EventCollector

        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            # Создаём несколько trades
            for i in range(5):
                collector.append_trade(RawTrade(
                    symbol="BTCUSDT", trade_id=f"trade_{i}", sequence=i,
                    exchange_timestamp_ms=i * 1000, outer_timestamp_ms=i * 1000,
                    receive_timestamp_ms=i * 1000,
                    price_ticks=10000 + i, qty_steps=100 + i * 10,
                    taker_side=TakerSide.BUY if i % 2 == 0 else TakerSide.SELL,
                ))

            collector.flush()
            collector.wal.roll_segment()
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            app = create_app(data_dir=base_dir)
            client = TestClient(app)

            response = client.get(
                "/api/v1/tape/BTCUSDT",
                params={
                    "start_ts": 0,
                    "end_ts": 10000 * 1000,
                    "limit": 10,
                },
            )

            assert response.status_code == 200
            data = response.json()

            assert data["symbol"] == "BTCUSDT"
            assert "tape" in data
            assert "stats" in data
            assert len(data["tape"]) == 5

            # Проверяем структуру tape entry
            entry = data["tape"][0]
            assert "timestamp_us" in entry
            assert "price_ticks" in entry
            assert "qty_steps" in entry
            assert "aggressor_side" in entry

    def test_tape_endpoint_with_stats(self):
        """Tape endpoint включает статистику."""
        from packages.api.app import create_app
        from packages.bybit.collector import EventCollector

        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="1", sequence=1,
                exchange_timestamp_ms=1000, outer_timestamp_ms=1000, receive_timestamp_ms=1000,
                price_ticks=10000, qty_steps=100, taker_side=TakerSide.BUY,
            ))
            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="2", sequence=2,
                exchange_timestamp_ms=2000, outer_timestamp_ms=2000, receive_timestamp_ms=2000,
                price_ticks=10001, qty_steps=50, taker_side=TakerSide.SELL,
            ))

            collector.flush()
            collector.wal.roll_segment()
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            app = create_app(data_dir=base_dir)
            client = TestClient(app)

            response = client.get(
                "/api/v1/tape/BTCUSDT",
                params={"start_ts": 0, "end_ts": 10000 * 1000, "limit": 10},
            )

            data = response.json()
            stats = data["stats"]

            assert stats["total_volume"] == 150
            assert stats["buy_volume"] == 100
            assert stats["sell_volume"] == 50
            assert stats["buy_count"] == 1
            assert stats["sell_count"] == 1

    def test_tape_endpoint_404_unknown_symbol(self):
        """Tape endpoint возвращает 404 для неизвестного symbol."""
        from packages.api.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get(
                "/api/v1/tape/UNKNOWN",
                params={"start_ts": 0, "end_ts": 10000, "limit": 10},
            )

            assert response.status_code == 404


class TestFootprintEndpoint:
    """Тесты /api/v1/footprint/{symbol}."""

    def test_footprint_endpoint_success(self):
        """GET /api/v1/footprint/{symbol} возвращает footprint."""
        from packages.api.app import create_app
        from packages.bybit.collector import EventCollector

        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            # Несколько trades на разных price levels
            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="1", sequence=1,
                exchange_timestamp_ms=1000, outer_timestamp_ms=1000, receive_timestamp_ms=1000,
                price_ticks=10000, qty_steps=100, taker_side=TakerSide.BUY,
            ))
            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="2", sequence=2,
                exchange_timestamp_ms=2000, outer_timestamp_ms=2000, receive_timestamp_ms=2000,
                price_ticks=10001, qty_steps=50, taker_side=TakerSide.SELL,
            ))
            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="3", sequence=3,
                exchange_timestamp_ms=3000, outer_timestamp_ms=3000, receive_timestamp_ms=3000,
                price_ticks=10000, qty_steps=75, taker_side=TakerSide.SELL,
            ))

            collector.flush()
            collector.wal.roll_segment()
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            app = create_app(data_dir=base_dir)
            client = TestClient(app)

            response = client.get(
                "/api/v1/footprint/BTCUSDT",
                params={
                    "start_ts": 0,
                    "end_ts": 10000 * 1000,
                    "interval": "1m",
                },
            )

            assert response.status_code == 200
            data = response.json()

            assert data["symbol"] == "BTCUSDT"
            assert data["interval"] == "1m"
            assert "candles" in data
            assert len(data["candles"]) == 1

            candle = data["candles"][0]
            assert "cells" in candle
            assert "poc_price" in candle
            assert len(candle["cells"]) == 2  # 2 price levels

    def test_footprint_endpoint_with_imbalance(self):
        """Footprint endpoint включает imbalance в cells."""
        from packages.api.app import create_app
        from packages.bybit.collector import EventCollector

        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            # Strong buy imbalance на 10000
            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="1", sequence=1,
                exchange_timestamp_ms=1000, outer_timestamp_ms=1000, receive_timestamp_ms=1000,
                price_ticks=10000, qty_steps=300, taker_side=TakerSide.BUY,
            ))
            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="2", sequence=2,
                exchange_timestamp_ms=2000, outer_timestamp_ms=2000, receive_timestamp_ms=2000,
                price_ticks=10000, qty_steps=100, taker_side=TakerSide.SELL,
            ))

            collector.flush()
            collector.wal.roll_segment()
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            app = create_app(data_dir=base_dir)
            client = TestClient(app)

            response = client.get(
                "/api/v1/footprint/BTCUSDT",
                params={"start_ts": 0, "end_ts": 10000 * 1000, "interval": "1m"},
            )

            data = response.json()
            candle = data["candles"][0]
            cell = candle["cells"][0]

            assert cell["buy_volume"] == 300
            assert cell["sell_volume"] == 100
            assert cell["delta"] == 200
            assert cell["imbalance"] == 0.5  # (300-100)/400

    def test_footprint_endpoint_400_invalid_interval(self):
        """Footprint endpoint возвращает 400 для некорректного interval."""
        from packages.api.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get(
                "/api/v1/footprint/BTCUSDT",
                params={"start_ts": 0, "end_ts": 10000, "interval": "invalid"},
            )

            assert response.status_code == 400

    def test_footprint_endpoint_404_unknown_symbol(self):
        """Footprint endpoint возвращает 404 для неизвестного symbol."""
        from packages.api.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get(
                "/api/v1/footprint/UNKNOWN",
                params={"start_ts": 0, "end_ts": 10000, "interval": "1m"},
            )

            assert response.status_code == 404
