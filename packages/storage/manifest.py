"""
Manifest опубликованных сегментов и его атомарное обновление.
Источник: Roadmap §6.4, §6.5

Manifest хранит: schema, checksum, min/max event time, min/max WAL offset,
row count, connection epochs, gap references и source revision.

Партиционирование (§6.5):
    venue=bybit/category=linear/symbol={symbol}/event_type={type}/date=YYYY-MM-DD/

Manifest lease/state изменяет только maintenance через file lock + atomic
replace (Roadmap §6.1). Analytics не обновляет committed manifest напрямую.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

MANIFEST_VERSION = 1


class ManifestError(RuntimeError):
    """Ошибка манифеста."""


def partition_path(
    *,
    venue: str,
    category: str,
    symbol: str,
    event_type: str,
    date: str,
) -> Path:
    """Каноничный путь партиции (Roadmap §6.5)."""
    return Path(
        f"venue={venue.lower()}",
        f"category={category}",
        f"symbol={symbol}",
        f"event_type={event_type}",
        f"date={date}",
    )


@dataclass(frozen=True)
class ManifestEntry:
    """Одна опубликованная запись манифеста."""

    segment_id: str
    relative_path: str
    schema_version: int
    checksum: str
    row_count: int
    min_event_time_ms: int
    max_event_time_ms: int
    min_wal_offset: int
    max_wal_offset: int
    connection_epochs: tuple[str, ...] = field(default_factory=tuple)
    gap_references: tuple[str, ...] = field(default_factory=tuple)
    source_data_revision: str = "rev-0"
    byte_size: int = 0

    def __post_init__(self) -> None:
        if self.row_count < 0:
            raise ManifestError(f"{self.segment_id}: row_count < 0")
        if self.max_event_time_ms < self.min_event_time_ms:
            raise ManifestError(
                f"{self.segment_id}: max_event_time_ms < min_event_time_ms"
            )
        if self.max_wal_offset < self.min_wal_offset:
            raise ManifestError(
                f"{self.segment_id}: max_wal_offset < min_wal_offset"
            )
        if not self.checksum:
            raise ManifestError(f"{self.segment_id}: checksum обязателен")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["connection_epochs"] = list(self.connection_epochs)
        data["gap_references"] = list(self.gap_references)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ManifestEntry":
        payload = dict(data)
        payload["connection_epochs"] = tuple(payload.get("connection_epochs", ()))
        payload["gap_references"] = tuple(payload.get("gap_references", ()))
        return cls(**payload)


class Manifest:
    """Манифест партиции с атомарной заменой файла.

    Формат — JSON. Целые числа сериализуются как числа JSON внутри
    доверенного локального файла; наружу (§5.2) int64 отдаётся строками
    на уровне API, а не здесь.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._entries: dict[str, ManifestEntry] = {}
        self._version = MANIFEST_VERSION
        if self.path.exists():
            self.load()

    # ------------------------------------------------------------------
    # Чтение / запись
    # ------------------------------------------------------------------

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{self.path}: повреждённый JSON: {exc}") from exc

        version = raw.get("manifest_version")
        if version != MANIFEST_VERSION:
            raise ManifestError(
                f"{self.path}: несовместимая версия манифеста {version!r}; "
                f"ожидалась {MANIFEST_VERSION}. Требуется миграция."
            )
        self._entries = {
            item["segment_id"]: ManifestEntry.from_dict(item)
            for item in raw.get("entries", [])
        }

    def _serialize(self) -> str:
        return json.dumps(
            {
                "manifest_version": self._version,
                "entries": [e.to_dict() for e in self.sorted_entries()],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    def flush(self) -> None:
        """Атомарно заменить файл манифеста: tmp → fsync → rename → fsync(dir)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._serialize()

        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=self.path.name + ".", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
            dir_fd = os.open(str(self.path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------
    # Операции
    # ------------------------------------------------------------------

    def add(self, entry: ManifestEntry, *, flush: bool = True) -> None:
        """Добавить запись. Повторная публикация того же segment_id идемпотентна."""
        existing = self._entries.get(entry.segment_id)
        if existing is not None:
            if existing.checksum != entry.checksum:
                raise ManifestError(
                    f"{entry.segment_id}: повторная публикация с другим checksum "
                    f"({existing.checksum} != {entry.checksum})"
                )
            return
        self._entries[entry.segment_id] = entry
        if flush:
            self.flush()

    def remove(self, segment_id: str, *, flush: bool = True) -> None:
        if segment_id not in self._entries:
            raise ManifestError(f"{segment_id}: отсутствует в манифесте")
        del self._entries[segment_id]
        if flush:
            self.flush()

    def get(self, segment_id: str) -> ManifestEntry | None:
        return self._entries.get(segment_id)

    def sorted_entries(self) -> list[ManifestEntry]:
        return sorted(self._entries.values(), key=lambda e: e.min_wal_offset)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, segment_id: object) -> bool:
        return segment_id in self._entries

    # ------------------------------------------------------------------
    # Производные величины
    # ------------------------------------------------------------------

    def published_offset(self) -> int:
        """Максимальный непрерывный опубликованный offset.

        Разрыв в последовательности останавливает продвижение: пропуск
        не объявляется опубликованным (Roadmap §6.2).
        """
        offset = 0
        for entry in self.sorted_entries():
            if entry.min_wal_offset > offset:
                break
            offset = max(offset, entry.max_wal_offset)
        return offset

    def total_rows(self) -> int:
        return sum(e.row_count for e in self._entries.values())

    def gap_references(self) -> tuple[str, ...]:
        result: list[str] = []
        for entry in self.sorted_entries():
            result.extend(entry.gap_references)
        return tuple(dict.fromkeys(result))

    def covers_offset(self, offset: int) -> bool:
        return any(
            e.min_wal_offset <= offset < e.max_wal_offset for e in self._entries.values()
        )
