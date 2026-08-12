"""
Канонические Pydantic-схемы событий платформы.
Источник: Roadmap §5.2, §5.6; all-modules-data-persistence-architecture.md §5

Правила:
- price/qty — int (PriceTicks/QtySteps), никогда не float
- turnoverQuote отсутствует в RawTrade — биржа его не присылает (вычисляемое)
- int64 в JSON wire-format передаётся строкой (JS number не persistent)
- Decimal128 принимается строкой из JSON
- RawRpiBookEvent хранится отдельно от стандартного стакана
"""

from __future__ import annotations

import json
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Перечисления
# ---------------------------------------------------------------------------

class TakerSide(str, Enum):
    BUY = "Buy"
    SELL = "Sell"


class FeedKind(str, Enum):
    STANDARD = "standard"
    RPI = "rpi"
    FULL = "full"


class GapReason(str, Enum):
    DISCONNECT = "disconnect"
    RESTART = "restart"
    SEQUENCE_RULE = "sequenceRule"
    UNSYNCED = "unsynced"
    TRUNCATED = "truncated"
    LAGGED = "lagged"
    TRADE_OVERLAP_UNPROVEN = "tradeOverlapUnproven"
    LIQUIDATION_RECONNECT = "liquidationReconnect"
    STORAGE_FAILURE = "storageFailure"


class GapRecoverability(str, Enum):
    OPEN = "OPEN"
    RECOVERED = "RECOVERED"
    BOUNDED_UNRECOVERED = "BOUNDED_UNRECOVERED"


class EventType(str, Enum):
    RAW_TRADE = "RAW_TRADE"
    RAW_BOOK_EVENT = "RAW_BOOK_EVENT"
    RAW_RPI_BOOK_EVENT = "RAW_RPI_BOOK_EVENT"
    BOOK_CHECKPOINT = "BOOK_CHECKPOINT"
    RAW_LIQUIDATION = "RAW_LIQUIDATION"
    GAP_MARKER = "GAP_MARKER"


class LiquidatedPositionSide(str, Enum):
    LONG = "Long"
    SHORT = "Short"


# ---------------------------------------------------------------------------
# Вспомогательный тип: int-строка для JSON wire-format
# ---------------------------------------------------------------------------

class _IntStr(BaseModel):
    """Не используется напрямую — паттерн для валидаторов."""


def _parse_int_str(value: Any, field_name: str) -> int:
    """Принять int или строку-с-числом; отклонить float и bool."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name}: bool недопустим")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"{field_name}: не целое: {value!r}")
    raise TypeError(f"{field_name}: ожидается int или str, получен {type(value).__name__!r}")


def _parse_decimal_str(value: Any, field_name: str) -> Decimal:
    """Принять Decimal, int или строку; отклонить float."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name}: bool недопустим")
    if isinstance(value, float):
        raise TypeError(
            f"{field_name}: float запрещён в persistent схемах. "
            "Передайте строку или Decimal."
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, str)):
        try:
            result = Decimal(str(value))
        except Exception:
            raise ValueError(f"{field_name}: не Decimal: {value!r}")
        if not result.is_finite():
            raise ValueError(f"{field_name}: Decimal должен быть конечным: {value!r}")
        return result
    raise TypeError(f"{field_name}: ожидается str/Decimal/int, получен {type(value).__name__!r}")


# ---------------------------------------------------------------------------
# RawTrade  (Roadmap §5.6, all-modules §5.1)
# ---------------------------------------------------------------------------

