"""
OBI (Order Book Imbalance) Engine (Roadmap §6).

Источник: Roadmap §6 (Advanced Order Flow — DOM/OBI/OFI)

Concept:
OBI измеряет дисбаланс между bid и ask объёмами на различных уровнях orderbook.
Positive OBI → больше bid pressure (potential upward movement)
Negative OBI → больше ask pressure (potential downward movement)

Calculation:
OBI = (Bid Volume - Ask Volume) / (Bid Volume + Ask Volume)

Ranges: -1.0 (all asks) to +1.0 (all bids)

Levels:
- Near spread (top 5 levels)
- Mid-range (6-20 levels)
- Far (21-50 levels)

Use Cases:
- Identify institutional accumulation/distribution
- Predict short-term price movement
- Detect hidden support/resistance
- Confirm trend strength

Roadmap §6 requirements:
- Per-level OBI calculation
- Aggregated OBI по depth levels
- Time-series tracking
- Threshold alerts
"""

import logging
from dataclasses import dataclass
from typing import Any

from packages.analytics.orderbook import OrderBookSnapshot, OrderBookLevel

logger = logging.getLogger(__name__)


@dataclass
class OBISnapshot:
    """OBI snapshot для одного timestamp.

    Roadmap §6: OBI calculation result.
    """
    timestamp_us: int
    symbol: str

    # Overall OBI
    overall_obi: float

    # OBI по depth levels
    near_obi: float  # Top 5 levels
    mid_obi: float   # 6-20 levels
    far_obi: float   # 21-50 levels

    # Volume data
    total_bid_volume: float
    total_ask_volume: float

    # Per-level data (optional)
    level_obis: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "timestamp_us": self.timestamp_us,
            "symbol": self.symbol,
            "overall_obi": self.overall_obi,
            "near_obi": self.near_obi,
            "mid_obi": self.mid_obi,
            "far_obi": self.far_obi,
            "total_bid_volume": self.total_bid_volume,
            "total_ask_volume": self.total_ask_volume,
        }


class OBIEngine:
    """OBI (Order Book Imbalance) calculation engine.

    Roadmap §6: DOM/OBI analysis.
    """

    def __init__(
        self,
        near_levels: int = 5,
        mid_levels: int = 20,
        far_levels: int = 50,
    ):
        """Initialize OBI engine.

        Args:
            near_levels: top N levels для near OBI
            mid_levels: max level для mid OBI (6-N)
            far_levels: max level для far OBI (21-N)
        """
        self.near_levels = near_levels
        self.mid_levels = mid_levels
        self.far_levels = far_levels

        # History
        self.snapshots: list[OBISnapshot] = []

    def calculate_obi(self, book: OrderBookSnapshot, symbol: str = "UNKNOWN") -> OBISnapshot:
        """Calculate OBI from book snapshot.

        Args:
            book: OrderBookSnapshot с L50 data
            symbol: symbol name

        Returns:
            OBISnapshot с calculated OBI values

        Roadmap §6: OBI calculation от book snapshot.
        """
        bids = book.bids
        asks = book.asks

        # Overall OBI (all levels)
        total_bid_vol = sum(bid.qty_steps for bid in bids)
        total_ask_vol = sum(ask.qty_steps for ask in asks)

        overall_obi = self._calc_obi_value(total_bid_vol, total_ask_vol)

        # Near OBI (top 5 levels)
        near_bids = bids[:self.near_levels]
        near_asks = asks[:self.near_levels]
        near_bid_vol = sum(bid.qty_steps for bid in near_bids)
        near_ask_vol = sum(ask.qty_steps for ask in near_asks)
        near_obi = self._calc_obi_value(near_bid_vol, near_ask_vol)

        # Mid OBI (6-20 levels)
        mid_bids = bids[self.near_levels:self.mid_levels]
        mid_asks = asks[self.near_levels:self.mid_levels]
        mid_bid_vol = sum(bid.qty_steps for bid in mid_bids)
        mid_ask_vol = sum(ask.qty_steps for ask in mid_asks)
        mid_obi = self._calc_obi_value(mid_bid_vol, mid_ask_vol)

        # Far OBI (21-50 levels)
        far_bids = bids[self.mid_levels:self.far_levels]
        far_asks = asks[self.mid_levels:self.far_levels]
        far_bid_vol = sum(bid.qty_steps for bid in far_bids)
        far_ask_vol = sum(ask.qty_steps for ask in far_asks)
        far_obi = self._calc_obi_value(far_bid_vol, far_ask_vol)

        # Per-level OBI (optional)
        level_obis = []
        max_levels = min(len(bids), len(asks), self.far_levels)

        for i in range(max_levels):
            bid_vol = bids[i].qty_steps if i < len(bids) else 0
            ask_vol = asks[i].qty_steps if i < len(asks) else 0
            level_obi = self._calc_obi_value(bid_vol, ask_vol)
            level_obis.append(level_obi)

        snapshot = OBISnapshot(
            timestamp_us=book.timestamp_us,
            symbol=symbol,
            overall_obi=overall_obi,
            near_obi=near_obi,
            mid_obi=mid_obi,
            far_obi=far_obi,
            total_bid_volume=total_bid_vol,
            total_ask_volume=total_ask_vol,
            level_obis=level_obis,
        )

        self.snapshots.append(snapshot)

        return snapshot

    def _calc_obi_value(self, bid_volume: float, ask_volume: float) -> float:
        """Calculate OBI value.

        Args:
            bid_volume: total bid volume
            ask_volume: total ask volume

        Returns:
            OBI value (-1.0 to +1.0)
        """
        total = bid_volume + ask_volume

        if total == 0:
            return 0.0

        return (bid_volume - ask_volume) / total

    def get_latest(self) -> OBISnapshot | None:
        """Get latest OBI snapshot.

        Returns:
            Latest OBISnapshot или None
        """
        if not self.snapshots:
            return None

        return self.snapshots[-1]

    def get_history(self, start_ts: int, end_ts: int) -> list[OBISnapshot]:
        """Get OBI history для time range.

        Args:
            start_ts: start timestamp (microseconds)
            end_ts: end timestamp (microseconds)

        Returns:
            List of OBISnapshot в range
        """
        return [
            snap for snap in self.snapshots
            if start_ts <= snap.timestamp_us < end_ts
        ]

    def detect_extreme_imbalance(
        self,
        threshold: float = 0.7,
    ) -> tuple[bool, str | None]:
        """Detect extreme OBI (potential strong movement).

        Args:
            threshold: OBI threshold (default 0.7)

        Returns:
            (is_extreme, direction) где direction = "bullish" | "bearish" | None

        Roadmap §6: threshold alert для extreme imbalance.
        """
        latest = self.get_latest()

        if not latest:
            return False, None

        # Check near levels (most important для short-term movement)
        if latest.near_obi > threshold:
            return True, "bullish"
        elif latest.near_obi < -threshold:
            return True, "bearish"

        return False, None

    def to_dict_list(self, start_ts: int, end_ts: int) -> list[dict[str, Any]]:
        """Get OBI history как dict list.

        Args:
            start_ts: start timestamp
            end_ts: end timestamp

        Returns:
            List of OBI dicts
        """
        snapshots = self.get_history(start_ts, end_ts)
        return [snap.to_dict() for snap in snapshots]
