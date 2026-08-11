"""
RawKline contract (Roadmap §8.2 RPI feed).

Источник: Bybit V5 WebSocket API kline.{interval}.{symbol}
Документация: https://bybit-exchange.github.io/docs/v5/websocket/public/kline
"""

from decimal import Decimal

from pydantic import BaseModel, Field


class RawKline(BaseModel):
    """1-minute OHLCV candlestick от Bybit kline feed.

    Roadmap §8.2: RPI feed записывается отдельно, не участвует в detector/Heatmap.

    Использование:
    - Account-independent kline validation
    - Scheduled market history
    - OHLCV baseline для проверки derived analytics

    Атрибуты:
        venue: биржа (всегда "BYBIT")
        category: категория инструмента ("linear", "inverse", "spot")
        symbol: торговая пара (например, "BTCUSDT")
        interval: интервал свечи ("1", "3", "5", "15", "30", "60", "D")
        start_timestamp_ms: время начала свечи (Unix timestamp, миллисекунды)
        end_timestamp_ms: время окончания свечи (Unix timestamp, миллисекунды)
        open: цена открытия (Decimal)
        high: максимальная цена (Decimal)
        low: минимальная цена (Decimal)
        close: цена закрытия (Decimal)
        volume: объём торгов (Decimal)
        turnover: оборот в quote currency (Decimal)
        confirm: флаг завершения свечи (False = обновляется, True = финальная)
        exchange_timestamp_ms: серверное время Bybit (миллисекунды)
        receive_timestamp_ms: время получения сообщения (миллисекунды)
    """

    venue: str = Field(frozen=True)
    category: str = Field(frozen=True)
    symbol: str = Field(frozen=True)
    interval: str = Field(frozen=True)

    start_timestamp_ms: int = Field(frozen=True)
    end_timestamp_ms: int = Field(frozen=True)

    open: Decimal = Field(frozen=True)
    high: Decimal = Field(frozen=True)
    low: Decimal = Field(frozen=True)
    close: Decimal = Field(frozen=True)
    volume: Decimal = Field(frozen=True)
    turnover: Decimal = Field(frozen=True)

    confirm: bool = Field(frozen=True)
    exchange_timestamp_ms: int = Field(frozen=True)
    receive_timestamp_ms: int = Field(frozen=True)

    def __str__(self) -> str:
        return (
            f"RawKline({self.symbol} {self.interval}m "
            f"start={self.start_timestamp_ms} "
            f"OHLC={self.open}/{self.high}/{self.low}/{self.close} "
            f"vol={self.volume} confirm={self.confirm})"
        )
