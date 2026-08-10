"""
Pydantic модели для API request/response (Stage 3 / P3-S3-003).

Источник: Roadmap §7 (Query & Aggregation)
"""

from pydantic import BaseModel, Field, field_validator


class TradesQueryParams(BaseModel):
    """Query параметры для GET /api/v1/trades.

    Валидация:
    - start_ts < end_ts
    - limit в допустимых границах
    """

    symbol: str = Field(..., description="Symbol (BTCUSDT)", min_length=1)
    start_ts: int = Field(..., description="Начало диапазона (microseconds)", ge=0)
    end_ts: int = Field(..., description="Конец диапазона (microseconds)", ge=0)
    limit: int = Field(1000, description="Максимальное количество событий", ge=1, le=10000)
    event_type: str | None = Field(
        None, description="Фильтр по eventType (RawTrade, BookCheckpoint)"
    )

    @field_validator("end_ts")
    @classmethod
    def validate_time_range(cls, v: int, info) -> int:
        """Проверка: start_ts < end_ts."""
        if "start_ts" in info.data and v <= info.data["start_ts"]:
            raise ValueError("end_ts должен быть больше start_ts")
        return v


class TradesResponse(BaseModel):
    """Response для GET /api/v1/trades."""

    symbol: str = Field(..., description="Symbol")
    start_ts: int = Field(..., description="Начало диапазона (microseconds)")
    end_ts: int = Field(..., description="Конец диапазона (microseconds)")
    events: list[dict] = Field(..., description="Список событий (RawTrade/BookCheckpoint)")
    count: int = Field(..., description="Количество возвращённых событий")
    has_more: bool = Field(..., description="Есть ещё данные (count == limit)")


class OHLCQueryParams(BaseModel):
    """Query параметры для GET /api/v1/ohlc."""

    symbol: str = Field(..., description="Symbol (BTCUSDT)", min_length=1)
    start_ts: int = Field(..., description="Начало диапазона (microseconds)", ge=0)
    end_ts: int = Field(..., description="Конец диапазона (microseconds)", ge=0)
    interval: str = Field(..., description="Интервал candle (1m, 5m, 15m, 1h, 4h, 1d)")

    @field_validator("end_ts")
    @classmethod
    def validate_time_range(cls, v: int, info) -> int:
        """Проверка: start_ts < end_ts."""
        if "start_ts" in info.data and v <= info.data["start_ts"]:
            raise ValueError("end_ts должен быть больше start_ts")
        return v

    @field_validator("interval")
    @classmethod
    def validate_interval(cls, v: str) -> str:
        """Проверка допустимых интервалов."""
        valid_intervals = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]
        if v not in valid_intervals:
            raise ValueError(f"Интервал должен быть одним из: {', '.join(valid_intervals)}")
        return v


class OHLCCandle(BaseModel):
    """Одна OHLC candle."""

    timestamp_us: int = Field(..., description="Timestamp начала candle (microseconds)")
    open_ticks: int = Field(..., description="Open price (ticks)")
    high_ticks: int = Field(..., description="High price (ticks)")
    low_ticks: int = Field(..., description="Low price (ticks)")
    close_ticks: int = Field(..., description="Close price (ticks)")
    volume_steps: int = Field(..., description="Volume (qty steps)")
    trade_count: int = Field(..., description="Количество trades в candle")


class OHLCResponse(BaseModel):
    """Response для GET /api/v1/ohlc."""

    symbol: str = Field(..., description="Symbol")
    interval: str = Field(..., description="Интервал candle")
    start_ts: int = Field(..., description="Начало диапазона (microseconds)")
    end_ts: int = Field(..., description="Конец диапазона (microseconds)")
    candles: list[OHLCCandle] = Field(..., description="Список candles")
    count: int = Field(..., description="Количество candles")


class ErrorResponse(BaseModel):
    """Response для ошибок."""

    error: str = Field(..., description="Тип ошибки")
    detail: str = Field(..., description="Детали ошибки")
    status_code: int = Field(..., description="HTTP status code")
