"""
Тесты OHLC aggregation (P3-S3-004).

Проверяют: aggregate_ohlc(), parse_interval(), GET /api/v1/ohlc endpoint.
"""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts.schemas import RawTrade, TakerSide
from packages.api.aggregation import aggregate_ohlc, parse_interval
from packages.api.app import create_app
from packages.bybit.collector import EventCollector

pytestmark = pytest.mark.contract


class TestParseInterval:
    """Тесты parse_interval()."""

    def test_parse_minutes(self):
        """Парсинг минут."""
        assert parse_interval("1m") == 60 * 1_000_000
        assert parse_interval("5m") == 5 * 60 * 1_000_000
        assert parse_interval("15m") == 15 * 60 * 1_000_000

    def test_parse_hours(self):
        """Парсинг часов."""
        assert parse_interval("1h") == 60 * 60 * 1_000_000
        assert parse_interval("4h") == 4 * 60 * 60 * 1_000_000

    def test_parse_days(self):
        """Парсинг дней."""
        assert parse_interval("1d") == 24 * 60 * 60 * 1_000_000

    def test_invalid_format_raises(self):
        """Некорректный формат → ValueError."""
        with pytest.raises(ValueError, match="Некорректный unit"):
            parse_interval("1x")

        with pytest.raises(ValueError, match="Некорректное число"):
            parse_interval("abcm")

        with pytest.raises(ValueError, match="не может быть пустым"):
            parse_interval("")


class TestAggregateOHLC:
    """Тесты aggregate_ohlc()."""

    def test_aggregate_single_candle(self):
        """Один candle из нескольких trades."""
        events = [
            {
                "timestampUs": 1000000,  # 1s
                "eventType": "RawTrade",
                "priceTicks": 100,
                "qtySteps": 10,
            },
            {
                "timestampUs": 1500000,  # 1.5s (тот же candle)
                "eventType": "RawTrade",
                "priceTicks": 110,
                "qtySteps": 20,
            },
            {
                "timestampUs": 1800000,  # 1.8s (тот же candle)
                "eventType": "RawTrade",
                "priceTicks": 105,
                "qtySteps": 15,
            },
        ]

        candles = aggregate_ohlc(events, interval_us=60 * 1_000_000)  # 1m candles

        assert len(candles) == 1
        candle = candles[0]
        assert candle["timestamp_us"] == 0  # floor(1s / 60s) * 60s = 0
        assert candle["open_ticks"] == 100  # первая цена
        assert candle["high_ticks"] == 110  # max
        assert candle["low_ticks"] == 100  # min
        assert candle["close_ticks"] == 105  # последняя цена
        assert candle["volume_steps"] == 45  # 10+20+15
        assert candle["trade_count"] == 3

    def test_aggregate_multiple_candles(self):
        """Несколько candles."""
        events = [
            {
                "timestampUs": 0,
                "eventType": "RawTrade",
                "priceTicks": 100,
                "qtySteps": 10,
            },
            {
                "timestampUs": 60 * 1_000_000,  # следующая минута
                "eventType": "RawTrade",
                "priceTicks": 200,
                "qtySteps": 20,
            },
            {
                "timestampUs": 120 * 1_000_000,  # ещё минута
                "eventType": "RawTrade",
                "priceTicks": 300,
                "qtySteps": 30,
            },
        ]

        candles = aggregate_ohlc(events, interval_us=60 * 1_000_000)

        assert len(candles) == 3
        assert candles[0]["open_ticks"] == 100
        assert candles[1]["open_ticks"] == 200
        assert candles[2]["open_ticks"] == 300

    def test_aggregate_filters_non_trades(self):
        """Фильтрует события не-RawTrade."""
        events = [
            {
                "timestampUs": 1000000,
                "eventType": "RawTrade",
                "priceTicks": 100,
                "qtySteps": 10,
            },
            {
                "timestampUs": 1500000,
                "eventType": "BookCheckpoint",  # не trade
                "priceTicks": 999,
                "qtySteps": 999,
            },
        ]

        candles = aggregate_ohlc(events, interval_us=60 * 1_000_000)

        assert len(candles) == 1
        assert candles[0]["volume_steps"] == 10  # только RawTrade

    def test_aggregate_empty_events(self):
        """Пустой список → пустой результат."""
        candles = aggregate_ohlc([], interval_us=60 * 1_000_000)
        assert candles == []

    def test_candles_sorted_by_timestamp(self):
        """Candles отсортированы по timestamp."""
        events = [
            {
                "timestampUs": 120 * 1_000_000,
                "eventType": "RawTrade",
                "priceTicks": 300,
                "qtySteps": 30,
            },
            {
                "timestampUs": 0,
                "eventType": "RawTrade",
                "priceTicks": 100,
                "qtySteps": 10,
            },
            {
                "timestampUs": 60 * 1_000_000,
                "eventType": "RawTrade",
                "priceTicks": 200,
                "qtySteps": 20,
            },
        ]

        candles = aggregate_ohlc(events, interval_us=60 * 1_000_000)

        assert len(candles) == 3
        assert candles[0]["timestamp_us"] == 0
        assert candles[1]["timestamp_us"] == 60 * 1_000_000
        assert candles[2]["timestamp_us"] == 120 * 1_000_000


