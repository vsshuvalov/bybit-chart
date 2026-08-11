"""
OFI (Order Flow Imbalance) и Microprice contracts (Roadmap §9.1 Этап 6, пункт 2).

OFI — изменение bid/ask объёмов между последовательными snapshots.
Microprice — взвешенная цена с учётом дисбаланса стакана.
"""

from pydantic import BaseModel, Field


class OFISnapshot(BaseModel):
    """Order Flow Imbalance между двумя book snapshots.

    OFI = Σ(ΔBid) - Σ(ΔAsk) на лучших N уровнях.
    Положительный OFI → bid pressure (покупатели агрессивнее).
    Отрицательный OFI → ask pressure.
    """

    timestamp_ms: int = Field(frozen=True)
    symbol: str = Field(frozen=True)

    ofi: int = Field(frozen=True, description="Order Flow Imbalance (qty_steps)")
    bid_delta: int = Field(frozen=True, description="Изменение bid объёма")
    ask_delta: int = Field(frozen=True, description="Изменение ask объёма")

    best_bid_ticks: int = Field(frozen=True, gt=0)
    best_ask_ticks: int = Field(frozen=True, gt=0)
    spread_ticks: int = Field(frozen=True, ge=0)

    levels_used: int = Field(frozen=True, ge=1)


class MicropriceSnapshot(BaseModel):
    """Microprice — взвешенная mid-цена с учётом дисбаланса стакана.

    Microprice = (ask_qty * bid_price + bid_qty * ask_price) / (bid_qty + ask_qty)

    Отражает краткосрочное ценовое давление точнее, чем mid-price.
    """

    timestamp_ms: int = Field(frozen=True)
    symbol: str = Field(frozen=True)

    microprice_ticks: int = Field(frozen=True, description="Microprice в тиках (округлено)")
    mid_price_ticks: int = Field(frozen=True, description="Обычная mid-цена")
    best_bid_ticks: int = Field(frozen=True)
    best_ask_ticks: int = Field(frozen=True)
    best_bid_qty: int = Field(frozen=True, ge=0)
    best_ask_qty: int = Field(frozen=True, ge=0)

    imbalance: float = Field(frozen=True, description="bid_qty / (bid_qty + ask_qty)")