class RawTrade(BaseModel):
    """Нормализованная сделка из publicTrade.{symbol}.

    Уникальный ключ: BYBIT:linear:{symbol}:{tradeId}
    turnoverQuote отсутствует — это вычисляемое price×qty, биржа его не присылает.
    """

    venue: Literal["BYBIT"] = "BYBIT"
    category: Literal["linear"] = "linear"
    symbol: str

    trade_id: str = Field(..., alias="tradeId")
    sequence: int = Field(..., description="seq — cross-sequence, не непрерывный")

    exchange_timestamp_ms: int = Field(..., alias="exchangeTimestampMs",
                                        description="trade.T — время исполнения на бирже")
    outer_timestamp_ms: int = Field(..., alias="outerTimestampMs",
                                     description="ts сообщения WS")
    receive_timestamp_ms: int = Field(..., alias="receiveTimestampMs")

    price_ticks: int = Field(..., alias="priceTicks", gt=0)
    qty_steps: int = Field(..., alias="qtySteps", gt=0)
    taker_side: TakerSide = Field(..., alias="takerSide")

    is_block_trade: bool = Field(False, alias="isBlockTrade")
    is_rpi_trade: bool = Field(False, alias="isRpiTrade")

    model_config = {"populate_by_name": True}

    @field_validator("price_ticks", "qty_steps", mode="before")
    @classmethod
    def _parse_int(cls, v: Any) -> int:
        return _parse_int_str(v, "priceTicks/qtySteps")

    @field_validator("sequence", "exchange_timestamp_ms",
                     "outer_timestamp_ms", "receive_timestamp_ms", mode="before")
    @classmethod
    def _parse_ts(cls, v: Any) -> int:
        return _parse_int_str(v, "timestamp/seq")

    def unique_key(self) -> str:
        """Детерминированный ключ дедупликации."""
        return f"BYBIT:linear:{self.symbol}:{self.trade_id}"


# ---------------------------------------------------------------------------
# RawBookEvent  (Roadmap §5.6, §8.2)
# ---------------------------------------------------------------------------

class RawBookLevel(BaseModel):
    """Один уровень стакана: [priceTicks, qtySteps]. size=0 → удалить уровень."""
    price_ticks: int = Field(..., alias="priceTicks", ge=0)
    qty_steps: int = Field(..., alias="qtySteps", ge=0)

    model_config = {"populate_by_name": True}

    @field_validator("price_ticks", "qty_steps", mode="before")
    @classmethod
    def _parse_int(cls, v: Any) -> int:
        return _parse_int_str(v, "bookLevel")


class RawBookEvent(BaseModel):
    """Snapshot или delta стандартного стакана.

    Не считать u и seq непрерывными по правилу prev+1.
    connectionEpoch обязателен — история книги достоверна только внутри эпохи.
    """

    venue: Literal["BYBIT"] = "BYBIT"
    category: Literal["linear"] = "linear"
    symbol: str
    depth: int = Field(..., description="1|50|200|1000")
    connection_epoch: str = Field(..., alias="connectionEpoch")

    feed_kind: FeedKind = Field(FeedKind.STANDARD, alias="feedKind")
    type: Literal["snapshot", "delta"]

    update_id: int = Field(..., alias="updateId", description="u")
    sequence: int = Field(..., alias="sequence", description="seq — не непрерывный")

    exchange_timestamp_ms: int = Field(..., alias="exchangeTimestampMs",
                                        description="cts — время matching engine")
    outer_timestamp_ms: int = Field(..., alias="outerTimestampMs")
    receive_timestamp_ms: int = Field(..., alias="receiveTimestampMs")

    schema_version: int = Field(1, alias="schemaVersion")

    bids: list[RawBookLevel] = Field(default_factory=list)
    asks: list[RawBookLevel] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @field_validator("depth", mode="before")
    @classmethod
    def _validate_depth(cls, v: Any) -> int:
        v = _parse_int_str(v, "depth")
        if v not in (1, 50, 200, 1000):
            raise ValueError(f"depth должен быть 1|50|200|1000, получен {v}")
        return v

    @field_validator("update_id", "sequence",
                     "exchange_timestamp_ms", "outer_timestamp_ms",
                     "receive_timestamp_ms", mode="before")
    @classmethod
    def _parse_int(cls, v: Any) -> int:
        return _parse_int_str(v, "updateId/seq/timestamp")


# ---------------------------------------------------------------------------
# RawRpiBookLevel и RawRpiBookEvent  (Roadmap §5.6, §8.2)
# ---------------------------------------------------------------------------

class RawRpiBookLevel(BaseModel):
    """Уровень RPI-стакана: [priceTicks, nonRpiQtySteps, rpiQtySteps].

    non-RPI component RPI feed не суммируется со standard book.
    """
    price_ticks: int = Field(..., alias="priceTicks", ge=0)
    non_rpi_qty_steps: int = Field(..., alias="nonRpiQtySteps", ge=0)
    rpi_qty_steps: int = Field(..., alias="rpiQtySteps", ge=0)

    model_config = {"populate_by_name": True}

    @field_validator("price_ticks", "non_rpi_qty_steps", "rpi_qty_steps", mode="before")
    @classmethod
    def _parse_int(cls, v: Any) -> int:
        return _parse_int_str(v, "rpiBookLevel")


