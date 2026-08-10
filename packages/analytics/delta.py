"""
Delta calculation для Order Flow анализа (Этап 3 / P3-A1).

Источник: Roadmap §9.2 (Backend-модули: Delta, CVD, VWAP, ...)

Delta — разница между buy volume и sell volume:
- TakerSide.BUY → +qtySteps (aggressive buy, покупатели атакуют ask)
- TakerSide.SELL → -qtySteps (aggressive sell, продавцы атакуют bid)

Delta > 0: больше aggressive buyers (bullish pressure)
Delta < 0: больше aggressive sellers (bearish pressure)

Roadmap §9: Delta агрегируется по временным окнам (1m, 5m, ...).
"""

from typing import Any


def calculate_delta(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Рассчитать Delta для списка RawTrade событий.

    Args:
        events: список RawTrade из ParquetReader (dict с qtySteps, takerSide, ...)

    Returns:
        {
            "buy_volume": int,      # сумма qtySteps для TakerSide.BUY
            "sell_volume": int,     # сумма qtySteps для TakerSide.SELL
            "delta": int,           # buy_volume - sell_volume
            "total_volume": int,    # buy_volume + sell_volume
            "trade_count": int,     # количество trades
            "buy_count": int,       # количество buy trades
            "sell_count": int,      # количество sell trades
        }
    """
    buy_volume = 0
    sell_volume = 0
    buy_count = 0
    sell_count = 0

    for event in events:
        # Roadmap §6: eventType для фильтрации (только RawTrade имеют takerSide)
        if event.get("eventType") != "RawTrade":
            continue

        qty_steps = event.get("qtySteps", 0)
        # Поле может называться "takerSide" (Parquet) или "taker_side" (Python)
        taker_side = event.get("takerSide") or event.get("taker_side")

        if taker_side == "Buy":
            buy_volume += qty_steps
            buy_count += 1
        elif taker_side == "Sell":
            sell_volume += qty_steps
            sell_count += 1

    delta = buy_volume - sell_volume
    total_volume = buy_volume + sell_volume
    trade_count = buy_count + sell_count

    return {
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "delta": delta,
        "total_volume": total_volume,
        "trade_count": trade_count,
        "buy_count": buy_count,
        "sell_count": sell_count,
    }


def aggregate_delta_by_interval(
    events: list[dict[str, Any]],
    interval_us: int,
) -> list[dict[str, Any]]:
    """Агрегировать Delta по временным окнам.

    Args:
        events: список RawTrade из ParquetReader
        interval_us: интервал в microseconds (1m = 60_000_000)

    Returns:
        Список Delta bars:
        [
            {
                "timestamp_us": int,
                "buy_volume": int,
                "sell_volume": int,
                "delta": int,
                "total_volume": int,
                "trade_count": int,
                "buy_count": int,
                "sell_count": int,
            },
            ...
        ]

    Roadmap §9: Delta bars синхронизированы с OHLC candles (тот же interval).
    """
    if not events:
        return []

    # Группировка по временным окнам
    bars_map: dict[int, list[dict[str, Any]]] = {}

    for event in events:
        if event.get("eventType") != "RawTrade":
            continue

        timestamp_us = event.get("timestampUs", 0)
        bar_ts = (timestamp_us // interval_us) * interval_us

        if bar_ts not in bars_map:
            bars_map[bar_ts] = []

        bars_map[bar_ts].append(event)

    # Расчёт Delta для каждого окна
    bars = []
    for bar_ts in sorted(bars_map.keys()):
        bar_events = bars_map[bar_ts]
        delta_stats = calculate_delta(bar_events)

        bars.append({
            "timestamp_us": bar_ts,
            **delta_stats,
        })

    return bars
