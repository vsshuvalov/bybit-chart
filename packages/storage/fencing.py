"""
Writer Lease и Fencing Token для Multi-Process Safety.

Источник: ADR-013, Roadmap §6.5, §18.1 (Этап 2)

Реализация: file lock (fcntl.flock) + epoch файл.
Без внешних зависимостей — работает на ext4/XFS/APFS (single-host).

Инварианты:
    - только один writer держит lease в любой момент времени
    - old epoch не может писать после cutover (epoch validation)
    - crash/SIGKILL автоматически освобождает lock (kernel)
    - epoch монотонно возрастает

Приёмка (Roadmap §18.1):
    SIGKILL старого writer → новый writer может безопасно начать
    Rollback начинает с durable offset нового epoch
    Ни один old epoch не пишет после cutover
"""

from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

LEASE_FILE_NAME = ".writer.lease"
EPOCH_FILE_NAME = ".writer.epoch"


class LeaseAcquisitionError(Exception):
    """Не удалось получить writer lease (другой writer активен)."""


class LeaseExpiredError(Exception):
    """Текущий lease истёк или был отозван."""


class EpochViolationError(Exception):
    """Попытка писать с устаревшим epoch (split-brain protection)."""


@dataclass
class LeaseInfo:
    """Информация о текущем holder lease."""
    epoch: int
    pid: int
    hostname: str
    acquired_at: float  # Unix timestamp

    def to_dict(self) -> dict:
        return {
            "epoch": self.epoch,
            "pid": self.pid,
            "hostname": self.hostname,
            "acquired_at": self.acquired_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LeaseInfo":
        return cls(
            epoch=d["epoch"],
            pid=d["pid"],
            hostname=d["hostname"],
            acquired_at=d["acquired_at"],
        )


class WriterLease:
    """Writer lease с fencing token на базе fcntl.flock.

    Гарантирует, что только один процесс является writer-ом
    в любой момент времени. При crash/SIGKILL kernel автоматически
    освобождает flock.

    Usage:
        lease = WriterLease(partition_dir)
        with lease:
            # только этот процесс является writer-ом
            wal.append(event)
            lease.assert_still_valid()  # проверка в долгих операциях

    Или явно:
        lease = WriterLease(partition_dir)
        lease.acquire()
        try:
            wal.append(event)
            lease.assert_still_valid()
        finally:
            lease.release()
    """

    def __init__(self, partition_dir: Path):
        """Инициализировать lease для раздела.

        Args:
            partition_dir: директория раздела (WAL partition)
        """
        self.partition_dir = Path(partition_dir)
        self.lease_file = self.partition_dir / LEASE_FILE_NAME
        self.epoch_file = self.partition_dir / EPOCH_FILE_NAME

        self._lock_fd: int | None = None
        self._epoch: int | None = None
        self._acquired = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self) -> int:
        """Захватить writer lease.

        Читает последний epoch из epoch_file, инкрементирует его,
        захватывает flock и записывает новый epoch + PID.

        Returns:
            Новый epoch (монотонно возрастающий)

        Raises:
            LeaseAcquisitionError: если другой writer держит lock
        """
        self.partition_dir.mkdir(parents=True, exist_ok=True)

        # Открыть/создать lease file
        fd = os.open(
            str(self.lease_file),
            os.O_RDWR | os.O_CREAT,
            0o600,
        )

        try:
            # Non-blocking exclusive lock
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                current = self._read_lease_info()
                raise LeaseAcquisitionError(
                    f"Writer lease held by pid={current.pid if current else '?'}, "
                    f"epoch={current.epoch if current else '?'}"
                ) from exc
            raise

        # Lock acquired — читаем и инкрементируем epoch
        new_epoch = self._next_epoch()
        hostname = _get_hostname()

        info = LeaseInfo(
            epoch=new_epoch,
            pid=os.getpid(),
            hostname=hostname,
            acquired_at=time.time(),
        )

        # Записываем lease info в lease file (для observability)
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        data = json.dumps(info.to_dict()).encode()
        os.write(fd, data)
        os.fsync(fd)

        # Записываем epoch в отдельный epoch file (для durability)
        self._write_epoch(new_epoch)

        self._lock_fd = fd
        self._epoch = new_epoch
        self._acquired = True

        logger.info(
            "Writer lease acquired: epoch=%d pid=%d partition=%s",
            new_epoch, os.getpid(), self.partition_dir,
        )
        return new_epoch

    def release(self) -> None:
        """Освободить writer lease."""
        if not self._acquired:
            return

        self._acquired = False
        epoch = self._epoch
        self._epoch = None

        if self._lock_fd is not None:
            try:
                # Очистить lease file перед release
                os.lseek(self._lock_fd, 0, os.SEEK_SET)
                os.ftruncate(self._lock_fd, 0)
                os.fsync(self._lock_fd)
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = None

        logger.info(
            "Writer lease released: epoch=%d pid=%d partition=%s",
            epoch, os.getpid(), self.partition_dir,
        )

    def assert_still_valid(self) -> None:
        """Проверить, что lease всё ещё валиден.

        Вызывать в длинных операциях (flush, compaction) для
        защиты от silent lease loss.

        Raises:
            LeaseExpiredError: если lease больше не активен
            EpochViolationError: если epoch изменился (cutover произошёл)
        """
        if not self._acquired or self._lock_fd is None:
            raise LeaseExpiredError("Writer lease not active")

        # Проверить epoch (cutover detection)
        current_epoch = self._read_epoch()
        if current_epoch != self._epoch:
            raise EpochViolationError(
                f"Epoch mismatch: expected={self._epoch}, current={current_epoch}. "
                "Another writer performed cutover."
            )

    @property
    def epoch(self) -> int | None:
        """Текущий epoch или None если lease не активен."""
        return self._epoch if self._acquired else None

    @property
    def is_active(self) -> bool:
        """True если lease захвачен и активен."""
        return self._acquired and self._lock_fd is not None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "WriterLease":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_epoch(self) -> int:
        """Прочитать последний epoch и вернуть epoch + 1."""
        last = self._read_epoch()
        return last + 1

    def _read_epoch(self) -> int:
        """Прочитать последний epoch из epoch_file."""
        if not self.epoch_file.exists():
            return 0
        try:
            return int(self.epoch_file.read_text().strip())
        except (ValueError, OSError):
            return 0

    def _write_epoch(self, epoch: int) -> None:
        """Атомарно записать новый epoch в epoch_file."""
        tmp = self.epoch_file.with_suffix(".tmp")
        tmp.write_text(str(epoch))
        tmp.rename(self.epoch_file)
        # fsync directory для durability
        _fsync_dir(self.partition_dir)

    def _read_lease_info(self) -> LeaseInfo | None:
        """Прочитать lease info для observability (non-locking)."""
        if not self.lease_file.exists():
            return None
        try:
            data = self.lease_file.read_text()
            if not data.strip():
                return None
            return LeaseInfo.from_dict(json.loads(data))
        except (json.JSONDecodeError, KeyError, OSError):
            return None


def read_current_lease(partition_dir: Path) -> LeaseInfo | None:
    """Прочитать текущий lease без захвата lock (для observability).

    Используется для мониторинга и debugging.

    Args:
        partition_dir: директория раздела

    Returns:
        LeaseInfo или None если нет активного writer
    """
    lease = WriterLease(partition_dir)
    return lease._read_lease_info()


def _get_hostname() -> str:
    """Получить hostname текущего хоста."""
    import socket
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def _fsync_dir(path: Path) -> None:
    """fsync директории для durability atomic rename."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
