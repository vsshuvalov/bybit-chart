"""
Тесты Analytics API endpoints (Этап 3 / Analytics API).

Проверяют: /api/v1/analytics/delta, /cvd, /vwap, /volume-profile.
"""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts.schemas import RawTrade, TakerSide

pytestmark = pytest.mark.contract


class TestAnalyticsEndpoints:
    """Тесты Analytics API endpoints."""

    def test_delta_endpoint(self):
        """GET /api/v1/analytics/delta возвращает Delta bars."""
        from packages.api.app import create_app
        from packages.bybit.collector import EventCollector

        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            # Создаём тестовые данные
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            trade1 = RawTrade(
                symbol="BTCUSDT",
                trade_id="1",
                sequence=1,
                exchange_timestamp_ms=1000,
                outer_timestamp_ms=1001,
                receive_timestamp_ms=1002,
                price_ticks=100,
                qty_steps=10,
                taker_side=TakerSide.BUY,
            )
            trade2 = RawTrade(
                symbol="BTCUSDT",
                trade_id="2",
                sequence=2,
                exchange_timestamp_ms=2000,
                outer_timestamp_ms=2001,
                receive_timestamp_ms=2002,
                price_ticks=110,
                qty_steps=5,
                taker_side=TakerSide.SELL,
            )

            collector.append_trade(trade1)
            collector.append_trade(trade2)
            collector.flush()
            collector.wal.roll_segment()
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            # Тестируем endpoint
            app = create_app(data_dir=base_dir)
            client = TestClient(app)

            response = client.get(
                "/api/v1/analytics/delta",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 0,
                    "end_ts": 10000 * 1000,
                    "interval": "1m",
                },
            )

            assert response.status_code == 200
            data = response.json()

            assert data["symbol"] == "BTCUSDT"
            assert data["interval"] == "1m"
            assert len(data["bars"]) == 1

            bar = data["bars"][0]
            assert bar["buy_volume"] == 10
            assert bar["sell_volume"] == 5
            assert bar["delta"] == 5  # 10 - 5

    def test_cvd_endpoint(self):
        """GET /api/v1/analytics/cvd возвращает CVD bars."""
        from packages.api.app import create_app
        from packages.bybit.collector import EventCollector

        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            # Trade 1: buy +10
            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="1", sequence=1,
                exchange_timestamp_ms=0, outer_timestamp_ms=0, receive_timestamp_ms=0,
                price_ticks=100, qty_steps=10, taker_side=TakerSide.BUY,
            ))

            # Trade 2: sell -5 (в следующей минуте)
            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="2", sequence=2,
                exchange_timestamp_ms=60_000, outer_timestamp_ms=60_000, receive_timestamp_ms=60_000,
                price_ticks=110, qty_steps=5, taker_side=TakerSide.SELL,
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
                "/api/v1/analytics/cvd",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 0,
                    "end_ts": 120_000 * 1000,
                    "interval": "1m",
                },
            )

            assert response.status_code == 200
            data = response.json()

            assert len(data["bars"]) == 2

            # Bar 0: CVD = 10
            assert data["bars"][0]["cvd"] == 10

            # Bar 1: CVD = 10 + (-5) = 5
            assert data["bars"][1]["cvd"] == 5

    def test_vwap_endpoint(self):
        """GET /api/v1/analytics/vwap возвращает VWAP bars."""
        from packages.api.app import create_app
        from packages.bybit.collector import EventCollector

        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="1", sequence=1,
                exchange_timestamp_ms=1000, outer_timestamp_ms=1000, receive_timestamp_ms=1000,
                price_ticks=100, qty_steps=10, taker_side=TakerSide.BUY,
            ))
            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="2", sequence=2,
                exchange_timestamp_ms=2000, outer_timestamp_ms=2000, receive_timestamp_ms=2000,
                price_ticks=110, qty_steps=20, taker_side=TakerSide.BUY,
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
                "/api/v1/analytics/vwap",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 0,
                    "end_ts": 10000 * 1000,
                    "interval": "1m",
                },
            )

            assert response.status_code == 200
            data = response.json()

            assert len(data["bars"]) == 1

            bar = data["bars"][0]
            # VWAP = (100*10 + 110*20) / 30 = 106
            assert bar["vwap_ticks"] == 106

    def test_volume_profile_endpoint(self):
        """GET /api/v1/analytics/volume-profile возвращает Volume Profile."""
        from packages.api.app import create_app
        from packages.bybit.collector import EventCollector

        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="1", sequence=1,
                exchange_timestamp_ms=1000, outer_timestamp_ms=1000, receive_timestamp_ms=1000,
                price_ticks=100, qty_steps=10, taker_side=TakerSide.BUY,
            ))
            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="2", sequence=2,
                exchange_timestamp_ms=2000, outer_timestamp_ms=2000, receive_timestamp_ms=2000,
                price_ticks=200, qty_steps=50, taker_side=TakerSide.BUY,
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
                "/api/v1/analytics/volume-profile",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 0,
                    "end_ts": 10000 * 1000,
                    "price_bin_ticks": 100,
                },
            )

            assert response.status_code == 200
            data = response.json()

            assert data["symbol"] == "BTCUSDT"
            assert "profile" in data
            assert "hvn_lvn" in data

            profile = data["profile"]
            assert len(profile["price_levels"]) == 2
            assert profile["poc_price_ticks"] == 200  # максимальный объём

    def test_analytics_endpoint_404_unknown_symbol(self):
        """Analytics endpoints возвращают 404 для неизвестного symbol."""
        from packages.api.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get(
                "/api/v1/analytics/delta",
                params={
                    "symbol": "UNKNOWN",
                    "start_ts": 0,
                    "end_ts": 10000,
                    "interval": "1m",
                },
            )

            assert response.status_code == 404
            assert "не найден" in response.json()["detail"]

    def test_analytics_endpoint_400_invalid_interval(self):
        """Analytics endpoints возвращают 400 для некорректного interval."""
        from packages.api.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get(
                "/api/v1/analytics/delta",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 0,
                    "end_ts": 10000,
                    "interval": "invalid",
                },
            )

            assert response.status_code == 400
