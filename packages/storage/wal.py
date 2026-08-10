"""
WAL: append-only журнал сырых событий с group commit и crash-recovery.
Источник: Roadmap §5.1, §6.2, §6.3

Принцип доставки (Roadmap §5.1):
    collector: append + fsync WAL
    → non-blocking live publish
    → analytics получает at-least-once
    → durable checkpoint
    → после пропуска дочитывает WAL

Инвариант v1: analytics и trading получают только события с
walOffset <= durableOffset. Speculative pre-fsync tail запрещён.

fsync допускается выполнять bounded group commit, а не syscall на каждое
событие; при этом durableOffset продвигается явно.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from packages.storage.frames import (
    HEADER_SIZE,
    Frame,
    encode_frame,
    frame_size,
    scan_frames,
)
from packages.storage.offsets import OffsetSet

SEGMENT_SUFFIX = ".wal"
SEGMENT_NAME_RE = re.compile(r"^(?P<base>\d{20})\.wal$")


def segment_name(base_offset: int) -> str:
    """Имя сегмента кодирует его base offset — так порядок = лексикографический."""
    return f"{base_offset:020d}{SEGMENT_SUFFIX}"


def parse_segment_name(name: str) -> int | None:
    m = SEGMENT_NAME_RE.match(name)
    if m is None:
        return None
    return int(m.group("base"))


def fsync_dir(path: Path) -> None:
    """fsync каталога — обязателен после atomic rename (Roadmap §6.4)."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class RecoveryReport:
    """Итог recovery при старте.

    durable_violation=True означает, что отброшенный хвост находился
    ниже ранее объявленного durableOffset. Roadmap §6.2: это incident.
    """

    partition_id: str
    scanned_segments: int
    valid_records: int
    last_valid_offset: int
    truncated_bytes: int
    torn: bool
    corrupt: bool
    durable_violation: bool
    error: str | None = None

    @property
    def clean(self) -> bool:
        return self.truncated_bytes == 0 and not self.torn and not self.corrupt


@dataclass(frozen=True)
class AppendResult:
    """Результат append: offset записи и текущее состояние offsets."""

    wal_offset: int
    end_offset: int
    durable: bool


class GroupCommitPolicy:
    """Ограничение bounded group commit.

    Roadmap §5.1: максимальная group-commit задержка фиксируется SLO
    и проверяется SIGKILL-тестом. Здесь задаются пределы, при достижении
    которых fsync обязателен.
    """

    def __init__(self, max_records: int = 64, max_bytes: int = 256 * 1024) -> None:
        if max_records < 1:
            raise ValueError("max_records должен быть >= 1")
        if max_bytes < 1:
            raise ValueError("max_bytes должен быть >= 1")
        self.max_records = max_records
        self.max_bytes = max_bytes

    def should_commit(self, pending_records: int, pending_bytes: int) -> bool:
        return (
            pending_records >= self.max_records
            or pending_bytes >= self.max_bytes
        )