class RawRpiBookEvent(BaseModel):
    """Snapshot или delta RPI-стакана (orderbook.rpi.{symbol}).

    Хранится отдельно от стандартного стакана — не смешивать.
    u=1 → RPI state заменяется полностью.
    """

    venue: Literal["BYBIT"] = "BYBIT"
    category: Literal["linear"] = "linear"
    symbol: str
    depth: Literal[50] = 50
    connection_epoch: str = Field(..., alias="connectionEpoch")

    type: Literal["snapshot", "delta"]
    update_id: int = Field(..., alias="updateId")
    sequence: int = Field(..., alias="sequence")

    exchange_timestamp_ms: int = Field(..., alias="exchangeTimestampMs")
    outer_timestamp_ms: int = Field(..., alias="outerTimestampMs")
    receive_timestamp_ms: int = Field(..., alias="receiveTimestampMs")

    schema_version: int = Field(1, alias="schemaVersion")

    bids: list[RawRpiBookLevel] = Field(default_factory=list)
    asks: list[RawRpiBookLevel] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @field_validator("update_id", "sequence",
                     "exchange_timestamp_ms", "outer_timestamp_ms",
                     "receive_timestamp_ms", mode="before")
    @classmethod
    def _parse_int(cls, v: Any) -> int:
        return _parse_int_str(v, "rpiBookEvent int field")


# ---------------------------------------------------------------------------
# BookCheckpoint  (Roadmap §5.6)
# ---------------------------------------------------------------------------

class BookCheckpoint(BaseModel):
    """Материализованный снапшот подписанной глубины книги.

    Хранит фактические level counts и coverage — нельзя без доказательства
    подписывать как исчерпывающую ликвидность рынка.
    """

    venue: Literal["BYBIT"] = "BYBIT"
    category: Literal["linear"] = "linear"
    symbol: str
    depth: int
    connection_epoch: str = Field(..., alias="connectionEpoch")

    update_id: int = Field(..., alias="updateId")
    sequence: int

    exchange_timestamp_ms: int = Field(..., alias="exchangeTimestampMs")
    outer_timestamp_ms: int = Field(..., alias="outerTimestampMs")
    receive_timestamp_ms: int = Field(..., alias="receiveTimestampMs")

    schema_version: int = Field(1, alias="schemaVersion")

    bids: list[RawBookLevel] = Field(default_factory=list)
    asks: list[RawBookLevel] = Field(default_factory=list)

    level_count: int = Field(..., alias="levelCount", ge=0)
    coverage_boundary_ticks: int = Field(..., alias="coverageBoundaryTicks", ge=0)
    coverage_bps: Decimal = Field(..., alias="coverageBps")
    is_feed_range_complete: bool = Field(..., alias="isFeedRangeComplete")

    stale: bool = False
    stale_reason: Optional[str] = Field(None, alias="staleReason")

    model_config = {"populate_by_name": True}

    @field_validator("depth", "update_id", "sequence", "level_count",
                     "coverage_boundary_ticks",
                     "exchange_timestamp_ms", "outer_timestamp_ms",
                     "receive_timestamp_ms", mode="before")
    @classmethod
    def _parse_int(cls, v: Any) -> int:
        return _parse_int_str(v, "bookCheckpoint int field")

    @field_validator("coverage_bps", mode="before")
    @classmethod
    def _parse_decimal(cls, v: Any) -> Decimal:
        return _parse_decimal_str(v, "coverageBps")


# ---------------------------------------------------------------------------
# RawLiquidation  (Roadmap §5.6, all-modules-changes §3.6)
# ---------------------------------------------------------------------------

