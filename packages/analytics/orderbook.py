"""
Order Book Reconstruction для L2 depth analysis (Roadmap §8.2).

Источник: Roadmap §8.2 (orderbook reconstruction, delta updates)

Архитектура:
- OrderBookState maintains current bid/ask levels
- apply_snapshot() rebuilds from BookCheckpoint
- Future: apply_delta() для incremental updates (ADR)

Use Cases:
- Depth chart visualization (bid/ask walls)
- Imbalance calculation (bid volume vs ask volume)
- Liquidity analysis (depth at price levels)
- Spread monitoring (best bid - best ask)

MVP: Snapshot-only reconstruction
Future: Delta updates для efficiency (Roadmap §8.2)
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OrderBookLevel:
    """Один уровень orderbook (bid или ask).

    Roadmap §8: price/qty хранятся как scaled integers (ticks/steps).
    """
    price_ticks: int
    qty_steps: int


@dataclass
class OrderBookSnapshot:
    """Snapshot orderbook состояния.

    Roadmap §8.2: snapshot = полная копия orderbook на момент времени.
    """
    timestamp_us: int
    bids: list[OrderBookLevel]  # sorted descending (best bid first)
    asks: list[OrderBookLevel]  # sorted ascending (best ask first)
    depth: int  # количество levels (200, 500)
    update_id: int  # sequence number для updates


class OrderBookState:
    """Maintains current orderbook state.

    Roadmap §8.2: rebuild orderbook from BookCheckpoint snapshots.
    Future: apply deltas для incremental updates.
    """

    def __init__(self, symbol: str):
        """Инициализировать orderbook state.

        Args:
            symbol: BTCUSDT, ETHUSDT, XRPUSDT
        """
        self.symbol = symbol
        self.bids: list[OrderBookLevel] = []
        self.asks: list[OrderBookLevel] = []
        self.timestamp_us: int = 0
        self.update_id: int = 0
        self.depth: int = 0

    def apply_snapshot(self, snapshot: OrderBookSnapshot):
        """Применить snapshot (полная перезапись orderbook).

        Args:
            snapshot: OrderBookSnapshot из BookCheckpoint

        Roadmap §8.2: snapshot = полная замена bids/asks.
        """
        self.bids = snapshot.bids.copy()
        self.asks = snapshot.asks.copy()
        self.timestamp_us = snapshot.timestamp_us
        self.update_id = snapshot.update_id
        self.depth = snapshot.depth

        logger.debug(
            f"Applied snapshot: symbol={self.symbol}, "
            f"bids={len(self.bids)}, asks={len(self.asks)}, "
            f"update_id={self.update_id}"
        )

    def get_best_bid(self) -> OrderBookLevel | None:
        """Получить лучший bid (highest price).

        Returns:
            OrderBookLevel или None если bids пустой
        """
        return self.bids[0] if self.bids else None

    def get_best_ask(self) -> OrderBookLevel | None:
        """Получить лучший ask (lowest price).

        Returns:
            OrderBookLevel или None если asks пустой
        """
        return self.asks[0] if self.asks else None

    def get_spread_ticks(self) -> int | None:
        """Получить spread (best_ask - best_bid) в ticks.

        Returns:
            Spread в ticks или None если orderbook пустой
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()

        if best_bid and best_ask:
            return best_ask.price_ticks - best_bid.price_ticks

        return None

    def get_depth_levels(self, num_levels: int = 10) -> dict[str, Any]:
        """Получить top N levels для depth chart.

        Args:
            num_levels: количество levels на каждой стороне (default: 10)

        Returns:
            {
                "bids": [{"price_ticks": int, "qty_steps": int}, ...],
                "asks": [{"price_ticks": int, "qty_steps": int}, ...],
                "spread_ticks": int,
                "timestamp_us": int,
            }
        """
        bids_top = [
            {"price_ticks": b.price_ticks, "qty_steps": b.qty_steps}
            for b in self.bids[:num_levels]
        ]

        asks_top = [
            {"price_ticks": a.price_ticks, "qty_steps": a.qty_steps}
            for a in self.asks[:num_levels]
        ]

        return {
            "bids": bids_top,
            "asks": asks_top,
            "spread_ticks": self.get_spread_ticks(),
            "timestamp_us": self.timestamp_us,
            "update_id": self.update_id,
        }

    def calculate_imbalance(self, depth_levels: int = 10) -> dict[str, Any]:
        """Рассчитать order book imbalance (bid vs ask pressure).

        Args:
            depth_levels: количество levels для анализа

        Returns:
            {
                "bid_volume": int,     # total bid volume (top N levels)
                "ask_volume": int,     # total ask volume (top N levels)
                "imbalance": float,    # (bid - ask) / (bid + ask), range [-1, 1]
                "imbalance_ratio": float,  # bid / ask
            }

        Roadmap §9: Imbalance > 0 → bullish pressure, < 0 → bearish pressure.
        """
        bid_volume = sum(b.qty_steps for b in self.bids[:depth_levels])
        ask_volume = sum(a.qty_steps for a in self.asks[:depth_levels])

        total_volume = bid_volume + ask_volume

        if total_volume > 0:
            imbalance = (bid_volume - ask_volume) / total_volume
        else:
            imbalance = 0.0

        if ask_volume > 0:
            imbalance_ratio = bid_volume / ask_volume
        else:
            imbalance_ratio = float('inf') if bid_volume > 0 else 0.0

        return {
            "bid_volume": bid_volume,
            "ask_volume": ask_volume,
            "imbalance": imbalance,
            "imbalance_ratio": imbalance_ratio,
            "depth_levels": depth_levels,
        }

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать orderbook state → dict.

        Returns:
            Полный snapshot orderbook в JSON-serializable формате
        """
        return {
            "symbol": self.symbol,
            "timestamp_us": self.timestamp_us,
            "update_id": self.update_id,
            "depth": self.depth,
            "bids": [{"price_ticks": b.price_ticks, "qty_steps": b.qty_steps} for b in self.bids],
            "asks": [{"price_ticks": a.price_ticks, "qty_steps": a.qty_steps} for a in self.asks],
        }


def reconstruct_from_checkpoint(checkpoint_dict: dict[str, Any]) -> OrderBookSnapshot:
    """Reconstruct OrderBookSnapshot from BookCheckpoint dict.

    Args:
        checkpoint_dict: BookCheckpoint из ParquetReader (с bids/asks JSON)

    Returns:
        OrderBookSnapshot ready для apply_snapshot()
    """
    import json

    # Parse bids/asks JSON
    bids_json = checkpoint_dict.get("bids", "[]")
    asks_json = checkpoint_dict.get("asks", "[]")

    bids_data = json.loads(bids_json) if isinstance(bids_json, str) else bids_json
    asks_data = json.loads(asks_json) if isinstance(asks_json, str) else asks_json

    bids = [OrderBookLevel(price_ticks=b["price"], qty_steps=b["qty"]) for b in bids_data]
    asks = [OrderBookLevel(price_ticks=a["price"], qty_steps=a["qty"]) for a in asks_data]

    return OrderBookSnapshot(
        timestamp_us=checkpoint_dict.get("timestampUs", 0),
        bids=bids,
        asks=asks,
        depth=checkpoint_dict.get("depth", 0),
        update_id=checkpoint_dict.get("updateId", 0),
    )
