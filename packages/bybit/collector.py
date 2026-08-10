"""
Event Collector для записи Bybit событий в WAL (Stage 2 / P2-S2-004).

Источник: Roadmap §5.6, §6
Архитектура: WebSocket → Deserializer → Collector → WAL → Parquet

Коллектор:
- Принимает RawTrade из deserializer
- Сериализует в bytes (JSON для MVP, Protobuf в ADR-002)
- Вызывает wal.append(payload)
- Batch commit по GroupCommitPolicy

Интеграция с close_and_publish_segment():
- Заменяет stub-десериализацию Frame.payload → row
- Читает реальный RawTrade из payload
- Конвертирует в row для Parquet с правильными полями
"""

import json
import logging
from pathlib import Path
from typing import Any

from contracts.schemas import RawTrade, BookCheckpoint
from packages.storage import WalPartition, GroupCommitPolicy

logger = logging.getLogger(__name__)


class EventCollector:
    """Коллектор событий для записи в WAL.

    Использование:
        collector = EventCollector(
            partition_dir=Path("/data/BTCUSDT"),
            partition_id="BTCUSDT",
        )
        collector.append_trade(trade)
        collector.flush()
    """

    def __init__(
        self,
        partition_dir: Path | str,
        partition_id: str,
        *,
        max_segment_bytes: int = 8 * 1024 * 1024,
        group_commit: GroupCommitPolicy | None = None,
    ):
        """Инициализировать коллектор.

        Args:
            partition_dir: каталог WAL partition
            partition_id: идентификатор partition (symbol)
            max_segment_bytes: размер сегмента для roll
            group_commit: политика batch commit
        """
        self.partition_dir = Path(partition_dir)
        self.partition_id = partition_id

        if group_commit is None:
            # Дефолт: commit каждые 100 записей или 1MB
            group_commit = GroupCommitPolicy(max_records=100, max_bytes=1024 * 1024)

        self.wal = WalPartition(
            directory=self.partition_dir,
            partition_id=partition_id,
            max_segment_bytes=max_segment_bytes,
            group_commit=group_commit,
        )

        # Восстанавливаем WAL при старте
        recovery = self.wal.recover()
        logger.info(
            f"EventCollector восстановлен: partition={partition_id}, "
            f"last_valid_offset={recovery.last_valid_offset}, "
            f"valid_records={recovery.valid_records}"
        )

    def append_trade(self, trade: RawTrade) -> int:
        """Добавить RawTrade в WAL.

        Args:
            trade: десериализованная сделка

        Returns:
            wal_offset записи

        Примечание: commit происходит автоматически по GroupCommitPolicy.
        """
        # Сериализация: JSON для MVP (ADR-002 заменит на Protobuf)
        payload = self._serialize_event(trade)

        result = self.wal.append(payload)
        logger.debug(f"Записан trade: offset={result.wal_offset}, id={trade.trade_id}")

        return result.wal_offset

    def append_book_checkpoint(self, checkpoint: BookCheckpoint) -> int:
        """Добавить BookCheckpoint в WAL.

        Args:
            checkpoint: десериализованный orderbook snapshot

        Returns:
            wal_offset записи

        Roadmap §8.2: Только snapshot, delta reconstruction — будущее расширение.
        """
        # Сериализация: JSON для MVP
        payload = self._serialize_event(checkpoint)

        result = self.wal.append(payload)
        logger.debug(
            f"Записан book checkpoint: offset={result.wal_offset}, "
            f"symbol={checkpoint.symbol}, depth={checkpoint.depth}, "
            f"levelCount={checkpoint.level_count}"
        )

        return result.wal_offset

    def _serialize_event(self, event: RawTrade | BookCheckpoint) -> bytes:
        """Сериализовать событие (RawTrade или BookCheckpoint) → bytes.

        Roadmap §6: Frame.payload — opaque bytes, интерпретация на стороне reader.
        MVP: JSON (читаемый, отладочный).
        ADR-002: Protobuf (компактный, типизированный).
        """
        # Используем model_dump() для сериализации Pydantic модели
        data = event.model_dump(mode='json')  # mode='json' конвертирует Decimal → str
        return json.dumps(data, separators=(",", ":")).encode("utf-8")

    def _serialize_trade(self, trade: RawTrade) -> bytes:
        """Сериализовать RawTrade → bytes.

        Deprecated: используйте _serialize_event().
        Оставлен для обратной совместимости.
        """
        return self._serialize_event(trade)

    def flush(self) -> None:
        """Принудительный commit pending records.

        Roadmap §6.3: live publish должен использовать durable_offset как ceiling.
        """
        self.wal.commit()
        logger.debug(f"Flush: durable_offset={self.wal.durable_offset}")

    def close(self) -> None:
        """Закрыть WAL partition."""
        self.wal.close()
        logger.info(f"EventCollector закрыт: partition={self.partition_id}")


def deserialize_trade_from_payload(payload: bytes) -> RawTrade:
    """Десериализовать Frame.payload → RawTrade.

    Обратная операция к EventCollector._serialize_event().
    Используется в close_and_publish_segment() для конверсии WAL → Parquet rows.

    Args:
        payload: Frame.payload (JSON-encoded RawTrade)

    Returns:
        Десериализованный RawTrade

    Raises:
        ValueError: некорректный payload
    """
    try:
        data = json.loads(payload.decode("utf-8"))
        return RawTrade(**data)
    except Exception as exc:
        raise ValueError(f"Не удалось десериализовать RawTrade: {exc}") from exc