class RawLiquidation(BaseModel):
    """Ликвидация из allLiquidation.{symbol}.

    Нормализация (обязательна на уровне schema, не UI):
      rawSide=Buy  → liquidatedPositionSide=Long  → inferredForcedFlow=Sell
      rawSide=Sell → liquidatedPositionSide=Short → inferredForcedFlow=Buy

    bankruptcyPriceTicks — цена банкротства, не фактическая fill price.
    У события нет exchange ID/seq → точная cross-reconnect дедупликация невозможна.
    """

    venue: Literal["BYBIT"] = "BYBIT"
    category: Literal["linear"] = "linear"
    symbol: str

    raw_side: TakerSide = Field(..., alias="rawSide")
    liquidated_position_side: LiquidatedPositionSide = Field(
        ..., alias="liquidatedPositionSide"
    )
    inferred_forced_flow: TakerSide = Field(..., alias="inferredForcedFlow")

    bankruptcy_price_ticks: int = Field(..., alias="bankruptcyPriceTicks", gt=0)
    qty_steps: int = Field(..., alias="qtySteps", gt=0)

    exchange_timestamp_ms: int = Field(..., alias="exchangeTimestampMs")
    outer_timestamp_ms: int = Field(..., alias="outerTimestampMs")
    receive_timestamp_ms: int = Field(..., alias="receiveTimestampMs")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _check_normalization(self) -> "RawLiquidation":
        """Проверить, что нормализация side согласована."""
        if self.raw_side == TakerSide.BUY:
            if self.liquidated_position_side != LiquidatedPositionSide.LONG:
                raise ValueError(
                    "rawSide=Buy → liquidatedPositionSide должен быть Long"
                )
            if self.inferred_forced_flow != TakerSide.SELL:
                raise ValueError(
                    "rawSide=Buy → inferredForcedFlow должен быть Sell"
                )
        else:
            if self.liquidated_position_side != LiquidatedPositionSide.SHORT:
                raise ValueError(
                    "rawSide=Sell → liquidatedPositionSide должен быть Short"
                )
            if self.inferred_forced_flow != TakerSide.BUY:
                raise ValueError(
                    "rawSide=Sell → inferredForcedFlow должен быть Buy"
                )
        return self

    @field_validator("bankruptcy_price_ticks", "qty_steps",
                     "exchange_timestamp_ms", "outer_timestamp_ms",
                     "receive_timestamp_ms", mode="before")
    @classmethod
    def _parse_int(cls, v: Any) -> int:
        return _parse_int_str(v, "liquidation int field")

    @classmethod
    def from_bybit(
        cls,
        *,
        symbol: str,
        raw_side: str,
        bankruptcy_price_ticks: Any,
        qty_steps: Any,
        exchange_timestamp_ms: Any,
        outer_timestamp_ms: Any,
        receive_timestamp_ms: Any,
    ) -> "RawLiquidation":
        """Создать из нормализованных данных Bybit с автоматическим выводом side."""
        side = TakerSide(raw_side)
        if side == TakerSide.BUY:
            pos_side = LiquidatedPositionSide.LONG
            forced_flow = TakerSide.SELL
        else:
            pos_side = LiquidatedPositionSide.SHORT
            forced_flow = TakerSide.BUY

        return cls(
            symbol=symbol,
            rawSide=side,
            liquidatedPositionSide=pos_side,
            inferredForcedFlow=forced_flow,
            bankruptcyPriceTicks=bankruptcy_price_ticks,
            qtySteps=qty_steps,
            exchangeTimestampMs=exchange_timestamp_ms,
            outerTimestampMs=outer_timestamp_ms,
            receiveTimestampMs=receive_timestamp_ms,
        )


# ---------------------------------------------------------------------------
# GapMarker  (Roadmap §5.6)
# ---------------------------------------------------------------------------

class GapMarker(BaseModel):
    """Маркер разрыва в потоке данных.

    Неизвестный участок данных всегда маркируется gap, не интерполируется.
    """

    gap_id: str = Field(..., alias="gapId")
    venue: Literal["BYBIT"] = "BYBIT"
    category: Literal["linear"] = "linear"
    symbol: str
    feed_kind: FeedKind = Field(..., alias="feedKind")
    depth: Optional[int] = None

    start_time_ms: int = Field(..., alias="startTimeMs")
    end_time_ms: Optional[int] = Field(None, alias="endTimeMs")
    detected_at_ms: int = Field(..., alias="detectedAtMs")

    previous_connection_epoch: str = Field(..., alias="previousConnectionEpoch")
    next_connection_epoch: Optional[str] = Field(None, alias="nextConnectionEpoch")

    reason: GapReason
    recoverability: GapRecoverability = GapRecoverability.OPEN

    blocks_modules: list[str] = Field(default_factory=list, alias="blocksModules")
    source_data_revision: Optional[str] = Field(None, alias="sourceDataRevision")
    evidence_refs: list[str] = Field(default_factory=list, alias="evidenceRefs")

    model_config = {"populate_by_name": True}

    @field_validator("start_time_ms", "detected_at_ms", mode="before")
    @classmethod
    def _parse_int(cls, v: Any) -> int:
        return _parse_int_str(v, "gapMarker timestamp")

    @field_validator("end_time_ms", mode="before")
    @classmethod
    def _parse_optional_int(cls, v: Any) -> Optional[int]:
        if v is None:
            return None
        return _parse_int_str(v, "endTimeMs")


