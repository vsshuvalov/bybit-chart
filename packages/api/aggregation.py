"""
OHLC Aggregation для server-side candles (Stage 3 / P3-S3-004).

Источник: Roadmap §7 (Query & Aggregation)

Агрегирует RawTrade → OHLC candles для визуализации.
"""

from decimal import Decimal
from typing import Any


def aggregate_ohlc(
    events: list[dict[str, Any]],
    interval_us: int,
) -> list[dict[str, Any]]:
    """Агрегировать события → OHLC candles.

    Args:
        events: список событий (RawTrade) из ParquetReader
        interval_us: интервал candle в microseconds

    Returns:
        Список candles с OHLC + volume + trade_count

    Пример:
        events = [
            {"timestampUs": 1000000, "priceTicks": 100, "qtySteps": 10},
            {"timestampUs": 1500000, "priceTicks": 110, "qtySteps": 20},
            {"timestampUs": 2000000, "priceTicks": 105, "qtySteps": 15},
        ]
        candles = aggregate_ohlc(events, interval_us=1_000_000)  # 1s candles
        # [
        #   {timestamp_us: 1000000, open: 100, high: 110, low: 100, close: 110, ...},
        #   {timestamp_us: 2000000, open: 105, high: 105, low: 105, close: 105, ...},
        # ]
    """
    if not events:
        return []

    # Фильтруем только RawTrade (у них есть priceTicks/qtySteps)
    trades = [e for e in events if e.get("eventType") == "RawTrade"]

    if not trades:
        return []

    # Группировка по временным окнам
    candles_map: dict[int, dict[str, Any]] = {}

    for trade in trades:
        timestamp_us = trade["timestampUs"]
        price_ticks = trade["priceTicks"]
        qty_steps = trade["qtySteps"]

        # Определяем candle timestamp (floor к началу интервала)
        candle_ts = (timestamp_us // interval_us) * interval_us

        if candle_ts not in candles_map:
            # Новая candle
            candles_map[candle_ts] = {
                "timestamp_us": candle_ts,
                "open_ticks": price_ticks,
                "high_ticks": price_ticks,
                "low_ticks": price_ticks,
                "close_ticks": price_ticks,
                "volume_steps": qty_steps,
                "trade_count": 1,
            }
        else:
            # Обновление существующей candle
            candle = candles_map[candle_ts]
            candle["high_ticks"] = max(candle["high_ticks"], price_ticks)
            candle["low_ticks"] = min(candle["low_ticks"], price_ticks)
            candle["close_ticks"] = price_ticks  # последняя цена
            candle["volume_steps"] += qty_steps
            candle["trade_count"] += 1

    # Сортировка по timestamp
    candles = sorted(candles_map.values(), key=lambda c: c["timestamp_us"])

    return candles


def parse_interval(interval_str: str) -> int:
    """Распарсить interval string → microseconds.

    Args:
        interval_str: "1m", "5m", "15m", "1h", "4h", "1d"

    Returns:
        Интервал в microseconds

    Raises:
        ValueError: некорректный формат

    Пример:
        parse_interval("1m") → 60_000_000 (60 секунд в µs)
        parse_interval("1h") → 3_600_000_000 (1 час в µs)
    """
    if not interval_str:
        raise ValueError("Interval не может быть пустым")

    # Парсинг: число + unit
    if interval_str[-1] not in ("m", "h", "d"):
        raise ValueError(f"Некорректный unit в interval: {interval_str}")

    try:
        value = int(interval_str[:-1])
    except ValueError:
        raise ValueError(f"Некорректное число в interval: {interval_str}")

    unit = interval_str[-1]

    # Конверсия в microseconds
    if unit == "m":
        return value * 60 * 1_000_000  # минуты → µs
    elif unit == "h":
        return value * 60 * 60 * 1_000_000  # часы → µs
    elif unit == "d":
        return value * 24 * 60 * 60 * 1_000_000  # дни → µs

    raise ValueError(f"Неизвестный unit: {unit}")
