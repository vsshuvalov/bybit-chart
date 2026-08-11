"""
Bybit kline deserializer (Roadmap §8.2 RPI feed).

Преобразует WebSocket kline.{interval}.{symbol} → RawKline contract.
"""

import time
from decimal import Decimal
from typing import Any

from contracts.raw_kline import RawKline


def deserialize_kline(
    message: dict[str, Any],
    receive_timestamp_ms: int | None = None,
) -> RawKline:
    """Десериализовать kline.{interval}.{symbol} → RawKline.

    Args:
        message: JSON сообщение от Bybit WebSocket
        receive_timestamp_ms: время получения (если None — берётся текущее)

    Returns:
        RawKline contract

    Raises:
        ValueError: если message не содержит обязательные поля

    Example message:
        {
            "topic": "kline.1.BTCUSDT",
            "type": "snapshot",
            "ts": 1672324800000,
            "data": [{
                "start": 1672324800000,
                "end": 1672324859999,
                "interval": "1",
                "open": "16649.5",
                "close": "16650",
                "high": "16650.5",
                "low": "16649",
                "volume": "2.343",
                "turnover": "39007.1165",
                "confirm": false,
                "timestamp": 1672324800000
            }]
        }
    """
    if receive_timestamp_ms is None:
        receive_timestamp_ms = int(time.time() * 1000)

    # Валидация
    topic = message.get("topic", "")
    if not topic.startswith("kline."):
        raise ValueError(f"Не kline topic: {topic}")

    # Парсинг topic: kline.{interval}.{symbol}
    parts = topic.split(".")
    if len(parts) != 3:
        raise ValueError(f"Неправильный формат topic: {topic}")

    interval = parts[1]
    symbol = parts[2]

    # Извлечение данных
    data_list = message.get("data", [])
    if not data_list:
        raise ValueError("Пустой data array в kline message")

    data = data_list[0]  # kline всегда содержит 1 элемент

    # Exchange timestamp
    exchange_timestamp_ms = message.get("ts")
    if exchange_timestamp_ms is None:
        raise ValueError("Отсутствует поле 'ts' в сообщении")

    # Kline fields
    start_timestamp_ms = data.get("start")
    end_timestamp_ms = data.get("end")
    open_str = data.get("open")
    high_str = data.get("high")
    low_str = data.get("low")
    close_str = data.get("close")
    volume_str = data.get("volume")
    turnover_str = data.get("turnover")
    confirm = data.get("confirm", False)

    # Валидация обязательных полей
    if start_timestamp_ms is None:
        raise ValueError("Отсутствует поле 'start' в data")
    if end_timestamp_ms is None:
        raise ValueError("Отсутствует поле 'end' в data")
    if open_str is None:
        raise ValueError("Отсутствует поле 'open' в data")
    if high_str is None:
        raise ValueError("Отсутствует поле 'high' в data")
    if low_str is None:
        raise ValueError("Отсутствует поле 'low' в data")
    if close_str is None:
        raise ValueError("Отсутствует поле 'close' в data")
    if volume_str is None:
        raise ValueError("Отсутствует поле 'volume' в data")
    if turnover_str is None:
        raise ValueError("Отсутствует поле 'turnover' в data")

    # Decimal conversion
    try:
        open_dec = Decimal(open_str)
        high_dec = Decimal(high_str)
        low_dec = Decimal(low_str)
        close_dec = Decimal(close_str)
        volume_dec = Decimal(volume_str)
        turnover_dec = Decimal(turnover_str)
    except Exception as exc:
        raise ValueError(f"Ошибка преобразования Decimal: {exc}") from exc

    return RawKline(
        venue="BYBIT",
        category="linear",
        symbol=symbol,
        interval=interval,
        start_timestamp_ms=start_timestamp_ms,
        end_timestamp_ms=end_timestamp_ms,
        open=open_dec,
        high=high_dec,
        low=low_dec,
        close=close_dec,
        volume=volume_dec,
        turnover=turnover_dec,
        confirm=confirm,
        exchange_timestamp_ms=exchange_timestamp_ms,
        receive_timestamp_ms=receive_timestamp_ms,
    )
