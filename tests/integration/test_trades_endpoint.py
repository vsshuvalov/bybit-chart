"""
Тесты Trades endpoint (P3-S3-003).

Проверяют: GET /api/v1/trades с валидацией, фильтрацией, pagination, error handling.
"""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts.schemas import RawTrade, TakerSide
from packages.api.app import create_app
from packages.bybit.collector import EventCollector

pytestmark = pytest.mark.contract


class TestTradesEndpoint:
    """Тесты GET /api/v1/trades."""

    def test_get_trades_basic(self):
        """GET /api/v1/trades возвращает события из Parquet."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            # Создаём тестовые данные
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            trades = [
                RawTrade(
                    symbol="BTCUSDT",
                    trade_id="trade-1",
                    sequence=1,
                    exchange_timestamp_ms=1000,  # 1000000 µs
                    outer_timestamp_ms=1001,
                    receive_timestamp_ms=1002,
                    price_ticks=100,
                    qty_steps=10,
                    taker_side=TakerSide.BUY,
                ),
                RawTrade(
                    symbol="BTCUSDT",
                    trade_id="trade-2",
                    sequence=2,
                    exchange_timestamp_ms=2000,  # 2000000 µs
                    outer_timestamp_ms=2001,
                    receive_timestamp_ms=2002,
                    price_ticks=200,
                    qty_steps=20,
                    taker_side=TakerSide.SELL,
                ),
            ]

            for trade in trades:
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

            # Запрос trades
            response = client.get(
                "/api/v1/trades",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 0,
                    "end_ts": 10000 * 1000,  # 10ms
                },
            )

            assert response.status_code == 200
            data = response.json()

            assert data["symbol"] == "BTCUSDT"
            assert data["count"] == 2
            assert data["has_more"] is False
            assert len(data["events"]) == 2
            assert data["events"][0]["priceTicks"] == 100
            assert data["events"][1]["priceTicks"] == 200

    def test_get_trades_with_time_filter(self):
        """Фильтрация по временному диапазону работает."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            trades = [
                RawTrade(
                    symbol="BTCUSDT",
                    trade_id="trade-1",
                    sequence=1,
                    exchange_timestamp_ms=1000,
                    outer_timestamp_ms=1001,
                    receive_timestamp_ms=1002,
                    price_ticks=100,
                    qty_steps=10,
                    taker_side=TakerSide.BUY,
                ),
                RawTrade(
                    symbol="BTCUSDT",
                    trade_id="trade-2",
                    sequence=2,
                    exchange_timestamp_ms=2000,
                    outer_timestamp_ms=2001,
                    receive_timestamp_ms=2002,
                    price_ticks=200,
                    qty_steps=20,
                    taker_side=TakerSide.SELL,
                ),
                RawTrade(
                    symbol="BTCUSDT",
                    trade_id="trade-3",
                    sequence=3,
                    exchange_timestamp_ms=3000,
                    outer_timestamp_ms=3001,
                    receive_timestamp_ms=3002,
                    price_ticks=300,
                    qty_steps=30,
                    taker_side=TakerSide.BUY,
                ),
            ]

            for trade in trades:
                collector.append_trade(trade)

            collector.flush()
            collector.wal.roll_segment()
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            app = create_app(data_dir=td)
            client = TestClient(app)

            # Диапазон: 1-2.5ms (только trade-1 и trade-2)
            response = client.get(
                "/api/v1/trades",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 1000 * 1000,
                    "end_ts": 2500 * 1000,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 2
            assert data["events"][0]["priceTicks"] == 100
            assert data["events"][1]["priceTicks"] == 200

    def test_get_trades_with_limit(self):
        """Limit и has_more работают корректно."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            # Создаём 5 trades
            for i in range(5):
                trade = RawTrade(
                    symbol="BTCUSDT",
                    trade_id=f"trade-{i}",
                    sequence=i,
                    exchange_timestamp_ms=1000 + i * 100,
                    outer_timestamp_ms=1001 + i * 100,
                    receive_timestamp_ms=1002 + i * 100,
                    price_ticks=100 + i * 10,
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

            app = create_app(data_dir=td)
            client = TestClient(app)

            # Limit = 3
            response = client.get(
                "/api/v1/trades",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 0,
                    "end_ts": 10000 * 1000,
                    "limit": 3,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 3
            assert data["has_more"] is True  # есть ещё данные

    def test_get_trades_with_event_type_filter(self):
        """Фильтр по event_type работает."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            trade = RawTrade(
                symbol="BTCUSDT",
                trade_id="trade-1",
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

            app = create_app(data_dir=td)
            client = TestClient(app)

            # Фильтр по RawTrade
            response = client.get(
                "/api/v1/trades",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 0,
                    "end_ts": 10000 * 1000,
                    "event_type": "RawTrade",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 1

    def test_get_trades_invalid_time_range(self):
        """start_ts >= end_ts → 400 Bad Request."""
        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get(
                "/api/v1/trades",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 2000,
                    "end_ts": 1000,  # end_ts < start_ts
                },
            )

            assert response.status_code == 400

    def test_get_trades_missing_params(self):
        """Отсутствующие обязательные параметры → 422 Unprocessable Entity."""
        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            # Без symbol
            response = client.get(
                "/api/v1/trades",
                params={"start_ts": 0, "end_ts": 1000},
            )

            assert response.status_code == 422  # FastAPI validation error

    def test_get_trades_symbol_not_found(self):
        """Несуществующий symbol → 404 Not Found."""
        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get(
                "/api/v1/trades",
                params={
                    "symbol": "NONEXISTENT",
                    "start_ts": 0,
                    "end_ts": 1000,
                },
            )

            assert response.status_code == 404

    def test_get_trades_empty_result(self):
        """Диапазон без данных → пустой список."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            trade = RawTrade(
                symbol="BTCUSDT",
                trade_id="trade-1",
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

            app = create_app(data_dir=td)
            client = TestClient(app)

            # Диапазон не пересекается
            response = client.get(
                "/api/v1/trades",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 5000 * 1000,
                    "end_ts": 6000 * 1000,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 0
            assert data["has_more"] is False
