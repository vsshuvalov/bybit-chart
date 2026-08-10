"""
Atomic commit protocol: публикация сегмента без частично видимой истории.
Источник: Roadmap §6.4; all-modules-data-persistence-architecture-changes.md §2.3

Обязательная последовательность:
    WAL/live-tail
    → segment.tmp
    → close writer
    → validate footer/schemaVersion/rowCount/checksum
    → fsync(file)
    → atomic rename to segment.parquet
    → fsync(parent)
    → atomic manifest update
    → checkpoint advance

Открытый writer никогда не объявляется историей. Checkpoint продвигается
только после commit манифеста.

Формат файла здесь не фиксируется: writer передаётся callback-ом, поэтому
Parquet/PyArrow не является зависимостью Stage 1. Валидация footer
выполняется отдельным validator-ом того же слоя.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol

from packages.storage.manifest import Manifest, ManifestEntry


class CommitStage(str, Enum):
    """Точки, в которых может произойти crash (для fault-инъекции)."""

    BEFORE_WRITE = "BEFORE_WRITE"
    AFTER_WRITE_BEFORE_CLOSE = "AFTER_WRITE_BEFORE_CLOSE"
    AFTER_CLOSE_BEFORE_VALIDATE = "AFTER_CLOSE_BEFORE_VALIDATE"
    AFTER_VALIDATE_BEFORE_FSYNC = "AFTER_VALIDATE_BEFORE_FSYNC"
    AFTER_FSYNC_BEFORE_RENAME = "AFTER_FSYNC_BEFORE_RENAME"
    AFTER_RENAME_BEFORE_MANIFEST = "AFTER_RENAME_BEFORE_MANIFEST"
    AFTER_MANIFEST_BEFORE_CHECKPOINT = "AFTER_MANIFEST_BEFORE_CHECKPOINT"
    DONE = "DONE"


class CommitError(RuntimeError):
    """Ошибка публикации сегмента."""


class ValidationError(CommitError):
    """Файл не прошёл валидацию — публикация запрещена."""


class InjectedCrash(BaseException):
    """Инъекция аварии в тестах. BaseException — чтобы не ловилось except Exception."""


@dataclass(frozen=True)
class SegmentPayload:
    """Данные, подлежащие публикации."""

    segment_id: str
    schema_version: int
    row_count: int
    min_event_time_ms: int
    max_event_time_ms: int
    min_wal_offset: int
    max_wal_offset: int
    connection_epochs: tuple[str, ...] = ()
    gap_references: tuple[str, ...] = ()
    source_data_revision: str = "rev-0"


class SegmentWriter(Protocol):
    """Пишет содержимое сегмента в открытый файл и возвращает footer-метку."""

    def __call__(self, handle: object, payload: SegmentPayload) -> bytes: ...


@dataclass(frozen=True)
class CommitResult:
    committed_path: Path
    checksum: str
    byte_size: int
    manifest_entry: ManifestEntry
    checkpoint_offset: int


def compute_checksum(path: Path) -> str:
    """SHA-256 файла целиком. Читается потоково — без загрузки в память."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def default_validator(
    path: Path, payload: SegmentPayload, footer: bytes
) -> None:
    """Базовая валидация: непустой файл, footer, schemaVersion, rowCount.

    Реальный Parquet-валидатор footer-а подключается позже тем же контрактом.
    """
    if not path.exists():
        raise ValidationError(f"{payload.segment_id}: файл отсутствует")
    size = path.stat().st_size
    if size == 0:
        raise ValidationError(f"{payload.segment_id}: пустой файл не публикуется")
    if not footer:
        raise ValidationError(
            f"{payload.segment_id}: footer отсутствует — writer не был закрыт корректно"
        )
    if payload.row_count <= 0:
        raise ValidationError(
            f"{payload.segment_id}: rowCount={payload.row_count}; "
            "сегмент без строк не публикуется"
        )
    if payload.schema_version <= 0:
        raise ValidationError(
            f"{payload.segment_id}: некорректный schemaVersion={payload.schema_version}"
        )
    if payload.max_wal_offset <= payload.min_wal_offset:
        raise ValidationError(
            f"{payload.segment_id}: пустой WAL-диапазон "
            f"[{payload.min_wal_offset}, {payload.max_wal_offset})"
        )


