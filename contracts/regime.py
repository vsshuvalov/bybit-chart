"""
Orderflow regime detection and feature API (Roadmap §9.1 Этап 6).

Агрегирует все book-derived features для классификации текущего режима рынка.
"""

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class MarketRegime(str, Enum):
    """Классификация текущего режима рынка."""
    ACCUMULATION = "accumulation"  # Низкая волатильность, balanced orderflow
    DISTRIBUTION = "distribution"  # Высокая волатильность, imbalanced orderflow
    MARKUP = "markup"  # Восходящий тренд, buying pressure
    MARKDOWN = "markdown"  # Нисходящий тренд, selling pressure
    NEUTRAL = "neutral"  # Нет выраженного режима
    UNKNOWN = "unknown"  # Недостаточно данных


class OrderflowFeature(BaseModel):
    """Одна feature из orderflow analysis.

    Attributes:
        name: название feature (например, "walls", "absorption")
        active: активна ли feature в текущий момент
        value: числовое значение feature (опционально)
        confidence: уровень уверенности [0.0, 1.0]
        timestamp_ms: время последнего обновления
        metadata: дополнительные данные (side, price_level и т.д.)
    """
    name: str = Field(..., description="Feature name")
    active: bool = Field(..., description="Is feature currently active")
    value: float | None = Field(None, description="Numeric value if applicable")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    timestamp_ms: int = Field(..., description="Last update timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional data")


class RegimeState(BaseModel):
    """Текущее состояние рынка и активные features.

    Attributes:
        symbol: торговая пара
        regime: текущий классифицированный режим
        regime_confidence: уверенность в классификации [0.0, 1.0]
        features: список активных и неактивных features
        timestamp_ms: время вычисления состояния
        window_ms: размер временного окна для анализа
    """
    symbol: str = Field(..., description="Trading pair")
    regime: MarketRegime = Field(..., description="Current market regime")
    regime_confidence: float = Field(..., ge=0.0, le=1.0, description="Regime confidence")
    features: list[OrderflowFeature] = Field(..., description="All tracked features")
    timestamp_ms: int = Field(..., description="State computation timestamp")
    window_ms: int = Field(..., description="Analysis window size")

    class Config:
        use_enum_values = True


class FeatureImportance(BaseModel):
    """Важность feature для текущего режима.

    Attributes:
        name: название feature
        importance: важность [0.0, 1.0] — насколько feature влияет на regime
        contribution: положительный/отрицательный вклад в текущий regime
    """
    name: str = Field(..., description="Feature name")
    importance: float = Field(..., ge=0.0, le=1.0, description="Feature importance")
    contribution: float = Field(..., description="Contribution to current regime")


class RegimeAnalysis(BaseModel):
    """Полный анализ режима с feature importance.

    Attributes:
        state: текущее состояние рынка
        feature_importance: список feature importance scores
        regime_history: история смены режимов (опционально)
    """
    state: RegimeState = Field(..., description="Current market state")
    feature_importance: list[FeatureImportance] = Field(..., description="Feature importance scores")
    regime_history: list[dict[str, Any]] = Field(default_factory=list, description="Regime change history")
