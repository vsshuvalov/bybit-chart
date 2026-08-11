"""
Tape/Bubbles analytics module (Roadmap §9.1 Этап 5, пункт 2).

Tape: фильтрация крупных сделок для ленты Time & Sales.
Bubbles: кластеризация сделок по цене и времени для визуализации.
"""

from collections import defaultdict
from decimal import Decimal
from typing import Iterator

from contracts.schemas import RawTrade, TakerSide
from contracts.tape import BubbleCluster, TapeEntry, TradeSizeCategory


def _classify_size(qty_steps: int, thresholds: dict) -> TradeSizeCategory:
    """Классифицировать размер сделки по порогам."""
    if qty_steps >= thresholds["whale"]:
        return TradeSizeCategory.WHALE
    if qty_steps >= thresholds["large"]:
        return TradeSizeCategory.LARGE
    if qty_steps >= thresholds["medium"]:
        return TradeSizeCategory.MEDIUM
    return TradeSizeCategory.SMALL


class TapeFilter:
    """Фильтр ленты крупных сделок.

    Пропускает только сделки выше заданного порога объёма.

    Usage:
        tape = TapeFilter(min_qty_steps=1000)
        for trade in trades:
            entry = tape.process(trade)
            if entry:
                print(entry)
    """

    def __init__(
        self,
        min_qty_steps: int = 0,
        whale_threshold: int = 10000,
        large_threshold: int = 5000,
        medium_threshold: int = 1000,
    ):
        self.min_qty_steps = min_qty_steps
        self.thresholds = {
            "whale": whale_threshold,
            "large": large_threshold,
            "medium": medium_threshold,
        }
        self.entries: list[TapeEntry] = []

    def process(self, trade: RawTrade) -> TapeEntry | None:
        """Обработать trade — вернуть TapeEntry если проходит фильтр."""
        if trade.qty_steps < self.min_qty_steps:
            return None

        entry = TapeEntry(
            exchange_timestamp_ms=trade.exchange_timestamp_ms,
            symbol=trade.symbol,
            price_ticks=trade.price_ticks,
            qty_steps=trade.qty_steps,
            taker_side=trade.taker_side.value,
            size_category=_classify_size(trade.qty_steps, self.thresholds),
            trade_id=trade.trade_id,
            is_block_trade=trade.is_block_trade,
        )
        self.entries.append(entry)
        return entry

    def get_entries(
        self,
        start_ms: int | None = None,
        end_ms: int | None = None,
        min_category: TradeSizeCategory | None = None,
    ) -> list[TapeEntry]:
        """Получить отфильтрованные записи."""
        result = self.entries
        if start_ms is not None:
            result = [e for e in result if e.exchange_timestamp_ms >= start_ms]
        if end_ms is not None:
            result = [e for e in result if e.exchange_timestamp_ms < end_ms]
        if min_category == TradeSizeCategory.LARGE:
            result = [e for e in result if e.size_category in (
                TradeSizeCategory.LARGE, TradeSizeCategory.WHALE
            )]
        elif min_category == TradeSizeCategory.WHALE:
            result = [e for e in result if e.size_category == TradeSizeCategory.WHALE]
        return result


class BubbleAggregator:
    """Кластеризатор сделок для bubble visualization.

    Группирует сделки в одном ценовом уровне за cluster_window_ms.

    Usage:
        agg = BubbleAggregator(cluster_window_ms=1000)
        for trade in trades:
            agg.add_trade(trade)
        bubbles = agg.get_bubbles()
    """

    def __init__(
        self,
        cluster_window_ms: int = 1000,
        whale_threshold: int = 10000,
        large_threshold: int = 5000,
        medium_threshold: int = 1000,
    ):
        self.cluster_window_ms = cluster_window_ms
        self.thresholds = {
            "whale": whale_threshold,
            "large": large_threshold,
            "medium": medium_threshold,
        }
        # {price_ticks: (window_start_ms, buy_qty, sell_qty, count)}
        self._active: dict[int, tuple[int, int, int, int]] = {}
        self._clusters: list[BubbleCluster] = []

    def add_trade(self, trade: RawTrade) -> BubbleCluster | None:
        """Добавить trade — вернуть завершённый кластер если окно закрылось."""
        completed = None
        price = trade.price_ticks
        now = trade.exchange_timestamp_ms

        if price in self._active:
            window_start, buy_qty, sell_qty, count = self._active[price]
            if now - window_start > self.cluster_window_ms:
                # Закрыть текущий кластер
                completed = self._close_cluster(price, window_start, buy_qty, sell_qty, count, trade.symbol)
                # Начать новый
                self._active[price] = (now, 0, 0, 0)
                window_start, buy_qty, sell_qty, count = self._active[price]
        else:
            self._active[price] = (now, 0, 0, 0)
            window_start, buy_qty, sell_qty, count = self._active[price]

        # Обновить кластер
        if trade.taker_side == TakerSide.BUY:
            self._active[price] = (window_start, buy_qty + trade.qty_steps, sell_qty, count + 1)
        else:
            self._active[price] = (window_start, buy_qty, sell_qty + trade.qty_steps, count + 1)

        return completed

    def _close_cluster(
        self, price: int, window_start: int,
        buy_qty: int, sell_qty: int, count: int, symbol: str
    ) -> BubbleCluster:
        total = buy_qty + sell_qty
        if buy_qty > sell_qty:
            dominant = "Buy"
        elif sell_qty > buy_qty:
            dominant = "Sell"
        else:
            dominant = "Neutral"

        cluster = BubbleCluster(
            timestamp_ms=window_start,
            symbol=symbol,
            price_ticks=price,
            total_qty_steps=total,
            buy_qty_steps=buy_qty,
            sell_qty_steps=sell_qty,
            trade_count=count,
            dominant_side=dominant,
            size_category=_classify_size(total, self.thresholds),
        )
        self._clusters.append(cluster)
        return cluster

    def flush(self, symbol: str) -> list[BubbleCluster]:
        """Завершить все активные кластеры."""
        flushed = []
        for price, (window_start, buy_qty, sell_qty, count) in self._active.items():
            if count > 0:
                cluster = self._close_cluster(price, window_start, buy_qty, sell_qty, count, symbol)
                flushed.append(cluster)
        self._active.clear()
        return flushed

    def get_bubbles(
        self,
        start_ms: int | None = None,
        end_ms: int | None = None,
        min_category: TradeSizeCategory | None = None,
    ) -> list[BubbleCluster]:
        """Получить завершённые кластеры."""
        result = self._clusters
        if start_ms is not None:
            result = [b for b in result if b.timestamp_ms >= start_ms]
        if end_ms is not None:
            result = [b for b in result if b.timestamp_ms < end_ms]
        if min_category == TradeSizeCategory.LARGE:
            result = [b for b in result if b.size_category in (
                TradeSizeCategory.LARGE, TradeSizeCategory.WHALE
            )]
        elif min_category == TradeSizeCategory.WHALE:
            result = [b for b in result if b.size_category == TradeSizeCategory.WHALE]
        return result
