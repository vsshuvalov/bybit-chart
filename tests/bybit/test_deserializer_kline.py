"""
Тесты для deserializer_kline (Roadmap §8.2 RPI feed).
"""

import pytest
from decimal import Decimal

from packages.bybit.deserializer_kline import deserialize_kline


def test_deserialize_kline_basic():
    """Базовый тест десериализации kline."""
    message = {
        "topic": "kline.1.BTCUSDT",
        "type": "snapshot",
        "ts": 1672324800000,
        "data": [
            {
                "start": 1672324800000,
                "end": 1672324859999,
                "interval": "1",
                "open": "16649.5",
                "close": "16650",
                "high": "16650.5",
                "low": "16649",
                "volume": "2.343",
                "turnover": "39007.1165",
                "confirm": False,
                "timestamp": 1672324800000,
            }
        ],
    }

    kline = deserialize_kline(message, receive_timestamp_ms=1672324850000)

    assert kline.venue == "BYBIT"
    assert kline.category == "linear"
    assert kline.symbol == "BTCUSDT"
    assert kline.interval == "1"
    assert kline.start_timestamp_ms == 1672324800000
    assert kline.end_timestamp_ms == 1672324859999
    assert kline.open == Decimal("16649.5")
    assert kline.high == Decimal("16650.5")
    assert kline.low == Decimal("16649")
    assert kline.close == Decimal("16650")
    assert kline.volume == Decimal("2.343")
    assert kline.turnover == Decimal("39007.1165")
    assert kline.confirm is False
    assert kline.exchange_timestamp_ms == 1672324800000
    assert kline.receive_timestamp_ms == 1672324850000


def test_deserialize_kline_confirmed():
    """Тест финальной (confirmed) свечи."""
    message = {
        "topic": "kline.1.ETHUSDT",
        "type": "snapshot",
        "ts": 1672324860000,
        "data": [
            {
                "start": 1672324800000,
                "end": 1672324859999,
                "interval": "1",
                "open": "1200.5",
                "close": "1201.0",
                "high": "1202.0",
                "low": "1200.0",
                "volume": "100.5",
                "turnover": "120600.25",
                "confirm": True,
                "timestamp": 1672324860000,
            }
        ],
    }

    kline = deserialize_kline(message)

    assert kline.symbol == "ETHUSDT"
    assert kline.confirm is True


def test_deserialize_kline_missing_topic():
    """Тест ошибки при отсутствии topic."""
    message = {
        "type": "snapshot",
        "ts": 1672324800000,
        "data": [{"start": 1672324800000}],
    }

    with pytest.raises(ValueError, match="Не kline topic"):
        deserialize_kline(message)


def test_deserialize_kline_wrong_topic():
    """Тест ошибки при неправильном topic."""
    message = {
        "topic": "publicTrade.BTCUSDT",
        "ts": 1672324800000,
        "data": [{"start": 1672324800000}],
    }

    with pytest.raises(ValueError, match="Не kline topic"):
        deserialize_kline(message)


def test_deserialize_kline_empty_data():
    """Тест ошибки при пустом data array."""
    message = {
        "topic": "kline.1.BTCUSDT",
        "ts": 1672324800000,
        "data": [],
    }

    with pytest.raises(ValueError, match="Пустой data array"):
        deserialize_kline(message)


def test_deserialize_kline_missing_required_fields():
    """Тест ошибки при отсутствии обязательных полей."""
    message = {
        "topic": "kline.1.BTCUSDT",
        "ts": 1672324800000,
        "data": [
            {
                "start": 1672324800000,
                # missing: end, open, high, low, close, volume, turnover
            }
        ],
    }

    with pytest.raises(ValueError, match="Отсутствует поле"):
        deserialize_kline(message)


def test_deserialize_kline_decimal_conversion_error():
    """Тест ошибки при невалидном Decimal."""
    message = {
        "topic": "kline.1.BTCUSDT",
        "ts": 1672324800000,
        "data": [
            {
                "start": 1672324800000,
                "end": 1672324859999,
                "interval": "1",
                "open": "invalid_number",
                "close": "16650",
                "high": "16650.5",
                "low": "16649",
                "volume": "2.343",
                "turnover": "39007.1165",
                "confirm": False,
            }
        ],
    }

    with pytest.raises(ValueError, match="Ошибка преобразования Decimal"):
        deserialize_kline(message)


def test_deserialize_kline_multiple_intervals():
    """Тест разных интервалов."""
    intervals = ["1", "3", "5", "15", "30", "60", "D"]

    for interval in intervals:
        message = {
            "topic": f"kline.{interval}.BTCUSDT",
            "ts": 1672324800000,
            "data": [
                {
                    "start": 1672324800000,
                    "end": 1672324859999,
                    "interval": interval,
                    "open": "16649.5",
                    "close": "16650",
                    "high": "16650.5",
                    "low": "16649",
                    "volume": "2.343",
                    "turnover": "39007.1165",
                    "confirm": False,
                }
            ],
        }

        kline = deserialize_kline(message)
        assert kline.interval == interval
