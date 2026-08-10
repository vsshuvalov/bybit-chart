"""
Event Deserializer для Bybit publicTrade (Stage 2 / P2-S2-002).

Преобразует JSON от Bybit WebSocket → RawTrade из contracts/schemas.py.

Источник: BTCUSDT_Bybit_Intraday_Strategies.md §2.1
Официальная документация: https://bybit-exchange.github.io/docs/v5/websocket/public/trade

Пример Bybit JSON:
{
  "topic": "publicTrade.BTCUSDT",
  "type": "snapshot",
  "ts": 1672304486868,
  "data": [
    {
      "T": 1672304486865,
      "s": "BTCUSDT",
      "S": "Buy",
      "v": "0.001",
      "p": "16578.50",
      "L": "PlusTick",
      "i": "20f43950-d8dd-5b31-9112-a178eb6023af",
      "BT": false
    }
  ]
}

Маппинг полей:
- trade.T → exchangeTimestampMs
- message.ts → outerTimestampMs
- receiveTimestampMs — устанавливается при получении (time.time_ns() // 1_000_000)
- trade.p → priceTicks (масштабированное целое: Decimal → int)
- trade.v → qtySteps (масштабированное целое)
- trade.S → takerSide (Buy/Sell)
- trade.i → tradeId
- message.seq → sequence (если есть)
- trade.BT → isBlockTrade
- RPI (если есть) → isRpiTrade
"""

import time
from decimal import Decimal
from typing import Any

from contracts.schemas import RawTrade, TakerSide
from packages.numeric import BTCUSDT_PRICE_TICK, BTCUSDT_QTY_STEP


def deserialize_raw_trade(
    message: dict[str, Any],
    receive_timestamp_ms: int | None = None,
) -> list[RawTrade]:
    """Десериализовать publicTrade.{symbol} → список RawTrade.

    Args:
        message: JSON сообщение от Bybit WebSocket
        receive_timestamp_ms: время получения (если None — берётся текущее)

    Returns:
        Список RawTrade (message.data может содержать несколько сделок)

    Raises:
        ValueError: некорректный формат сообщения

    Пример:
        message = {
            "topic": "publicTrade.BTCUSDT",
            "ts": 1672304486868,
            "data": [{"T": 1672304486865, "s": "BTCUSDT", "S": "Buy", ...}]
        }
        trades = deserialize_raw_trade(message)
    """
    if receive_timestamp_ms is None:
        receive_timestamp_ms = time.time_ns() // 1_000_000

    # Проверка обязательных полей
    if "topic" not in message:
        raise ValueError("Отсутствует поле 'topic' в сообщении")
    if "data" not in message:
        raise ValueError("Отсутствует поле 'data' в сообщении")

    topic = message["topic"]
    if not topic.startswith("publicTrade."):
        raise ValueError(f"Некорректный topic: {topic}, ожидается publicTrade.*")

    symbol = topic.split(".", 1)[1]
    outer_timestamp_ms = message.get("ts", 0)
    sequence = message.get("seq", 0)  # seq может отсутствовать

    trades = []
    for trade_data in message["data"]:
        try:
            trade = _parse_trade_data(
                trade_data=trade_data,
                symbol=symbol,
                outer_timestamp_ms=outer_timestamp_ms,
                receive_timestamp_ms=receive_timestamp_ms,
                sequence=sequence,
            )
            trades.append(trade)
        except Exception as exc:
            raise ValueError(f"Ошибка парсинга trade: {exc}") from exc

    return trades


def _parse_trade_data(
    trade_data: dict[str, Any],
    symbol: str,
    outer_timestamp_ms: int,
    receive_timestamp_ms: int,
    sequence: int,
) -> RawTrade:
    """Распарсить один элемент из message.data."""
    # Обязательные поля
    trade_id = trade_data["i"]
    exchange_timestamp_ms = int(trade_data["T"])
    price_str = trade_data["p"]
    qty_str = trade_data["v"]
    side_str = trade_data["S"]

    # Конверсия price/qty → масштабированные целые
    price_decimal = Decimal(price_str)
    qty_decimal = Decimal(qty_str)

    price_ticks = int(price_decimal / BTCUSDT_PRICE_TICK)
    qty_steps = int(qty_decimal / BTCUSDT_QTY_STEP)

    # takerSide
    if side_str == "Buy":
        taker_side = TakerSide.BUY
    elif side_str == "Sell":
        taker_side = TakerSide.SELL
    else:
        raise ValueError(f"Некорректный takerSide: {side_str}")

    # Опциональные признаки
    is_block_trade = trade_data.get("BT", False)
    is_rpi_trade = trade_data.get("RPI", False)

    return RawTrade(
        venue="BYBIT",
        category="linear",
        symbol=symbol,
        trade_id=trade_id,
        sequence=sequence,
        exchange_timestamp_ms=exchange_timestamp_ms,
        outer_timestamp_ms=outer_timestamp_ms,
        receive_timestamp_ms=receive_timestamp_ms,
        price_ticks=price_ticks,
        qty_steps=qty_steps,
        taker_side=taker_side,
        is_block_trade=is_block_trade,
        is_rpi_trade=is_rpi_trade,
    )
