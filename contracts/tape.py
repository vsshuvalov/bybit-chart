"""
Tape/Bubbles contracts (Roadmap §9.1 Этап 5, пункт 2).

Tape — лента крупных сделок (Time & Sales с порогом объёма).
Bubbles — кластеры сделок для визуализации агрессивного flow.
"""

from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TradeSizeCategory(str, Enum):
    """Категория размера сделки для bubble visualization."""
    SMALL = "small"       # < 25th percentile
    MEDIUM = "medium"     # 25-75th percentile
    LARGE = "large"       # 75-95th percentile
    WHALE = "whale"       # > 95th percentile


class TapeEntry(BaseModel):
    """Одна запись в ленте крупных сделок.

    Roadmap §9.1: Tape — Time & Sales с фильтром по размеру.
    """
    exchange_timestamp_ms: int = Field(frozen=True)
    symbol: str = Field(frozen=True)
    price_ticks: int = Field(frozen=True, gt=0)
    qty_steps: int = Field(frozen=True, gt=0)
    taker_side: str = Field(frozen=True)   # "Buy" | "Sell"
    size_category: TradeSizeCategory = Field(frozen=True)
    trade_id: str = Field(frozen=True)
    is_block_trade: bool = Field(frozen=True, default=False)


class BubbleCluster(BaseModel):
    """Кластер сделок в bubble visualization.

    Группирует сделки в одном ценовом уровне за короткий промежуток времени.
    Размер bubble пропорционален суммарному объёму.
    """
    timestamp_ms: int = Field(frozen=True, description="Начало кластера")
    symbol: str = Field(frozen=True)
    price_ticks: int = Field(frozen=True, gt=0)
    total_qty_steps: int = Field(frozen=True, ge=0)
    buy_qty_steps: int = Field(frozen=True, ge=0)
    sell_qty_steps: int = Field(frozen=True, ge=0)
    trade_count: int = Field(frozen=True, ge=0)
    dominant_side: str = Field(frozen=True)    # "Buy" | "Sell" | "Neutral"
    size_category: TradeSizeCategory = Field(frozen=True)
