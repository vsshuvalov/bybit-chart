"""
Footprint analytics contracts (Roadmap §9.1 Этап 5).

Footprint chart: bid/ask volume aggregation per price level.
"""

from decimal import Decimal
from typing import Dict

from pydantic import BaseModel, Field


class FootprintLevel(BaseModel):
    """Один ценовой уровень в footprint bar."""

    price: Decimal = Field(frozen=True, description="Ценовой уровень")
    bid_volume: Decimal = Field(
        frozen=True, ge=0, description="Объём покупок (taker Buy)"
    )
    ask_volume: Decimal = Field(
        frozen=True, ge=0, description="Объём продаж (taker Sell)"
    )
    total_volume: Decimal = Field(frozen=True, ge=0, description="Общий объём")
    imbalance: Decimal = Field(
        frozen=True,
        description="Дисбаланс: (bid_volume - ask_volume) / total_volume",
    )
    trade_count: int = Field(frozen=True, ge=0, description="Количество сделок")

    def __str__(self) -> str:
        return (
            f"FootprintLevel(price={self.price}, "
            f"bid={self.bid_volume}, ask={self.ask_volume}, "
            f"imbalance={self.imbalance:.2f})"
        )


class FootprintBar(BaseModel):
    """Footprint bar: агрегация bid/ask volume по ценовым уровням.

    Roadmap §9.1 Этап 5: Trade-derived analytics.

    Использование:
    - Визуализация агрессивных покупателей/продавцов
    - Imbalance detection (сильный дисбаланс bid/ask)
    - POC (Point of Control) — уровень с максимальным объёмом

    Атрибуты:
        venue: биржа (всегда "BYBIT")
        symbol: торговая пара (например, "BTCUSDT")
        interval_start_ms: начало временного интервала (Unix ms)
        interval_end_ms: конец временного интервала (Unix ms)
        interval_seconds: длительность интервала (секунды)
        levels: словарь {price: FootprintLevel}
        poc_price: Point of Control (уровень с max volume)
        total_bid_volume: суммарный bid volume
        total_ask_volume: суммарный ask volume
        total_volume: суммарный объём
        overall_imbalance: общий дисбаланс всего бара
        level_count: количество ценовых уровней
    """

    venue: str = Field(frozen=True)
    symbol: str = Field(frozen=True)
    interval_start_ms: int = Field(frozen=True)
    interval_end_ms: int = Field(frozen=True)
    interval_seconds: int = Field(frozen=True, gt=0)

    levels: Dict[str, FootprintLevel] = Field(
        frozen=True, description="Ценовые уровни (key = str(price))"
    )

    poc_price: Decimal | None = Field(
        frozen=True, description="Point of Control (max volume level)"
    )

    total_bid_volume: Decimal = Field(frozen=True, ge=0)
    total_ask_volume: Decimal = Field(frozen=True, ge=0)
    total_volume: Decimal = Field(frozen=True, ge=0)
    overall_imbalance: Decimal = Field(frozen=True)

    level_count: int = Field(frozen=True, ge=0)

    def __str__(self) -> str:
        return (
            f"FootprintBar({self.symbol} "
            f"{self.interval_start_ms}..{self.interval_end_ms}, "
            f"{self.level_count} levels, "
            f"POC={self.poc_price}, "
            f"imbalance={self.overall_imbalance:.2f})"
        )

    def get_level(self, price: Decimal) -> FootprintLevel | None:
        """Получить footprint level по цене."""
        return self.levels.get(str(price))

    def get_top_imbalanced_levels(self, threshold: Decimal) -> list[FootprintLevel]:
        """Получить уровни с сильным дисбалансом (|imbalance| > threshold).

        Args:
            threshold: порог дисбаланса (например, 0.5 = 50%)

        Returns:
            Список уровней, отсортированных по |imbalance| descending
        """
        imbalanced = [
            level
            for level in self.levels.values()
            if abs(level.imbalance) > threshold
        ]
        return sorted(imbalanced, key=lambda x: abs(x.imbalance), reverse=True)

    def get_aggressive_buy_levels(self, threshold: Decimal) -> list[FootprintLevel]:
        """Получить уровни с агрессивными покупками (imbalance > threshold).

        Args:
            threshold: порог дисбаланса (например, 0.3 = 30% преобладание bid)

        Returns:
            Список уровней, отсортированных по imbalance descending
        """
        return sorted(
            [level for level in self.levels.values() if level.imbalance > threshold],
            key=lambda x: x.imbalance,
            reverse=True,
        )

    def get_aggressive_sell_levels(self, threshold: Decimal) -> list[FootprintLevel]:
        """Получить уровни с агрессивными продажами (imbalance < -threshold).

        Args:
            threshold: порог дисбаланса (например, 0.3 = 30% преобладание ask)

        Returns:
            Список уровней, отсортированных по imbalance ascending
        """
        return sorted(
            [level for level in self.levels.values() if level.imbalance < -threshold],
            key=lambda x: x.imbalance,
        )
