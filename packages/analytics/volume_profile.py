"""
Volume Profile calculation для Order Flow анализа (Этап 3 / P3-A4).

Источник: Roadmap §9.2 (Backend-модули: Delta, CVD, VWAP, Volume Profile, ...)

Volume Profile — распределение объёма по ценовым уровням:
- Показывает, на каких ценах произошло больше всего торговли
- Используется для определения зон поддержки/сопротивления

Ключевые концепции:
- POC (Point of Control) — уровень с максимальным объёмом
- Value Area — диапазон, содержащий 70% объёма
- VAH (Value Area High) — верхняя граница Value Area
- VAL (Value Area Low) — нижняя граница Value Area
- HVN (High Volume Node) — уровни с высоким объёмом (support/resistance)
- LVN (Low Volume Node) — уровни с низким объёмом (слабые зоны)

Roadmap §9: Volume Profile рассчитывается для временного окна (день, неделя, сессия).
"""

from typing import Any


def calculate_volume_profile(
    events: list[dict[str, Any]],
    price_bin_ticks: int = 100,
) -> dict[str, Any]:
    """Рассчитать Volume Profile для списка RawTrade событий.

    Args:
        events: список RawTrade из ParquetReader
        price_bin_ticks: размер ценового bin в ticks (для группировки)
                         Например, для BTCUSDT: 100 ticks = $1.00

    Returns:
        {
            "price_levels": [
                {
                    "price_ticks": int,        # цена bin (округлённая)
                    "volume_steps": int,       # объём на этом уровне
                    "trade_count": int,        # количество trades
                    "buy_volume_steps": int,   # buy volume
                    "sell_volume_steps": int,  # sell volume
                },
                ...
            ],
            "poc_price_ticks": int,            # Point of Control
            "value_area_high_ticks": int,      # VAH
            "value_area_low_ticks": int,       # VAL
            "total_volume_steps": int,         # общий объём
            "value_area_volume_steps": int,    # объём в Value Area (70%)
        }

    Roadmap §9: Volume Profile группирует trades по ценовым bins,
    затем находит POC и Value Area.
    """
    if not events:
        return {
            "price_levels": [],
            "poc_price_ticks": 0,
            "value_area_high_ticks": 0,
            "value_area_low_ticks": 0,
            "total_volume_steps": 0,
            "value_area_volume_steps": 0,
        }

    # Группировка по ценовым bins
    price_bins: dict[int, dict[str, Any]] = {}

    for event in events:
        if event.get("eventType") != "RawTrade":
            continue

        price_ticks = event.get("priceTicks", 0)
        qty_steps = event.get("qtySteps", 0)
        taker_side = event.get("takerSide") or event.get("taker_side")

        # Округляем цену к bin
        bin_price = (price_ticks // price_bin_ticks) * price_bin_ticks

        if bin_price not in price_bins:
            price_bins[bin_price] = {
                "price_ticks": bin_price,
                "volume_steps": 0,
                "trade_count": 0,
                "buy_volume_steps": 0,
                "sell_volume_steps": 0,
            }

        price_bins[bin_price]["volume_steps"] += qty_steps
        price_bins[bin_price]["trade_count"] += 1

        if taker_side == "Buy":
            price_bins[bin_price]["buy_volume_steps"] += qty_steps
        elif taker_side == "Sell":
            price_bins[bin_price]["sell_volume_steps"] += qty_steps

    # Сортируем по цене
    price_levels = sorted(price_bins.values(), key=lambda x: x["price_ticks"])

    if not price_levels:
        return {
            "price_levels": [],
            "poc_price_ticks": 0,
            "value_area_high_ticks": 0,
            "value_area_low_ticks": 0,
            "total_volume_steps": 0,
            "value_area_volume_steps": 0,
        }

    # Point of Control (POC) — уровень с максимальным объёмом
    poc_level = max(price_levels, key=lambda x: x["volume_steps"])
    poc_price_ticks = poc_level["price_ticks"]

    # Total volume
    total_volume = sum(level["volume_steps"] for level in price_levels)

    # Value Area (70% volume) — расширяем от POC вверх/вниз
    value_area_target = int(total_volume * 0.7)
    value_area_volume = poc_level["volume_steps"]

    # Индекс POC
    poc_index = price_levels.index(poc_level)

    # Расширяем Value Area от POC
    va_low_index = poc_index
    va_high_index = poc_index

    while value_area_volume < value_area_target:
        # Проверяем, можем ли расширить вверх/вниз
        can_expand_up = va_high_index < len(price_levels) - 1
        can_expand_down = va_low_index > 0

        if not can_expand_up and not can_expand_down:
            break

        # Выбираем направление с бОльшим объёмом
        volume_up = price_levels[va_high_index + 1]["volume_steps"] if can_expand_up else 0
        volume_down = price_levels[va_low_index - 1]["volume_steps"] if can_expand_down else 0

        if volume_up >= volume_down and can_expand_up:
            va_high_index += 1
            value_area_volume += volume_up
        elif can_expand_down:
            va_low_index -= 1
            value_area_volume += volume_down
        else:
            break

    value_area_high_ticks = price_levels[va_high_index]["price_ticks"]
    value_area_low_ticks = price_levels[va_low_index]["price_ticks"]

    return {
        "price_levels": price_levels,
        "poc_price_ticks": poc_price_ticks,
        "value_area_high_ticks": value_area_high_ticks,
        "value_area_low_ticks": value_area_low_ticks,
        "total_volume_steps": total_volume,
        "value_area_volume_steps": value_area_volume,
    }


def find_hvn_lvn(
    volume_profile: dict[str, Any],
    hvn_threshold_percentile: float = 0.75,
    lvn_threshold_percentile: float = 0.25,
) -> dict[str, Any]:
    """Найти High Volume Nodes (HVN) и Low Volume Nodes (LVN).

    Roadmap §9: HVN — зоны с высоким объёмом (potential support/resistance).
                LVN — зоны с низким объёмом (слабые зоны, быстрое движение).

    Args:
        volume_profile: результат calculate_volume_profile()
        hvn_threshold_percentile: порог для HVN (default: 75-й перцентиль)
        lvn_threshold_percentile: порог для LVN (default: 25-й перцентиль)

    Returns:
        {
            "hvn_levels": [{"price_ticks": int, "volume_steps": int}, ...],
            "lvn_levels": [{"price_ticks": int, "volume_steps": int}, ...],
            "hvn_threshold": int,
            "lvn_threshold": int,
        }
    """
    price_levels = volume_profile.get("price_levels", [])

    if not price_levels:
        return {
            "hvn_levels": [],
            "lvn_levels": [],
            "hvn_threshold": 0,
            "lvn_threshold": 0,
        }

    # Сортируем объёмы для расчёта перцентилей
    volumes = sorted([level["volume_steps"] for level in price_levels])

    hvn_index = int(len(volumes) * hvn_threshold_percentile)
    lvn_index = int(len(volumes) * lvn_threshold_percentile)

    hvn_threshold = volumes[hvn_index] if hvn_index < len(volumes) else volumes[-1]
    lvn_threshold = volumes[lvn_index] if lvn_index < len(volumes) else volumes[0]

    # Фильтруем уровни
    hvn_levels = [
        {"price_ticks": level["price_ticks"], "volume_steps": level["volume_steps"]}
        for level in price_levels
        if level["volume_steps"] >= hvn_threshold
    ]

    lvn_levels = [
        {"price_ticks": level["price_ticks"], "volume_steps": level["volume_steps"]}
        for level in price_levels
        if level["volume_steps"] <= lvn_threshold
    ]

    return {
        "hvn_levels": hvn_levels,
        "lvn_levels": lvn_levels,
        "hvn_threshold": hvn_threshold,
        "lvn_threshold": lvn_threshold,
    }
