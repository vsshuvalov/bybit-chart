"""
Event Deserializer для Bybit orderbook (Stage 2 / P2-S2-003).

Преобразует JSON от Bybit WebSocket → BookCheckpoint из contracts/schemas.py.

Источник: BTCUSDT_Bybit_Intraday_Strategies.md §2.2
Официальная документация: https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook

Пример Bybit JSON (snapshot):
{
  "topic": "orderbook.200.BTCUSDT",
  "type": "snapshot",
  "ts": 1672304484978,
  "data": {
    "s": "BTCUSDT",
    "b": [["16493.50", "0.006"], ["16493.00", "0.100"], ...],
    "a": [["16611.00", "0.029"], ["16612.00", "0.213"], ...],
    "u": 18521288,
    "seq": 7961638724
  }
}

Маппинг полей:
- data.u → updateId
- data.seq → sequence
- message.ts → outerTimestampMs
- receiveTimestampMs — устанавливается при получении
- data.b → bids (список [price, qty])
- data.a → asks (список [price, qty])
- levelCount, coverageBps — вычисляются из snapshot
- depth — извлекается из topic (orderbook.{depth}.{symbol})

Roadmap §8.2: Full book reconstruction требует обработки delta updates.
MVP: Обрабатываем только snapshot для начальной загрузки.
"""

import time
from decimal import Decimal
from typing import Any

from contracts.schemas import BookCheckpoint, RawBookLevel
from packages.numeric import BTCUSDT_PRICE_TICK, BTCUSDT_QTY_STEP


def deserialize_book_snapshot(
    message: dict[str, Any],
    receive_timestamp_ms: int | None = None,
    connection_epoch: str = "live",
) -> BookCheckpoint:
    """Десериализовать orderbook snapshot → BookCheckpoint.

    Args:
        message: JSON сообщение от Bybit WebSocket
        receive_timestamp_ms: время получения (если None — берётся текущее)
        connection_epoch: идентификатор соединения (для replay)

    Returns:
        BookCheckpoint с материализованным snapshot

    Raises:
        ValueError: некорректный формат сообщения или не snapshot

    Примечание: Delta updates (type="delta") требуют отдельной обработки
    и book reconstruction (Roadmap §8.2). Сейчас поддерживаем только snapshot.

    Пример:
        message = {
            "topic": "orderbook.200.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304484978,
            "data": {"s": "BTCUSDT", "b": [...], "a": [...], "u": 18521288, "seq": 7961638724}
        }
        checkpoint = deserialize_book_snapshot(message)
    """
    if receive_timestamp_ms is None:
        receive_timestamp_ms = time.time_ns() // 1_000_000

    # Проверка обязательных полей
    if "topic" not in message:
        raise ValueError("Отсутствует поле 'topic' в сообщении")
    if "type" not in message:
        raise ValueError("Отсутствует поле 'type' в сообщении")
    if "data" not in message:
        raise ValueError("Отсутствует поле 'data' в сообщении")

    topic = message["topic"]
    msg_type = message["type"]

    if not topic.startswith("orderbook."):
        raise ValueError(f"Некорректный topic: {topic}, ожидается orderbook.*")

    if msg_type != "snapshot":
        raise ValueError(
            f"Поддерживаются только snapshot. Получен type={msg_type}. "
            f"Delta reconstruction требует Roadmap §8.2."
        )

    # Парсинг topic: orderbook.{depth}.{symbol}
    parts = topic.split(".")
    if len(parts) != 3:
        raise ValueError(f"Некорректный формат topic: {topic}")

    depth = int(parts[1])
    symbol = parts[2]

    outer_timestamp_ms = message.get("ts", 0)
    data = message["data"]

    # Парсинг data
    update_id = int(data["u"])
    sequence = int(data.get("seq", 0))

    # exchangeTimestampMs отсутствует в orderbook (в отличие от publicTrade)
    # Используем outerTimestampMs как fallback
    exchange_timestamp_ms = outer_timestamp_ms

    # Парсинг bids/asks
    bids = _parse_book_levels(data.get("b", []))
    asks = _parse_book_levels(data.get("a", []))

    # Вычисление coverage
    level_count = len(bids) + len(asks)
    coverage_stats = _calculate_coverage(bids, asks)

    return BookCheckpoint(
        venue="BYBIT",
        category="linear",
        symbol=symbol,
        depth=depth,
        connection_epoch=connection_epoch,
        update_id=update_id,
        sequence=sequence,
        exchange_timestamp_ms=exchange_timestamp_ms,
        outer_timestamp_ms=outer_timestamp_ms,
        receive_timestamp_ms=receive_timestamp_ms,
        bids=bids,
        asks=asks,
        level_count=level_count,
        coverage_boundary_ticks=coverage_stats["boundary_ticks"],
        coverage_bps=coverage_stats["coverage_bps"],
        is_feed_range_complete=coverage_stats["is_complete"],
    )