def deserialize_event_from_payload(payload: bytes) -> RawTrade | BookCheckpoint:
    """Десериализовать Frame.payload → RawTrade или BookCheckpoint.

    Универсальная десериализация для всех типов событий.
    Определяет тип по наличию полей в JSON.

    Args:
        payload: Frame.payload (JSON-encoded event)

    Returns:
        Десериализованное событие (RawTrade или BookCheckpoint)

    Raises:
        ValueError: некорректный payload или неизвестный тип события
    """
    try:
        data = json.loads(payload.decode("utf-8"))

        # Определяем тип события по наличию характерных полей
        if "trade_id" in data:
            return RawTrade(**data)
        elif "bids" in data or "asks" in data:
            return BookCheckpoint(**data)
        else:
            raise ValueError(f"Неизвестный тип события: {list(data.keys())}")

    except Exception as exc:
        raise ValueError(f"Не удалось десериализовать событие: {exc}") from exc


def raw_trade_to_parquet_row(trade: RawTrade) -> dict[str, Any]:
    """Конвертировать RawTrade → row для Parquet.

    Маппинг:
    - timestampUs = exchange_timestamp_ms * 1000 (ms → µs)
    - eventType = "RawTrade"
    - symbol = trade.symbol
    - priceTicks = trade.price_ticks
    - qtySteps = trade.qty_steps
    - Остальные поля = defaults или 0 (для BookCheckpoint-специфичных полей)

    Args:
        trade: десериализованный RawTrade

    Returns:
        Словарь для ParquetWriter.write_batch()
    """
    from decimal import Decimal

    return {
        "timestampUs": trade.exchange_timestamp_ms * 1000,
        "eventType": "RawTrade",
        "symbol": trade.symbol,
        "priceTicks": trade.price_ticks,
        "qtySteps": trade.qty_steps,
        "takerSide": trade.taker_side.value,  # TakerSide enum → string ("Buy" | "Sell")
        # BookCheckpoint-специфичные поля (stub для RawTrade)
        "depth": 0,
        "updateId": 0,
        "sequence": trade.sequence,
        "levelCount": 0,
        "coverageBoundaryTicks": 0,
        "coverageBps": Decimal("0.0000"),
        "isFeedRangeComplete": False,
        # Метаданные соединения
        "connectionEpoch": "live",  # stub: реальная эпоха из connection manager
        "exchangeTimestampMs": trade.exchange_timestamp_ms,
        "outerTimestampMs": trade.outer_timestamp_ms,
        "receiveTimestampMs": trade.receive_timestamp_ms,
    }


def book_checkpoint_to_parquet_row(checkpoint: BookCheckpoint) -> dict[str, Any]:
    """Конвертировать BookCheckpoint → row для Parquet.

    Маппинг:
    - timestampUs = exchange_timestamp_ms * 1000 (ms → µs)
    - eventType = "BookCheckpoint"
    - symbol = checkpoint.symbol
    - depth, updateId, sequence, levelCount, coverage metrics
    - priceTicks/qtySteps = 0 (stub для RawTrade-специфичных полей)

    Roadmap §6: bids/asks сохраняются как JSON-encoded строки (MVP).
    Будущее: struct<price:int64, qty:int64>[] через PyArrow.

    Args:
        checkpoint: десериализованный BookCheckpoint

    Returns:
        Словарь для ParquetWriter.write_batch()
    """
    import json

    return {
        "timestampUs": checkpoint.exchange_timestamp_ms * 1000,
        "eventType": "BookCheckpoint",
        "symbol": checkpoint.symbol,
        # RawTrade-специфичные поля (stub для BookCheckpoint)
        "priceTicks": 0,
        "qtySteps": 0,
        "takerSide": "",  # stub для BookCheckpoint (нет taker side)
        # BookCheckpoint-специфичные поля
        "depth": checkpoint.depth,
        "updateId": checkpoint.update_id,
        "sequence": checkpoint.sequence,
        "levelCount": checkpoint.level_count,
        "coverageBoundaryTicks": checkpoint.coverage_boundary_ticks,
        "coverageBps": checkpoint.coverage_bps,
        "isFeedRangeComplete": checkpoint.is_feed_range_complete,
        # Метаданные соединения
        "connectionEpoch": checkpoint.connection_epoch,
        "exchangeTimestampMs": checkpoint.exchange_timestamp_ms,
        "outerTimestampMs": checkpoint.outer_timestamp_ms,
        "receiveTimestampMs": checkpoint.receive_timestamp_ms,
        # Bids/asks как JSON strings (MVP)
        # TODO: мигрировать на struct arrays через ADR
        "bids": json.dumps([{"price": b.price_ticks, "qty": b.qty_steps} for b in checkpoint.bids]),
        "asks": json.dumps([{"price": a.price_ticks, "qty": a.qty_steps} for a in checkpoint.asks]),
    }


def event_to_parquet_row(event: RawTrade | BookCheckpoint) -> dict[str, Any]:
    """Конвертировать любое событие → row для Parquet.

    Универсальная конверсия, определяет тип события и вызывает соответствующую функцию.

    Args:
        event: десериализованное событие (RawTrade или BookCheckpoint)

    Returns:
        Словарь для ParquetWriter.write_batch()
    """
    if isinstance(event, RawTrade):
        return raw_trade_to_parquet_row(event)
    elif isinstance(event, BookCheckpoint):
        return book_checkpoint_to_parquet_row(event)
    else:
        raise ValueError(f"Неизвестный тип события: {type(event)}")
