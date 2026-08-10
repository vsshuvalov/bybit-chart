"""
VWAP (Volume Weighted Average Price) calculation (Этап 3 / P3-A3).

Источник: Roadmap §9.2 (Backend-модули: Delta, CVD, VWAP, ...)

VWAP — средняя цена взвешенная по объёму:
- VWAP = Σ(price × volume) / Σ(volume)
- Используется трейдерами для оценки справедливой цены
- Институциональные трейдеры часто исполняют ордера по VWAP

Интерпретация:
- Price > VWAP → потенциально перекупленность (bullish sentiment)
- Price < VWAP → потенциально перепроданность (bearish sentiment)
- VWAP как support/resistance level

Roadmap §9: VWAP рассчитывается внутри временного окна (например, 1 день).
"""

from typing import Any


def calculate_vwap(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Рассчитать VWAP для списка RawTrade событий.

    Args:
        events: список RawTrade из ParquetReader (dict с priceTicks, qtySteps, ...)

    Returns:
        {
            "vwap_ticks": int,              # VWAP в ticks (scaled integer)
            "total_volume_steps": int,      # общий объём (qtySteps)
            "total_turnover_ticks": int,    # общий turnover (priceTicks × qtySteps)
            "trade_count": int,             # количество trades
            "min_price_ticks": int,         # минимальная цена
            "max_price_ticks": int,         # максимальная цена
        }

    Формула:
        VWAP = Σ(priceTicks × qtySteps) / Σ(qtySteps)

    Roadmap §9: VWAP сохраняется как scaled integer (vwap_ticks),
    конверсия в price через PRICE_TICK на стороне frontend.
    """
    if not events:
        return {
            "vwap_ticks": 0,
            "total_volume_steps": 0,
            "total_turnover_ticks": 0,
            "trade_count": 0,
            "min_price_ticks": 0,
            "max_price_ticks": 0,
        }

    total_turnover_ticks = 0
    total_volume_steps = 0
    trade_count = 0
    prices = []

    for event in events:
        # Фильтрация: только RawTrade
        if event.get("eventType") != "RawTrade":
            continue

        price_ticks = event.get("priceTicks", 0)
        qty_steps = event.get("qtySteps", 0)

        total_turnover_ticks += price_ticks * qty_steps
        total_volume_steps += qty_steps
        trade_count += 1
        prices.append(price_ticks)

    if total_volume_steps == 0:
        vwap_ticks = 0
    else:
        vwap_ticks = total_turnover_ticks // total_volume_steps  # integer division

    min_price_ticks = min(prices) if prices else 0
    max_price_ticks = max(prices) if prices else 0

    return {
        "vwap_ticks": vwap_ticks,
        "total_volume_steps": total_volume_steps,
        "total_turnover_ticks": total_turnover_ticks,
        "trade_count": trade_count,
        "min_price_ticks": min_price_ticks,
        "max_price_ticks": max_price_ticks,
    }


def aggregate_vwap_by_interval(
    events: list[dict[str, Any]],
    interval_us: int,
) -> list[dict[str, Any]]:
    """Агрегировать VWAP по временным окнам.

    Args:
        events: список RawTrade из ParquetReader
        interval_us: интервал в microseconds (1m = 60_000_000)

    Returns:
        Список VWAP bars:
        [
            {
                "timestamp_us": int,
                "vwap_ticks": int,
                "total_volume_steps": int,
                "total_turnover_ticks": int,
                "trade_count": int,
                "min_price_ticks": int,
                "max_price_ticks": int,
            },
            ...
        ]

    Roadmap §9: VWAP bars синхронизированы с OHLC candles.
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

    # Расчёт VWAP для каждого окна
    bars = []
    for bar_ts in sorted(bars_map.keys()):
        bar_events = bars_map[bar_ts]
        vwap_stats = calculate_vwap(bar_events)

        bars.append({
            "timestamp_us": bar_ts,
            **vwap_stats,
        })

    return bars


def calculate_cumulative_vwap(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Рассчитать cumulative VWAP (running VWAP от начала периода).

    Roadmap §9: Cumulative VWAP часто используется для анализа дневного диапазона.
    VWAP пересчитывается с начала торгового дня, накапливая turnover и volume.

    Args:
        events: список RawTrade, отсортированный по timestampUs

    Returns:
        Список точек cumulative VWAP:
        [
            {
                "timestamp_us": int,
                "vwap_ticks": int,            # cumulative VWAP до этой точки
                "total_volume_steps": int,    # cumulative volume
                "total_turnover_ticks": int,  # cumulative turnover
            },
            ...
        ]

    Пример:
        events = [
            {"timestampUs": 1000, "priceTicks": 100, "qtySteps": 10},
            {"timestampUs": 2000, "priceTicks": 110, "qtySteps": 20},
        ]
        cumulative = calculate_cumulative_vwap(events)
        # [
        #   {"timestamp_us": 1000, "vwap_ticks": 100, "total_volume_steps": 10},
        #   {"timestamp_us": 2000, "vwap_ticks": 106, "total_volume_steps": 30},
        #   # VWAP[1] = (100*10 + 110*20) / (10+20) = 3200/30 = 106
        # ]
    """
    if not events:
        return []

    cumulative_points = []
    cumulative_turnover = 0
    cumulative_volume = 0

    for event in events:
        if event.get("eventType") != "RawTrade":
            continue

        price_ticks = event.get("priceTicks", 0)
        qty_steps = event.get("qtySteps", 0)
        timestamp_us = event.get("timestampUs", 0)

        cumulative_turnover += price_ticks * qty_steps
        cumulative_volume += qty_steps

        if cumulative_volume > 0:
            vwap_ticks = cumulative_turnover // cumulative_volume
        else:
            vwap_ticks = 0

        cumulative_points.append({
            "timestamp_us": timestamp_us,
            "vwap_ticks": vwap_ticks,
            "total_volume_steps": cumulative_volume,
            "total_turnover_ticks": cumulative_turnover,
        })

    return cumulative_points