def commit_segment(
    *,
    directory: Path | str,
    payload: SegmentPayload,
    writer: SegmentWriter,
    manifest: Manifest,
    file_suffix: str = ".parquet",
    validator: Callable[[Path, SegmentPayload, bytes], None] = default_validator,
    advance_checkpoint: Callable[[int], None] | None = None,
    crash_at: CommitStage | None = None,
) -> CommitResult:
    """Опубликовать сегмент по atomic commit protocol.

    crash_at инъектирует InjectedCrash в указанной точке — используется
    в crash-matrix тестах (Roadmap §19 Этап 1: crash до close, до rename,
    до manifest, до checkpoint).

    Гарантии:
    - .tmp никогда не виден как история: имя финального файла появляется
      только атомарным rename;
    - manifest обновляется только после fsync файла;
    - checkpoint продвигается только после успешного обновления manifest.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    final_path = directory / f"{payload.segment_id}{file_suffix}"
    if final_path.exists():
        existing = manifest.get(payload.segment_id)
        if existing is not None:
            return CommitResult(
                committed_path=final_path,
                checksum=existing.checksum,
                byte_size=existing.byte_size,
                manifest_entry=existing,
                checkpoint_offset=existing.max_wal_offset,
            )
        raise CommitError(
            f"{payload.segment_id}: файл существует, но отсутствует в манифесте — "
            "orphan не усыновляется автоматически"
        )

    if crash_at is CommitStage.BEFORE_WRITE:
        raise InjectedCrash(CommitStage.BEFORE_WRITE.value)

    fd, tmp_name = tempfile.mkstemp(
        dir=str(directory), prefix=f"{payload.segment_id}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)

    try:
        handle = os.fdopen(fd, "wb")
        try:
            footer = writer(handle, payload)
            if crash_at is CommitStage.AFTER_WRITE_BEFORE_CLOSE:
                raise InjectedCrash(CommitStage.AFTER_WRITE_BEFORE_CLOSE.value)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()

        if crash_at is CommitStage.AFTER_CLOSE_BEFORE_VALIDATE:
            raise InjectedCrash(CommitStage.AFTER_CLOSE_BEFORE_VALIDATE.value)

        validator(tmp_path, payload, footer)

        if crash_at is CommitStage.AFTER_VALIDATE_BEFORE_FSYNC:
            raise InjectedCrash(CommitStage.AFTER_VALIDATE_BEFORE_FSYNC.value)

        checksum = compute_checksum(tmp_path)
        byte_size = tmp_path.stat().st_size

        if crash_at is CommitStage.AFTER_FSYNC_BEFORE_RENAME:
            raise InjectedCrash(CommitStage.AFTER_FSYNC_BEFORE_RENAME.value)

        os.replace(tmp_path, final_path)
        _fsync_dir(directory)

        if crash_at is CommitStage.AFTER_RENAME_BEFORE_MANIFEST:
            raise InjectedCrash(CommitStage.AFTER_RENAME_BEFORE_MANIFEST.value)

        entry = ManifestEntry(
            segment_id=payload.segment_id,
            relative_path=final_path.name,
            schema_version=payload.schema_version,
            checksum=checksum,
            row_count=payload.row_count,
            min_event_time_ms=payload.min_event_time_ms,
            max_event_time_ms=payload.max_event_time_ms,
            min_wal_offset=payload.min_wal_offset,
            max_wal_offset=payload.max_wal_offset,
            connection_epochs=payload.connection_epochs,
            gap_references=payload.gap_references,
            source_data_revision=payload.source_data_revision,
            byte_size=byte_size,
        )
        manifest.add(entry)

        if crash_at is CommitStage.AFTER_MANIFEST_BEFORE_CHECKPOINT:
            raise InjectedCrash(CommitStage.AFTER_MANIFEST_BEFORE_CHECKPOINT.value)

        if advance_checkpoint is not None:
            advance_checkpoint(payload.max_wal_offset)

        return CommitResult(
            committed_path=final_path,
            checksum=checksum,
            byte_size=byte_size,
            manifest_entry=entry,
            checkpoint_offset=payload.max_wal_offset,
        )
    except BaseException:
        # .tmp удаляется только как собственный незавершённый артефакт
        # этой операции. ACTIVE и чужие файлы не трогаются.
        tmp_path.unlink(missing_ok=True)
        raise


def recover_orphan_tmp_files(
    directory: Path | str, *, suffix: str = ".tmp"
) -> list[Path]:
    """Найти незавершённые .tmp после аварии.

    Roadmap §6.3: `.tmp` не публикуется автоматически и не усыновляется.
    Возвращается список для отчёта/quarantine; удаление — решение
    maintenance по runbook, поэтому здесь файлы не удаляются.
    """
    directory = Path(directory)
    if not directory.exists():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.name.endswith(suffix))