# ---------------------------------------------------------------------------
# RawEventEnvelope  (Roadmap §5.2)
# ---------------------------------------------------------------------------

class RawEventEnvelope(BaseModel):
    """Технический конверт каждого события.

    Поля:
      protocolVersion — major.minor; ломающая смена увеличивает major
      schemaVersion — версия payload-схемы
      eventId — детерминирован и стабилен при replay
      walOffset — позиция в WAL (ровно одна запись после durable accept)
      dataRevision — версия производных данных при изменении

    Trade key: BYBIT:linear:{symbol}:{tradeId}
    int64 и Decimal в JSON wire-format — строками.
    """

    protocol_version: str = Field(..., alias="protocolVersion",
                                   description="major.minor; ломающая смена = новый major")
    schema_version: int = Field(..., alias="schemaVersion")
    event_id: str = Field(..., alias="eventId",
                          description="детерминированный ключ; стабилен при replay")
    event_type: EventType = Field(..., alias="eventType")

    venue: Literal["BYBIT"] = "BYBIT"
    category: Literal["linear"] = "linear"
    symbol: str

    collector_id: str = Field(..., alias="collectorId")
    connection_epoch: str = Field(..., alias="connectionEpoch")
    partition_id: str = Field(..., alias="partitionId")

    source_sequence: Optional[int] = Field(None, alias="sourceSequence",
                                            description="опционально, зависит от feed")
    update_id: Optional[int] = Field(None, alias="updateId")

    event_time_ms: int = Field(..., alias="eventTimeMs")
    outer_time_ms: int = Field(..., alias="outerTimeMs")
    receive_time_ms: int = Field(..., alias="receiveTimeMs")

    wal_offset: int = Field(..., alias="walOffset", ge=0,
                             description="позиция в WAL; продвигается только после fsync")
    data_revision: str = Field(..., alias="dataRevision")
    quality_flags: int = Field(0, alias="qualityFlags")

    payload: dict[str, Any] = Field(
        ..., description="сериализованный доменный объект (RawTrade, RawBookEvent, ...)"
    )

    model_config = {"populate_by_name": True}

    @field_validator("schema_version", "event_time_ms", "outer_time_ms",
                     "receive_time_ms", "wal_offset", "quality_flags",
                     mode="before")
    @classmethod
    def _parse_int(cls, v: Any) -> int:
        return _parse_int_str(v, "envelope int field")

    @field_validator("source_sequence", "update_id", mode="before")
    @classmethod
    def _parse_optional_int(cls, v: Any) -> Optional[int]:
        if v is None:
            return None
        return _parse_int_str(v, "sourceSequence/updateId")


# ---------------------------------------------------------------------------
# Orderflow Events (Этап 4: IPC publisher от orderflow-worker)
# ---------------------------------------------------------------------------

class OrderflowSweep(BaseModel):
    """Sweep event: агрессивный ордер сметающий несколько уровней стакана."""
    symbol: str
    timestamp: int  # milliseconds
    side: str  # "Buy" or "Sell"
    levels_swept: int
    volume: float
    price_start: float
    price_end: float


class OrderflowCascade(BaseModel):
    """Liquidation cascade event: последовательность быстрых ликвидаций."""
    symbol: str
    timestamp: int
    side: str
    volume: float
    price_range: float


class OrderflowOFI(BaseModel):
    """Order Flow Imbalance update."""
    symbol: str
    timestamp: int
    ofi: float
    microprice: float
    imbalance: float


class OrderflowWall(BaseModel):
    """Wall detected: крупный лимитный ордер в стакане."""
    symbol: str
    timestamp: int
    side: str
    price: float
    size: float


class OrderflowRegimeChange(BaseModel):
    """Market regime change event."""
    symbol: str
    timestamp: int
    old_regime: str
    new_regime: str
    confidence: float
