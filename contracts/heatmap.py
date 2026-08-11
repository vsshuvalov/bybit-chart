"""
Heatmap tile contract (Roadmap §9.2 Этап 6).

Heatmap визуализирует orderbook depth по времени и цене.
Tile = агрегированный snapshot для определённого time window и price bin.
"""

from decimal import Decimal
from pydantic import BaseModel, Field


class HeatmapTile(BaseModel):
    """Heatmap tile для orderbook visualization.

    Tile агрегирует bid/ask volume в price bin за time interval.

    Attributes:
        venue: биржа (например, "BYBIT")
        symbol: торговая пара (например, "BTCUSDT")
        interval_start_ms: начало временного окна (Unix timestamp ms)
        interval_end_ms: конец временного окна (Unix timestamp ms)
        price_bin_start_ticks: нижняя граница price bin (ticks)
        price_bin_end_ticks: верхняя граница price bin (ticks)
        bid_volume_sum: суммарный bid volume в этом bin за interval
        ask_volume_sum: суммарный ask volume в этом bin за interval
        snapshot_count: количество orderbook snapshots, попавших в tile
        bid_volume_max: максимальный bid volume в одном snapshot
        ask_volume_max: максимальный ask volume в одном snapshot
    """

    venue: str = Field(..., description="Exchange venue")
    symbol: str = Field(..., description="Trading pair")
    interval_start_ms: int = Field(..., description="Tile start timestamp (ms)")
    interval_end_ms: int = Field(..., description="Tile end timestamp (ms)")
    price_bin_start_ticks: int = Field(..., description="Price bin lower bound (ticks)")
    price_bin_end_ticks: int = Field(..., description="Price bin upper bound (ticks)")
    bid_volume_sum: int = Field(..., description="Total bid volume (steps)")
    ask_volume_sum: int = Field(..., description="Total ask volume (steps)")
    snapshot_count: int = Field(..., description="Number of snapshots in tile")
    bid_volume_max: int = Field(default=0, description="Max bid volume in single snapshot")
    ask_volume_max: int = Field(default=0, description="Max ask volume in single snapshot")

    class Config:
        frozen = True


class HeatmapQueryParams(BaseModel):
    """Query parameters для heatmap API.

    Attributes:
        start_ms: начало временного диапазона
        end_ms: конец временного диапазона
        price_bin_size: размер price bin в ticks (например, 10 для BTCUSDT = 1.0 USDT bins)
        time_interval_ms: размер временного окна в миллисекундах (например, 60000 = 1 минута)
    """

    start_ms: int = Field(..., ge=0, description="Start timestamp (ms)")
    end_ms: int = Field(..., ge=0, description="End timestamp (ms)")
    price_bin_size: int = Field(default=10, ge=1, description="Price bin size (ticks)")
    time_interval_ms: int = Field(default=60000, ge=1000, description="Time interval (ms)")

    def validate_range(self) -> None:
        """Validate time range."""
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
