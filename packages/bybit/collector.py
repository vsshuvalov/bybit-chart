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

from contracts.schemas import RawTrade
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
        payload = self._serialize_trade(trade)

        result = self.wal.append(payload)
        logger.debug(f"Записан trade: offset={result.wal_offset}, id={trade.trade_id}")

        return result.wal_offset

    def _serialize_trade(self, trade: RawTrade) -> bytes:
        """Сериализовать RawTrade → bytes.

        Roadmap §6: Frame.payload — opaque bytes, интерпретация на стороне reader.
        MVP: JSON (читаемый, отладочный).
        ADR-002: Protobuf (компактный, типизированный).
        """
        # Используем model_dump() для сериализации Pydantic модели
        data = trade.model_dump(by_alias=False)  # используем Python-имена полей
        return json.dumps(data, separators=(",", ":")).encode("utf-8")

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

    Обратная операция к EventCollector._serialize_trade().
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
