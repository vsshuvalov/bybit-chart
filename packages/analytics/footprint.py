"""
Footprint Chart для volume distribution analysis (Roadmap §9).

Источник: Roadmap §9 (Footprint chart, advanced order flow)

Footprint Chart — распределение объёма внутри каждой свечи:
- Показывает bid/ask volume на каждом price level внутри candle
- Визуализация: matrix (time × price), цвет = volume intensity
- Delta footprint: buy volume - sell volume на каждом level
- Imbalance detection: аномальные bid/ask ratios

Use Cases:
- Absorption detection (крупные bids поглощают selling)
- Exhaustion patterns (buying exhausted, no follow-through)
- Support/resistance validation (volume clusters)
- Iceberg order detection (hidden liquidity)

Roadmap §9: Footprint chart — professional order flow visualization.
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FootprintCell:
    """Одна ячейка footprint chart (price level × time bin).

    Roadmap §9: каждая ячейка хранит bid/ask volume на price level.
    """
    price_ticks: int
    buy_volume: int
    sell_volume: int
    delta: int  # buy_volume - sell_volume
    total_volume: int  # buy_volume + sell_volume

    def get_imbalance(self) -> float:
        """Рассчитать imbalance ratio.

        Returns:
            (buy - sell) / (buy + sell), range [-1, 1]
        """
        if self.total_volume == 0:
            return 0.0
        return self.delta / self.total_volume


@dataclass
class FootprintCandle:
    """Footprint для одной свечи (time bin).

    Roadmap §9: footprint candle содержит volume distribution по price levels.
    """
    timestamp_us: int
    cells: dict[int, FootprintCell]  # price_ticks → FootprintCell
    open_ticks: int
    high_ticks: int
    low_ticks: int
    close_ticks: int

    def get_poc_price(self) -> int | None:
        """Получить Point of Control (price с максимальным volume).

        Returns:
            price_ticks POC или None если cells пустые
        """
        if not self.cells:
            return None

        max_cell = max(self.cells.values(), key=lambda c: c.total_volume)
        return max_cell.price_ticks

    def get_imbalance_levels(self, threshold: float = 0.5) -> list[FootprintCell]:
        """Найти price levels с сильным imbalance.

        Args:
            threshold: минимальный |imbalance| для detection (0.5 = 75%/25%)

        Returns:
            Список cells с imbalance >= threshold
        """
        return [
            cell for cell in self.cells.values()
            if abs(cell.get_imbalance()) >= threshold
        ]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "timestamp_us": self.timestamp_us,
            "open_ticks": self.open_ticks,
            "high_ticks": self.high_ticks,
            "low_ticks": self.low_ticks,
            "close_ticks": self.close_ticks,
            "poc_price": self.get_poc_price(),
            "cells": [
                {
                    "price_ticks": price,
                    "buy_volume": cell.buy_volume,
                    "sell_volume": cell.sell_volume,
                    "delta": cell.delta,
                    "total_volume": cell.total_volume,
                    "imbalance": cell.get_imbalance(),
                }
                for price, cell in sorted(self.cells.items(), reverse=True)
            ],
        }


class FootprintChart:
    """Footprint chart engine для volume distribution analysis.

    Roadmap §9: builds footprint candles from trades.
    """

    def __init__(self, interval_us: int):
        """Initialize footprint chart.

        Args:
            interval_us: candle interval (microseconds), например 60_000_000 = 1m
        """
        self.interval_us = interval_us
        self.candles: dict[int, FootprintCandle] = {}  # timestamp → FootprintCandle

    def add_trade(
        self,
        timestamp_us: int,
        price_ticks: int,
        qty_steps: int,
        aggressor_side: str,
    ):
        """Добавить trade в footprint.

        Args:
            timestamp_us: timestamp сделки
            price_ticks: цена
            qty_steps: количество
            aggressor_side: "Buy" | "Sell"
        """
        # Определяем candle timestamp
        candle_ts = (timestamp_us // self.interval_us) * self.interval_us

        # Создаём candle если не существует
        if candle_ts not in self.candles:
            self.candles[candle_ts] = FootprintCandle(
                timestamp_us=candle_ts,
                cells={},
                open_ticks=price_ticks,
                high_ticks=price_ticks,
                low_ticks=price_ticks,
                close_ticks=price_ticks,
            )

        candle = self.candles[candle_ts]

        # Обновляем OHLC
        candle.high_ticks = max(candle.high_ticks, price_ticks)
        candle.low_ticks = min(candle.low_ticks, price_ticks)
        candle.close_ticks = price_ticks

        # Обновляем cell для price level
        if price_ticks not in candle.cells:
            candle.cells[price_ticks] = FootprintCell(
                price_ticks=price_ticks,
                buy_volume=0,
                sell_volume=0,
                delta=0,
                total_volume=0,
            )

        cell = candle.cells[price_ticks]

        if aggressor_side == "Buy":
            cell.buy_volume += qty_steps
        elif aggressor_side == "Sell":
            cell.sell_volume += qty_steps

        cell.total_volume = cell.buy_volume + cell.sell_volume
        cell.delta = cell.buy_volume - cell.sell_volume

    def get_candle(self, timestamp_us: int) -> FootprintCandle | None:
        """Получить footprint candle по timestamp.

        Args:
            timestamp_us: timestamp candle

        Returns:
            FootprintCandle или None
        """
        candle_ts = (timestamp_us // self.interval_us) * self.interval_us
        return self.candles.get(candle_ts)

    def get_candles_range(
        self,
        start_ts: int,
        end_ts: int,
    ) -> list[FootprintCandle]:
        """Получить footprint candles в диапазоне.

        Args:
            start_ts: начало диапазона
            end_ts: конец диапазона

        Returns:
            Список FootprintCandle (chronological order)
        """
        return [
            candle for ts, candle in sorted(self.candles.items())
            if start_ts <= ts < end_ts
        ]

    def detect_absorption(
        self,
        candle: FootprintCandle,
        min_volume_ratio: float = 3.0,
    ) -> list[tuple[int, str]]:
        """Detect absorption patterns (крупный volume поглощает противоположную сторону).

        Args:
            candle: FootprintCandle для анализа
            min_volume_ratio: минимальное соотношение buy/sell для absorption

        Returns:
            Список (price_ticks, "buy_absorption" | "sell_absorption")

        Roadmap §9: Absorption = крупные bids поглощают selling (или наоборот).
        """
        absorptions = []

        for price, cell in candle.cells.items():
            if cell.buy_volume == 0 or cell.sell_volume == 0:
                continue

            buy_ratio = cell.buy_volume / cell.sell_volume
            sell_ratio = cell.sell_volume / cell.buy_volume

            if buy_ratio >= min_volume_ratio:
                absorptions.append((price, "buy_absorption"))
            elif sell_ratio >= min_volume_ratio:
                absorptions.append((price, "sell_absorption"))

        return absorptions

    def to_dict_list(self, start_ts: int, end_ts: int) -> list[dict[str, Any]]:
        """Serialize candles в range to list of dicts.

        Args:
            start_ts: начало диапазона
            end_ts: конец диапазона

        Returns:
            JSON-serializable list
        """
        candles = self.get_candles_range(start_ts, end_ts)
        return [c.to_dict() for c in candles]


def create_footprint_from_trades(
    trades: list[dict[str, Any]],
    interval_us: int,
) -> FootprintChart:
    """Создать Footprint chart из списка RawTrade.

    Args:
        trades: список RawTrade dict из ParquetReader
        interval_us: candle interval (microseconds)

    Returns:
        FootprintChart instance с данными
    """
    footprint = FootprintChart(interval_us)

    for trade in trades:
        footprint.add_trade(
            timestamp_us=trade.get("timestampUs", 0),
            price_ticks=trade.get("priceTicks", 0),
            qty_steps=trade.get("qtySteps", 0),
            aggressor_side=trade.get("takerSide", ""),
        )

    return footprint