class WalPartition:
    """Одна WAL partition: каталог сегментов с непрерывным offset-пространством.

    Offset — байтовая позиция начала фрейма в непрерывном пространстве
    partition. Сегмент с именем `00000000000000001024.wal` начинается
    с offset 1024.

    Запрещено (Roadmap §6.3): удалять `.tmp`, ACTIVE и части незакрытой
    партиции. Этот класс удаление сегментов не выполняет вовсе.
    """

    def __init__(
        self,
        directory: Path | str,
        partition_id: str,
        *,
        max_segment_bytes: int = 8 * 1024 * 1024,
        group_commit: GroupCommitPolicy | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.partition_id = partition_id
        self.max_segment_bytes = max_segment_bytes
        self.group_commit = group_commit or GroupCommitPolicy()

        self.directory.mkdir(parents=True, exist_ok=True)

        self._offsets = OffsetSet(partition_id=partition_id)
        self._pending_records = 0
        self._pending_bytes = 0
        self._active_base: int | None = None
        self._active_file = None  # type: ignore[assignment]
        self._closed = False

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def offsets(self) -> OffsetSet:
        return self._offsets

    @property
    def accepted_offset(self) -> int:
        return self._offsets.accepted

    @property
    def durable_offset(self) -> int:
        return self._offsets.durable

    @property
    def pending_records(self) -> int:
        return self._pending_records

    def segment_paths(self) -> list[Path]:
        """Сегменты в порядке возрастания base offset."""
        result: list[tuple[int, Path]] = []
        for entry in self.directory.iterdir():
            if not entry.is_file():
                continue
            base = parse_segment_name(entry.name)
            if base is None:
                continue
            result.append((base, entry))
        result.sort(key=lambda item: item[0])
        return [path for _, path in result]

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recover(self, declared_durable_offset: int = 0) -> RecoveryReport:
        """Просканировать сегменты, отбросить torn tail, восстановить offsets.

        declared_durable_offset — durable offset из внешнего checkpoint.
        Если отброшенный хвост оказался ниже него, это durable_violation.
        """
        segments = self.segment_paths()
        valid_records = 0
        last_valid_offset = 0
        truncated_bytes = 0
        torn = False
        corrupt = False
        error: str | None = None

        for path in segments:
            base = parse_segment_name(path.name)
            assert base is not None
            data = path.read_bytes()
            scan = scan_frames(data)

            valid_records += len(scan.frames)
            last_valid_offset = base + scan.last_valid_offset

            if scan.trailing_bytes:
                truncated_bytes += scan.trailing_bytes
                torn = torn or scan.torn
                corrupt = corrupt or scan.corrupt
                error = error or scan.error
                # Отбрасываем хвост физически: durable-граница не может
                # включать непроверяемые байты.
                with open(path, "r+b") as handle:
                    handle.truncate(scan.last_valid_offset)
                    handle.flush()
                    os.fsync(handle.fileno())
                fsync_dir(self.directory)
                # Сегменты после повреждённого не читаем: непрерывность
                # пространства offset уже нарушена.
                break

        self._offsets = OffsetSet(
            partition_id=self.partition_id,
            accepted=last_valid_offset,
            durable=last_valid_offset,
            closed=min(self._offsets.closed, last_valid_offset),
            published=min(self._offsets.published, last_valid_offset),
            consumers=self._offsets.consumers,
        )
        self._pending_records = 0
        self._pending_bytes = 0
        self._active_base = None
        self._active_file = None

        return RecoveryReport(
            partition_id=self.partition_id,
            scanned_segments=len(segments),
            valid_records=valid_records,
            last_valid_offset=last_valid_offset,
            truncated_bytes=truncated_bytes,
            torn=torn,
            corrupt=corrupt,
            durable_violation=last_valid_offset < declared_durable_offset,
            error=error,
        )

    # ------------------------------------------------------------------
    # Запись
    # ------------------------------------------------------------------

    def _ensure_active(self) -> None:
        if self._active_file is not None:
            return
        base = self.accepted_offset
        path = self.directory / segment_name(base)
        if path.exists():
            size = path.stat().st_size
            if base + size != self.accepted_offset:
                base = self.accepted_offset - size
                path = self.directory / segment_name(base)
        self._active_base = base
        self._active_file = open(path, "ab")
        fsync_dir(self.directory)

    def append(self, payload: bytes) -> AppendResult:
        """Добавить запись. Возвращает её wal_offset.

        accepted продвигается сразу, durable — только после commit().
        Live publish обязан использовать durable_offset как ceiling.
        """
        if self._closed:
            raise RuntimeError("partition закрыта")

        self._ensure_active()
        assert self._active_file is not None and self._active_base is not None

        record = encode_frame(payload)
        wal_offset = self.accepted_offset

        self._active_file.write(record)
        self._active_file.flush()

        self._offsets = self._offsets.advance_accepted(wal_offset + len(record))
        self._pending_records += 1
        self._pending_bytes += len(record)

        durable = False
        if self.group_commit.should_commit(self._pending_records, self._pending_bytes):
            self.commit()
            durable = True

        if self._active_size() >= self.max_segment_bytes:
            self.roll_segment()

        return AppendResult(
            wal_offset=wal_offset,
            end_offset=self.accepted_offset,
            durable=durable,
        )

    def _active_size(self) -> int:
        if self._active_file is None or self._active_base is None:
            return 0
        return self.accepted_offset - self._active_base

    def commit(self) -> int:
        """Выполнить group commit fsync и продвинуть durable offset."""
        if self._active_file is not None:
            self._active_file.flush()
            os.fsync(self._active_file.fileno())
        self._offsets = self._offsets.advance_durable(self.accepted_offset)
        self._pending_records = 0
        self._pending_bytes = 0
        return self.durable_offset

    def roll_segment(self) -> int:
        """Закрыть ACTIVE сегмент и продвинуть closedOffset.

        Roadmap §6.3: ACTIVE → CLOSED_PENDING.
        """
        self.commit()
        if self._active_file is not None:
            self._active_file.close()
            self._active_file = None
            self._active_base = None
        self._offsets = self._offsets.advance_closed(self.durable_offset)
        fsync_dir(self.directory)
        return self._offsets.closed

    def mark_published(self, offset: int) -> None:
        """Отметить диапазон как COMMITTED в Parquet (Roadmap §6.4)."""
        self._offsets = self._offsets.advance_published(offset)

    def close(self) -> None:
        if self._closed:
            return
        if self._active_file is not None:
            self.commit()
            self._active_file.close()
            self._active_file = None
            self._active_base = None
        self._closed = True

    def __enter__(self) -> "WalPartition":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    def read_range(self, start_offset: int, end_offset: int | None = None) -> list[Frame]:
        """Прочитать непрерывный упорядоченный диапазон без дублей.

        Roadmap §6.2: единый RawEventReader читает непрерывный ordered range.
        Здесь читается только WAL-часть; переключение на Parquet выполняет
        вызывающий слой по published offset.
        """
        if end_offset is None:
            end_offset = self.durable_offset
        if end_offset > self.durable_offset:
            raise ValueError(
                f"запрошен offset {end_offset} > durable {self.durable_offset}: "
                "speculative pre-fsync tail запрещён"
            )
        if start_offset > end_offset:
            return []

        result: list[Frame] = []
        for path in self.segment_paths():
            base = parse_segment_name(path.name)
            assert base is not None
            size = path.stat().st_size
            seg_start, seg_end = base, base + size
            if seg_end <= start_offset or seg_start >= end_offset:
                continue
            data = path.read_bytes()
            scan = scan_frames(data)
            for frame in scan.frames:
                absolute = base + frame.offset
                if absolute < start_offset:
                    continue
                if absolute >= end_offset:
                    break
                result.append(
                    Frame(
                        payload=frame.payload,
                        offset=absolute,
                        total_size=frame.total_size,
                    )
                )
        return result