class TestOHLCEndpoint:
    """Тесты GET /api/v1/ohlc."""

    def test_get_ohlc_basic(self):
        """GET /api/v1/ohlc возвращает candles."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            # Создаём trades в разных минутах
            trades = [
                RawTrade(
                    symbol="BTCUSDT",
                    trade_id="t1",
                    sequence=1,
                    exchange_timestamp_ms=0,  # 0 µs
                    outer_timestamp_ms=1,
                    receive_timestamp_ms=2,
                    price_ticks=100,
                    qty_steps=10,
                    taker_side=TakerSide.BUY,
                ),
                RawTrade(
                    symbol="BTCUSDT",
                    trade_id="t2",
                    sequence=2,
                    exchange_timestamp_ms=60_000,  # 60s = 60_000_000 µs
                    outer_timestamp_ms=60_001,
                    receive_timestamp_ms=60_002,
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

            response = client.get(
                "/api/v1/ohlc",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 0,
                    "end_ts": 120_000 * 1000,  # 120s
                    "interval": "1m",
                },
            )

            assert response.status_code == 200
            data = response.json()

            assert data["symbol"] == "BTCUSDT"
            assert data["interval"] == "1m"
            assert data["count"] == 2
            assert len(data["candles"]) == 2

            # Проверка первого candle
            candle1 = data["candles"][0]
            assert candle1["open_ticks"] == 100
            assert candle1["close_ticks"] == 100
            assert candle1["volume_steps"] == 10
            assert candle1["trade_count"] == 1

            # Проверка второго candle
            candle2 = data["candles"][1]
            assert candle2["open_ticks"] == 200

    def test_get_ohlc_invalid_interval(self):
        """Некорректный interval → 400 Bad Request."""
        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get(
                "/api/v1/ohlc",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 0,
                    "end_ts": 1000,
                    "interval": "999x",  # некорректный
                },
            )

            assert response.status_code == 400

    def test_get_ohlc_symbol_not_found(self):
        """Несуществующий symbol → 404 Not Found."""
        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            response = client.get(
                "/api/v1/ohlc",
                params={
                    "symbol": "NONEXISTENT",
                    "start_ts": 0,
                    "end_ts": 1000,
                    "interval": "1m",
                },
            )

            assert response.status_code == 404

    def test_get_ohlc_empty_result(self):
        """Диапазон без данных → пустой список candles."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            trade = RawTrade(
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
                "/api/v1/ohlc",
                params={
                    "symbol": "BTCUSDT",
                    "start_ts": 5000 * 1000,
                    "end_ts": 6000 * 1000,
                    "interval": "1m",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 0
            assert data["candles"] == []
