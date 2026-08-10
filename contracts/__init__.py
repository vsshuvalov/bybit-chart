"""
contracts/ — канонические схемы событий платформы.
Источник: Roadmap §5.2, §5.6, all-modules-data-persistence-architecture.md §5

Все поля, участвующие в хранении и replay:
  price       → PriceTicks (int)
  quantity    → QtySteps (int)
  turnover    → Decimal128
  float       — только в UI / некритичных визуальных вычислениях

JSON wire-format: int64 и Decimal передаются как строки (JavaScript number
не является persistent wire-format для больших целых, Roadmap §5.2).
"""

from contracts.schemas import (
    TakerSide,
    FeedKind,
    GapReason,
    GapRecoverability,
    RawTrade,
    RawBookLevel,
    RawBookEvent,
    RawRpiBookLevel,
    RawRpiBookEvent,
    BookCheckpoint,
    RawLiquidation,
    GapMarker,
    RawEventEnvelope,
    EventType,
)

__all__ = [
    "TakerSide",
    "FeedKind",
    "GapReason",
    "GapRecoverability",
    "RawTrade",
    "RawBookLevel",
    "RawBookEvent",
    "RawRpiBookLevel",
    "RawRpiBookEvent",
    "BookCheckpoint",
    "RawLiquidation",
    "GapMarker",
    "RawEventEnvelope",
    "EventType",
]
