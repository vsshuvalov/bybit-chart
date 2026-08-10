"""
CVD (Cumulative Volume Delta) calculation (Этап 3 / P3-A2).

Источник: Roadmap §9.2 (Backend-модули: Delta, CVD, VWAP, ...)

CVD — кумулятивная сумма Delta:
- CVD[i] = CVD[i-1] + Delta[i]
- CVD[0] = Delta[0]

Интерпретация:
- Растущий CVD → устойчивое преобладание aggressive buyers
- Падающий CVD → устойчивое преобладание aggressive sellers
- Дивергенция CVD и цены → потенциальный разворот:
  * Price up, CVD down → bearish divergence (слабеет покупательское давление)
  * Price down, CVD up → bullish divergence (слабеет давление продавцов)

Roadmap §9: CVD визуализируется как линия под основным графиком.
"""

from typing import Any

from packages.analytics.delta import aggregate_delta_by_interval


def calculate_cvd(delta_bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Рассчитать CVD (Cumulative Volume Delta) из Delta bars.

    Args:
        delta_bars: список Delta bars из aggregate_delta_by_interval()
                    (каждый bar содержит timestamp_us, delta, ...)

    Returns:
        Список CVD bars с добавленным полем "cvd":
        [
            {
                "timestamp_us": int,
                "delta": int,
                "cvd": int,           # кумулятивная сумма delta
                "buy_volume": int,    # оригинальные поля из delta_bars
                "sell_volume": int,
                ...
            },
            ...
        ]

    Пример:
        delta_bars = [
            {"timestamp_us": 0, "delta": 100},
            {"timestamp_us": 60_000_000, "delta": -50},
            {"timestamp_us": 120_000_000, "delta": 75},
        ]
        cvd_bars = calculate_cvd(delta_bars)
        # [
        #   {"timestamp_us": 0, "delta": 100, "cvd": 100},
        #   {"timestamp_us": 60_000_000, "delta": -50, "cvd": 50},
        #   {"timestamp_us": 120_000_000, "delta": 75, "cvd": 125},
        # ]
    """
    if not delta_bars:
        return []

    cvd_bars = []
    cumulative_delta = 0

    for bar in delta_bars:
        delta = bar.get("delta", 0)
        cumulative_delta += delta

        # Копируем bar и добавляем cvd
        cvd_bar = {**bar, "cvd": cumulative_delta}
        cvd_bars.append(cvd_bar)

    return cvd_bars


def aggregate_cvd_by_interval(
    events: list[dict[str, Any]],
    interval_us: int,
) -> list[dict[str, Any]]:
    """Агрегировать CVD по временным окнам.

    Convenience функция: Delta aggregation + CVD calculation в одном вызове.

    Args:
        events: список RawTrade из ParquetReader
        interval_us: интервал в microseconds (1m = 60_000_000)

    Returns:
        Список CVD bars с timestamp_us, delta, cvd, buy_volume, sell_volume, ...

    Roadmap §9: CVD bars синхронизированы с OHLC candles.
    """
    # 1. Агрегируем Delta
    delta_bars = aggregate_delta_by_interval(events, interval_us)

    # 2. Рассчитываем CVD
    cvd_bars = calculate_cvd(delta_bars)

    return cvd_bars


def reset_cvd_at_index(
    cvd_bars: list[dict[str, Any]],
    reset_index: int,
) -> list[dict[str, Any]]:
    """Сбросить CVD в 0 на определённом индексе и пересчитать дальше.

    Roadmap §9: Сброс CVD полезен для анализа отдельных торговых сессий
    или после значимых событий (например, начало нового торгового дня).

    Args:
        cvd_bars: список CVD bars
        reset_index: индекс, с которого начинается новый CVD (inclusive)

    Returns:
        Новый список CVD bars с пересчитанным CVD после reset_index

    Пример:
        cvd_bars = [
            {"cvd": 100, "delta": 100},
            {"cvd": 150, "delta": 50},
            {"cvd": 125, "delta": -25},  # reset здесь (index=2)
            {"cvd": 175, "delta": 50},
        ]
        reset_bars = reset_cvd_at_index(cvd_bars, reset_index=2)
        # [
        #   {"cvd": 100, "delta": 100},
        #   {"cvd": 150, "delta": 50},
        #   {"cvd": -25, "delta": -25},  # reset: cvd = delta
        #   {"cvd": 25, "delta": 50},    # cvd = -25 + 50
        # ]
    """
    if not cvd_bars or reset_index >= len(cvd_bars):
        return cvd_bars.copy()

    reset_bars = []

    # Bars до reset — без изменений
    for i in range(reset_index):
        reset_bars.append(cvd_bars[i].copy())

    # Bars после reset — пересчитываем CVD
    cumulative_delta = 0
    for i in range(reset_index, len(cvd_bars)):
        bar = cvd_bars[i].copy()
        delta = bar.get("delta", 0)
        cumulative_delta += delta
        bar["cvd"] = cumulative_delta
        reset_bars.append(bar)

    return reset_bars
