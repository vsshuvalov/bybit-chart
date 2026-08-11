"""
Sweep detector contract (Roadmap §9.1 Этап 5, пункт 7).

Sweep — серия агрессивных сделок в одном направлении через
несколько ценовых уровней за короткий промежуток времени.
"""

from pydantic import BaseModel, Field


class SweepEvent(BaseModel):
    """Зафиксированный sweep через несколько уровней стакана.

    Roadmap §9.1: Sweep event set не зависит от chunk/batch boundaries.
    """

    symbol: str = Field(frozen=True)
    direction: str = Field(frozen=True)          # "Buy" | "Sell"

    start_timestamp_ms: int = Field(frozen=True)
    end_timestamp_ms: int = Field(frozen=True)

    start_price_ticks: int = Field(frozen=True, gt=0)
    end_price_ticks: int = Field(frozen=True, gt=0)

    levels_swept: int = Field(frozen=True, ge=1, description="Количество уникальных ценовых уровней")
    total_qty_steps: int = Field(frozen=True, ge=0)
    trade_count: int = Field(frozen=True, ge=1)

    price_move_ticks: int = Field(frozen=True, ge=0, description="Разница цен: |end - start|")
    duration_ms: int = Field(frozen=True, ge=0)

    @property
    def intensity(self) -> float:
        """Интенсивность: qty_steps / duration_ms."""
        if self.duration_ms == 0:
            return float(self.total_qty_steps)
        return self.total_qty_steps / self.duration_ms
