"""
Heatmap analytics module (Roadmap §9.2 Étап 6).

Агрегирует orderbook snapshots в tiles для heatmap visualization.
"""

from collections import defaultdict
from decimal import Decimal

from contracts.heatmap import HeatmapTile
from contracts.schemas import RawBookEvent, RawBookLevel


class HeatmapAggregator:
    """Агрегатор для heatmap tiles.

    Принимает orderbook snapshots и агрегирует их в tiles
    по time interval и price bin.

    Usage:
        aggregator = HeatmapAggregator(
            venue="BYBIT",
            symbol="BTCUSDT",
            time_interval_ms=60000,  # 1 minute
            price_bin_size_ticks=10,  # 1.0 USDT for BTCUSDT
        )

        for book_event in book_events:
            aggregator.add_snapshot(book_event)

        tiles = aggregator.build()
    """

    def __init__(
        self,
        venue: str,
        symbol: str,
        time_interval_ms: int,
        price_bin_size_ticks: int,
    ):
        """Инициализировать heatmap aggregator.

        Args:
            venue: биржа (например, "BYBIT")
            symbol: торговая пара (например, "BTCUSDT")
            time_interval_ms: длительность временного окна (миллисекунды)
            price_bin_size_ticks: размер price bin (ticks)
        """
        self.venue = venue
        self.symbol = symbol
        self.time_interval_ms = time_interval_ms
        self.price_bin_size_ticks = price_bin_size_ticks

        # tiles[(time_bin, price_bin)] = {"bid_sum": int, "ask_sum": int, "count": int, ...}
        self._tiles: dict[tuple[int, int], dict] = defaultdict(
            lambda: {
                "bid_sum": 0,
                "ask_sum": 0,
                "count": 0,
                "bid_max": 0,
                "ask_max": 0,
            }
        )

    def add_snapshot(self, book_event: RawBookEvent) -> None:
        """Добавить orderbook snapshot в агрегацию.

        Args:
            book_event: RawBookEvent с bid/ask levels
        """
        if book_event.type != "snapshot":
            # Heatmap работает только со snapshots, delta игнорируются
            return

        timestamp = book_event.exchange_timestamp_ms
        time_bin = self._get_time_bin(timestamp)

        # Агрегировать bid levels
        for level in book_event.bids:
            price_bin = self._get_price_bin(level.price_ticks)
            key = (time_bin, price_bin)
            tile = self._tiles[key]
            tile["bid_sum"] += level.qty_steps
            tile["bid_max"] = max(tile["bid_max"], level.qty_steps)
            tile["count"] += 1

        # Агрегировать ask levels
        for level in book_event.asks:
            price_bin = self._get_price_bin(level.price_ticks)
            key = (time_bin, price_bin)
            tile = self._tiles[key]
            tile["ask_sum"] += level.qty_steps
            tile["ask_max"] = max(tile["ask_max"], level.qty_steps)
            tile["count"] += 1

    def build(self) -> list[HeatmapTile]:
        """Построить финальный список tiles.

        Returns:
            Список HeatmapTile, отсортированный по времени и цене
        """
        tiles = []
        for (time_bin, price_bin), data in self._tiles.items():
            interval_start = time_bin * self.time_interval_ms
            interval_end = interval_start + self.time_interval_ms
            price_bin_start = price_bin * self.price_bin_size_ticks
            price_bin_end = price_bin_start + self.price_bin_size_ticks

            tile = HeatmapTile(
                venue=self.venue,
                symbol=self.symbol,
                interval_start_ms=interval_start,
                interval_end_ms=interval_end,
                price_bin_start_ticks=price_bin_start,
                price_bin_end_ticks=price_bin_end,
                bid_volume_sum=data["bid_sum"],
                ask_volume_sum=data["ask_sum"],
                snapshot_count=data["count"],
                bid_volume_max=data["bid_max"],
                ask_volume_max=data["ask_max"],
            )
            tiles.append(tile)

        # Сортировать по времени, затем по цене
        tiles.sort(key=lambda t: (t.interval_start_ms, t.price_bin_start_ticks))
        return tiles

    def _get_time_bin(self, timestamp_ms: int) -> int:
        """Вычислить time bin index для timestamp.

        Args:
            timestamp_ms: Unix timestamp в миллисекундах

        Returns:
            Time bin index (floor division)
        """
        return timestamp_ms // self.time_interval_ms

    def _get_price_bin(self, price_ticks: int) -> int:
        """Вычислить price bin index для price.

        Args:
            price_ticks: цена в ticks

        Returns:
            Price bin index (floor division)
        """
        return price_ticks // self.price_bin_size_ticks


def compute_heatmap(
    book_events: list[RawBookEvent],
    venue: str,
    symbol: str,
    time_interval_ms: int,
    price_bin_size_ticks: int,
) -> list[HeatmapTile]:
    """Compute heatmap tiles из orderbook snapshots.

    Convenience function для одноразовой агрегации.

    Args:
        book_events: список RawBookEvent (snapshots)
        venue: биржа
        symbol: торговая пара
        time_interval_ms: длительность временного окна
        price_bin_size_ticks: размер price bin

    Returns:
        Список HeatmapTile
    """
    aggregator = HeatmapAggregator(
        venue=venue,
        symbol=symbol,
        time_interval_ms=time_interval_ms,
        price_bin_size_ticks=price_bin_size_ticks,
    )

    for event in book_events:
        aggregator.add_snapshot(event)

    return aggregator.build()
