"""
Walls contract (Roadmap §9.1 Этап 6, пункт 5).

Wall — крупный лимитный ордер в стакане, выступающий
как поддержка (bid wall) или сопротивление (ask wall).

Roadmap: walls OUT_OF_VIEW/lifetime/continuity.
"""

from enum import Enum
from pydantic import BaseModel, Field


class WallStatus(str, Enum):
    ACTIVE = "active"           # виден в стакане
    OUT_OF_VIEW = "out_of_view" # вышел за пределы наблюдаемой глубины
    CONSUMED = "consumed"       # поглощён (qty стал < порога)
    MOVED = "moved"             # цена изменилась (iceberg?)


class Wall(BaseModel):
    """Крупный лимитный ордер (wall) в стакане."""

    symbol: str = Field(frozen=True)
    side: str = Field(frozen=True)           # "Bid" | "Ask"
    price_ticks: int = Field(frozen=True, gt=0)

    first_seen_ms: int = Field(frozen=True)
    last_seen_ms: int = Field(default=0)

    peak_qty_steps: int = Field(default=0, ge=0)  # максимальный зафиксированный объём
    last_qty_steps: int = Field(default=0, ge=0)

    status: WallStatus = Field(default=WallStatus.ACTIVE)
    update_count: int = Field(default=1, ge=1)

    model_config = {"frozen": False}

    @property
    def lifetime_ms(self) -> int:
        """Время жизни wall в мс."""
        return max(0, self.last_seen_ms - self.first_seen_ms)

    @property
    def is_active(self) -> bool:
        return self.status == WallStatus.ACTIVE
