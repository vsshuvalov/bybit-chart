"""
Absorption detector contract (Roadmap §9.1 Этап 6, пункт 4).

Absorption — ситуация когда крупный лимитный ордер поглощает
агрессивный поток, удерживая цену на уровне.
"""

from pydantic import BaseModel, Field


class AbsorptionEvent(BaseModel):
    """Зафиксированное поглощение агрессивного потока.

    Признаки absorption:
    - Значительный объём trades в одном направлении (агрессия)
    - Цена остаётся на том же уровне (не двигается)
    - Bid/ask qty не уменьшается (скрытый/обновляемый лимит)
    """

    timestamp_ms: int = Field(frozen=True)
    symbol: str = Field(frozen=True)
    price_ticks: int = Field(frozen=True, gt=0)
    side: str = Field(frozen=True)          # "Bid" | "Ask" (кто поглощает)

    absorbed_qty_steps: int = Field(frozen=True, ge=0, description="Объём поглощённых trades")
    duration_ms: int = Field(frozen=True, ge=0)
    trade_count: int = Field(frozen=True, ge=0)

    # Стакан до и после
    level_qty_before: int = Field(frozen=True, ge=0)
    level_qty_after: int = Field(frozen=True, ge=0)

    @property
    def replenishment_ratio(self) -> float:
        """Насколько уровень восполнился относительно поглощённого объёма.

        > 1.0 — уровень вырос (скрытый спрос/предложение)
        ~1.0 — уровень стабилен (хорошее поглощение)
        < 1.0 — уровень уменьшился (частичное поглощение)
        """
        if self.absorbed_qty_steps == 0:
            return 1.0
        return self.level_qty_after / max(self.absorbed_qty_steps, 1)
