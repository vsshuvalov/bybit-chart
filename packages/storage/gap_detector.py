"""
Gap Detection для мониторинга пропусков в данных (Этап 1 / P1-B2).

Источник: Roadmap §7 (Data Quality, gaps, watermark)

Gap — это пропуск в sequence numbers, указывающий на потерю данных:
- RawTrade: gap в sequence → пропущенные сделки
- BookCheckpoint: gap в updateId → пропущенные обновления book

SourceQuality states (Roadmap §7.2):
- BOOTSTRAP: начальная загрузка, нет истории
- LIVE_READY: непрерывный поток без gaps
- GAP: обнаружен пропуск, данные неполные
- DEGRADED: частые gaps или reconnects
- STALE: нет данных > threshold
"""

from dataclasses import dataclass
from typing import Literal

SourceQualityState = Literal[
    "BOOTSTRAP", "LIVE_READY", "GAP", "DEGRADED", "STALE", "REBUILDING", "LAGGING"
]


@dataclass
class Gap:
    """Обнаруженный gap в данных.

    Roadmap §7.3: Gap markers сохраняются в manifest.json.
    """

    event_type: str  # "RawTrade" или "BookCheckpoint"
    field_name: str  # "sequence" или "updateId"
    expected: int  # ожидаемое значение
    actual: int  # фактическое значение
    gap_size: int  # actual - expected
    first_offset: int  # WAL offset первого события после gap
    detected_at_ms: int  # timestamp обнаружения (milliseconds)

    def __repr__(self) -> str:
        return (
            f"Gap({self.event_type}.{self.field_name}: "
            f"expected={self.expected}, actual={self.actual}, "
            f"gap_size={self.gap_size}, offset={self.first_offset})"
        )


class GapDetector:
    """Детектор пропусков в sequence numbers.

    Использование:
        detector = GapDetector()

        # Для каждого события
        gap = detector.check_trade(trade, wal_offset)
        if gap:
            logger.warning(f"Обнаружен gap: {gap}")

        # Проверка состояния
        if detector.state == "GAP":
            # данные неполные
    """

    def __init__(self):
        """Инициализировать detector."""
        # Последние значения sequence/updateId
        self._last_trade_sequence: int | None = None
        self._last_book_update_id: int | None = None

        # Обнаруженные gaps
        self._gaps: list[Gap] = []

        # Состояние источника данных
        self._state: SourceQualityState = "BOOTSTRAP"

        # Счётчик событий с момента последнего gap
        self._events_since_gap = 0

    @property
    def state(self) -> SourceQualityState:
        """Текущее состояние качества данных."""
        return self._state

    @property
    def gaps(self) -> list[Gap]:
        """Список обнаруженных gaps."""
        return self._gaps.copy()

    def check_trade(self, trade_sequence: int, wal_offset: int) -> Gap | None:
        """Проверить RawTrade на gap в sequence.

        Args:
            trade_sequence: значение RawTrade.sequence
            wal_offset: WAL offset этого события

        Returns:
            Gap если обнаружен пропуск, иначе None
        """
        gap = None

        if self._last_trade_sequence is not None:
            expected = self._last_trade_sequence + 1

            if trade_sequence > expected:
                # Обнаружен gap
                gap_size = trade_sequence - expected
                gap = Gap(
                    event_type="RawTrade",
                    field_name="sequence",
                    expected=expected,
                    actual=trade_sequence,
                    gap_size=gap_size,
                    first_offset=wal_offset,
                    detected_at_ms=self._current_time_ms(),
                )
                self._gaps.append(gap)
                self._state = "GAP"
                self._events_since_gap = 0

            elif trade_sequence < expected:
                # Out-of-order или duplicate (не gap, но проблема)
                # Roadmap §7: логируем, но не меняем state
                pass

        # Обновляем последнее значение
        self._last_trade_sequence = max(
            trade_sequence, self._last_trade_sequence or 0
        )

        # Переход BOOTSTRAP → LIVE_READY
        if self._state == "BOOTSTRAP" and self._last_trade_sequence is not None:
            self._state = "LIVE_READY"

        # Переход GAP → LIVE_READY после N событий без gaps
        if self._state == "GAP":
            self._events_since_gap += 1
            if self._events_since_gap >= 100:  # threshold
                self._state = "LIVE_READY"

        return gap

    def check_book_checkpoint(
        self, update_id: int, wal_offset: int
    ) -> Gap | None:
        """Проверить BookCheckpoint на gap в updateId.

        Args:
            update_id: значение BookCheckpoint.update_id
            wal_offset: WAL offset этого события

        Returns:
            Gap если обнаружен пропуск, иначе None
        """
        gap = None

        if self._last_book_update_id is not None:
            expected = self._last_book_update_id + 1

            if update_id > expected:
                # Обнаружен gap
                gap_size = update_id - expected
                gap = Gap(
                    event_type="BookCheckpoint",
                    field_name="updateId",
                    expected=expected,
                    actual=update_id,
                    gap_size=gap_size,
                    first_offset=wal_offset,
                    detected_at_ms=self._current_time_ms(),
                )
                self._gaps.append(gap)
                self._state = "GAP"
                self._events_since_gap = 0

        # Обновляем последнее значение
        self._last_book_update_id = max(
            update_id, self._last_book_update_id or 0
        )

        # Переход BOOTSTRAP → LIVE_READY
        if self._state == "BOOTSTRAP" and self._last_book_update_id is not None:
            self._state = "LIVE_READY"

        # Переход GAP → LIVE_READY после N событий без gaps
        if self._state == "GAP":
            self._events_since_gap += 1
            if self._events_since_gap >= 100:
                self._state = "LIVE_READY"

        return gap

    def reset(self) -> None:
        """Сбросить состояние detector (для нового сегмента или reconnect)."""
        self._last_trade_sequence = None
        self._last_book_update_id = None
        self._gaps = []
        self._state = "BOOTSTRAP"
        self._events_since_gap = 0

    def _current_time_ms(self) -> int:
        """Текущее время в milliseconds."""
        import time

        return int(time.time() * 1000)

    def to_dict(self) -> dict:
        """Сериализовать detector state для manifest.json.

        Returns:
            Словарь с gaps и метаданными для JSON
        """
        return {
            "state": self._state,
            "last_trade_sequence": self._last_trade_sequence,
            "last_book_update_id": self._last_book_update_id,
            "gaps": [
                {
                    "event_type": g.event_type,
                    "field_name": g.field_name,
                    "expected": g.expected,
                    "actual": g.actual,
                    "gap_size": g.gap_size,
                    "first_offset": g.first_offset,
                    "detected_at_ms": g.detected_at_ms,
                }
                for g in self._gaps
            ],
        }