def _parse_book_levels(raw_levels: list[list[str]]) -> list[RawBookLevel]:
    """Распарсить список [price, qty] → RawBookLevel.

    Args:
        raw_levels: список ["price", "qty"] от Bybit

    Returns:
        Список RawBookLevel с масштабированными int
    """
    levels = []
    for raw_level in raw_levels:
        if len(raw_level) != 2:
            continue  # пропускаем некорректные записи

        price_str, qty_str = raw_level
        price_decimal = Decimal(price_str)
        qty_decimal = Decimal(qty_str)

        price_ticks = int(price_decimal / BTCUSDT_PRICE_TICK)
        qty_steps = int(qty_decimal / BTCUSDT_QTY_STEP)

        # Фильтруем нулевые уровни (Bybit может отправлять qty=0 для удаления)
        if qty_steps > 0:
            levels.append(
                RawBookLevel(price_ticks=price_ticks, qty_steps=qty_steps)
            )

    return levels


def _calculate_coverage(
    bids: list[RawBookLevel], asks: list[RawBookLevel]
) -> dict[str, Any]:
    """Вычислить coverage metrics для snapshot.

    Roadmap §8.2: coverage — это расстояние от mid до самого дальнего уровня.
    coverageBps = (boundary - mid) / mid * 10000.

    Args:
        bids: список bid levels (отсортированы по убыванию цены)
        asks: список ask levels (отсортированы по возрастанию цены)

    Returns:
        Dict с boundary_ticks, coverage_bps, is_complete
    """
    if not bids or not asks:
        # Нет стакана → нулевое покрытие
        return {
            "boundary_ticks": 0,
            "coverage_bps": Decimal("0.0000"),
            "is_complete": False,
        }

    # Лучшие цены (предполагаем, что Bybit отправляет отсортированные уровни)
    best_bid_ticks = bids[0].price_ticks
    best_ask_ticks = asks[0].price_ticks

    # Mid price
    mid_ticks = (best_bid_ticks + best_ask_ticks) / 2

    # Boundary — самый дальний уровень от mid
    worst_bid_ticks = bids[-1].price_ticks if bids else best_bid_ticks
    worst_ask_ticks = asks[-1].price_ticks if asks else best_ask_ticks

    bid_distance = abs(mid_ticks - worst_bid_ticks)
    ask_distance = abs(worst_ask_ticks - mid_ticks)

    boundary_distance = max(bid_distance, ask_distance)
    boundary_ticks = int(boundary_distance)

    # Coverage в basis points
    if mid_ticks > 0:
        coverage_bps = Decimal(str(boundary_distance / mid_ticks * 10000))
        # Округляем до 4 знаков (ADR-004: Decimal128(18, 4))
        coverage_bps = coverage_bps.quantize(Decimal("0.0001"))
    else:
        coverage_bps = Decimal("0.0000")

    # is_complete: считаем полным, если есть хотя бы depth/2 уровней с каждой стороны
    # (эвристика для MVP; реальная проверка требует знания subscribed depth)
    is_complete = len(bids) >= 5 and len(asks) >= 5

    return {
        "boundary_ticks": boundary_ticks,
        "coverage_bps": coverage_bps,
        "is_complete": is_complete,
    }
