"""
Time & Sales (Tape) для order flow analysis (Roadmap §9).

Источник: Roadmap §9 (Time & Sales, advanced order flow)

Time & Sales (aka "Tape") — поток сделок в реальном времени:
- Показывает каждую сделку: timestamp, price, quantity, aggressor side
- Aggressor side coloring: green (buy) / red (sell)
- Real-time stream через WebSocket
- Historical playback через Parquet

Use Cases:
- Price momentum detection (fast tape = momentum)
- Large trade identification (whale activity)
- Aggressor side patterns (absorption, exhaustion)
- Market microstructure analysis

Roadmap §9: Time & Sales — критичный инструмент для tape reading.
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TapeEntry:
    """Одна запись в Time & Sales tape.

    Roadmap §9: aggressor side определяет, кто был инициатором сделки.
    """
    timestamp_us: int
    price_ticks: int
    qty_steps: int
    aggressor_side: str  # "Buy" | "Sell"
    trade_id: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "timestamp_us": self.timestamp_us,
            "price_ticks": self.price_ticks,
            "qty_steps": self.qty_steps,
            "aggressor_side": self.aggressor_side,
            "trade_id": self.trade_id,
        }


class TimeAndSales:
    """Time & Sales tape engine.

    Roadmap §9: real-time tape для order flow analysis.
    """

    def __init__(self, max_entries: int = 1000):
        """Initialize Time & Sales tape.

        Args:
            max_entries: максимальное количество записей в памяти
        """
        self.entries: list[TapeEntry] = []
        self.max_entries = max_entries

    def append_trade(
        self,
        timestamp_us: int,
        price_ticks: int,
        qty_steps: int,
        aggressor_side: str,
        trade_id: str,
    ):
        """Добавить сделку в tape.

        Args:
            timestamp_us: timestamp сделки (microseconds)
            price_ticks: цена (scaled integer)
            qty_steps: количество (scaled integer)
            aggressor_side: "Buy" | "Sell"
            trade_id: unique trade ID
        """
        entry = TapeEntry(
            timestamp_us=timestamp_us,
            price_ticks=price_ticks,
            qty_steps=qty_steps,
            aggressor_side=aggressor_side,
            trade_id=trade_id,
        )

        self.entries.append(entry)

        # Trim старых записей если превышен max_entries
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries:]

    def get_recent(self, count: int = 100) -> list[TapeEntry]:
        """Получить последние N записей.

        Args:
            count: количество записей

        Returns:
            Список TapeEntry (newest first)
        """
        return list(reversed(self.entries[-count:]))

    def get_range(
        self,
        start_ts: int,
        end_ts: int,
    ) -> list[TapeEntry]:
        """Получить записи в временном диапазоне.

        Args:
            start_ts: начало диапазона (microseconds)
            end_ts: конец диапазона (microseconds)

        Returns:
            Список TapeEntry в диапазоне (chronological order)
        """
        return [
            e for e in self.entries
            if start_ts <= e.timestamp_us < end_ts
        ]

    def calculate_tape_stats(self, window_entries: int = 100) -> dict[str, Any]:
        """Рассчитать статистику tape за последние N записей.

        Args:
            window_entries: размер окна для анализа

        Returns:
            {
                "total_volume": int,
                "buy_volume": int,
                "sell_volume": int,
                "buy_count": int,
                "sell_count": int,
                "avg_trade_size": float,
                "price_range_ticks": int,
                "tape_speed": float,  # trades per second
            }
        """
        window = self.entries[-window_entries:] if len(self.entries) >= window_entries else self.entries

        if not window:
            return {
                "total_volume": 0,
                "buy_volume": 0,
                "sell_volume": 0,
                "buy_count": 0,
                "sell_count": 0,
                "avg_trade_size": 0.0,
                "price_range_ticks": 0,
                "tape_speed": 0.0,
            }

        buy_volume = sum(e.qty_steps for e in window if e.aggressor_side == "Buy")
        sell_volume = sum(e.qty_steps for e in window if e.aggressor_side == "Sell")
        buy_count = sum(1 for e in window if e.aggressor_side == "Buy")
        sell_count = sum(1 for e in window if e.aggressor_side == "Sell")
        total_volume = buy_volume + sell_volume

        avg_trade_size = total_volume / len(window) if window else 0.0

        prices = [e.price_ticks for e in window]
        price_range_ticks = max(prices) - min(prices) if prices else 0

        # Tape speed (trades per second)
        if len(window) >= 2:
            time_span_us = window[-1].timestamp_us - window[0].timestamp_us
            time_span_s = time_span_us / 1_000_000
            tape_speed = len(window) / time_span_s if time_span_s > 0 else 0.0
        else:
            tape_speed = 0.0

        return {
            "total_volume": total_volume,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "avg_trade_size": avg_trade_size,
            "price_range_ticks": price_range_ticks,
            "tape_speed": tape_speed,
        }

    def detect_large_trades(
        self,
        threshold_multiplier: float = 3.0,
        window_entries: int = 100,
    ) -> list[TapeEntry]:
        """Detect крупные сделки (whale activity).

        Args:
            threshold_multiplier: multiplier от среднего размера сделки
            window_entries: размер окна для baseline

        Returns:
            Список крупных сделок (newest first)
        """
        stats = self.calculate_tape_stats(window_entries)
        avg_size = stats["avg_trade_size"]

        if avg_size == 0:
            return []

        threshold = avg_size * threshold_multiplier

        large_trades = [
            e for e in self.entries[-window_entries:]
            if e.qty_steps >= threshold
        ]

        return list(reversed(large_trades))

    def to_dict_list(self, count: int = 100) -> list[dict[str, Any]]:
        """Serialize recent entries to list of dicts.

        Args:
            count: количество записей

        Returns:
            JSON-serializable list
        """
        recent = self.get_recent(count)
        return [e.to_dict() for e in recent]


def create_tape_from_trades(trades: list[dict[str, Any]]) -> TimeAndSales:
    """Создать Time & Sales tape из списка RawTrade.

    Args:
        trades: список RawTrade dict из ParquetReader

    Returns:
        TimeAndSales instance с загруженными данными
    """
    tape = TimeAndSales(max_entries=len(trades))

    for trade in trades:
        tape.append_trade(
            timestamp_us=trade.get("timestampUs", 0),
            price_ticks=trade.get("priceTicks", 0),
            qty_steps=trade.get("qtySteps", 0),
            aggressor_side=trade.get("takerSide", ""),
            trade_id=trade.get("sequence", ""),  # используем sequence как trade_id
        )

    return tape
