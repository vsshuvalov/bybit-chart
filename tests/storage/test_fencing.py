"""
Fault и property tests для WriterLease (fencing token).

Источник: ADR-013, Roadmap §6.5, §18.1

Acceptance criteria (Roadmap §18.1):
    SIGKILL старого writer → новый writer может безопасно начать
    Repeated trade seq не теряет trades
    Rollback получает новый epoch и начинает от durable offset
    Ни один old epoch не пишет после cutover
"""

import os
import signal
import time
from pathlib import Path

import pytest

from packages.storage.fencing import (
    EpochViolationError,
    LeaseAcquisitionError,
    LeaseExpiredError,
    LeaseInfo,
    WriterLease,
    read_current_lease,
)

pytestmark = pytest.mark.fault


# ------------------------------------------------------------------
# Basic acquisition / release
# ------------------------------------------------------------------

class TestWriterLeaseBasic:

    def test_acquire_returns_epoch_1_on_first_use(self, tmp_path):
        lease = WriterLease(tmp_path)
        epoch = lease.acquire()
        try:
            assert epoch == 1
        finally:
            lease.release()

    def test_epoch_monotonically_increases(self, tmp_path):
        for expected in range(1, 5):
            lease = WriterLease(tmp_path)
            epoch = lease.acquire()
            assert epoch == expected
            lease.release()

    def test_lease_is_active_after_acquire(self, tmp_path):
        lease = WriterLease(tmp_path)
        assert not lease.is_active
        lease.acquire()
        try:
            assert lease.is_active
            assert lease.epoch == 1
        finally:
            lease.release()

    def test_lease_inactive_after_release(self, tmp_path):
        lease = WriterLease(tmp_path)
        lease.acquire()
        lease.release()
        assert not lease.is_active
        assert lease.epoch is None

    def test_context_manager(self, tmp_path):
        lease = WriterLease(tmp_path)
        with lease:
            assert lease.is_active
            assert lease.epoch == 1
        assert not lease.is_active

    def test_context_manager_releases_on_exception(self, tmp_path):
        lease = WriterLease(tmp_path)
        with pytest.raises(RuntimeError):
            with lease:
                assert lease.is_active
                raise RuntimeError("simulated crash")
        assert not lease.is_active

    def test_creates_partition_dir_if_missing(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c"
        assert not deep.exists()
        lease = WriterLease(deep)
        lease.acquire()
        lease.release()
        assert deep.exists()


# ------------------------------------------------------------------
# Exclusive lock (split-brain prevention)
# ------------------------------------------------------------------

class TestWriterLeaseExclusive:

    def test_second_acquire_raises_while_first_held(self, tmp_path):
        lease1 = WriterLease(tmp_path)
        lease1.acquire()
        try:
            lease2 = WriterLease(tmp_path)
            with pytest.raises(LeaseAcquisitionError):
                lease2.acquire()
        finally:
            lease1.release()

    def test_second_acquire_succeeds_after_first_released(self, tmp_path):
        lease1 = WriterLease(tmp_path)
        lease1.acquire()
        lease1.release()

        lease2 = WriterLease(tmp_path)
        epoch = lease2.acquire()
        try:
            assert epoch == 2  # Epoch incremented
        finally:
            lease2.release()

    def test_error_message_contains_holder_info(self, tmp_path):
        lease1 = WriterLease(tmp_path)
        lease1.acquire()
        try:
            lease2 = WriterLease(tmp_path)
            with pytest.raises(LeaseAcquisitionError, match="pid="):
                lease2.acquire()
        finally:
            lease1.release()


# ------------------------------------------------------------------
# Epoch validation (cutover protection)
# ------------------------------------------------------------------

class TestEpochValidation:

    def test_assert_still_valid_passes_when_active(self, tmp_path):
        lease = WriterLease(tmp_path)
        lease.acquire()
        try:
            lease.assert_still_valid()  # должен не бросать
        finally:
            lease.release()

    def test_assert_still_valid_raises_after_release(self, tmp_path):
        lease = WriterLease(tmp_path)
        lease.acquire()
        lease.release()
        with pytest.raises(LeaseExpiredError):
            lease.assert_still_valid()

    def test_assert_still_valid_raises_on_epoch_change(self, tmp_path):
        """Simulates cutover: lease1 думает что держит lease, но epoch уже другой."""
        lease1 = WriterLease(tmp_path)
        lease1.acquire()  # epoch=1
        # НЕ release — просто запоминаем fd и epoch
        saved_fd = lease1._lock_fd

        # Форсируем: epoch_file → 2 (simulates another writer advanced it)
        (tmp_path / ".writer.epoch").write_text("2")

        # lease1 всё ещё "думает" что активен (epoch=1, fd=valid)
        with pytest.raises(EpochViolationError, match="Epoch mismatch"):
            lease1.assert_still_valid()

        # Cleanup
        lease1.release()

    def test_epoch_violation_message_contains_epochs(self, tmp_path):
        lease = WriterLease(tmp_path)
        lease.acquire()  # epoch=1
        # Форсируем epoch_file → 2
        (tmp_path / ".writer.epoch").write_text("2")

        with pytest.raises(EpochViolationError) as exc_info:
            lease.assert_still_valid()
        assert "expected=1" in str(exc_info.value)
        assert "current=2" in str(exc_info.value)

        lease.release()


# ------------------------------------------------------------------
# SIGKILL simulation (crash recovery)
# ------------------------------------------------------------------

class TestLeaseRecoveryAfterCrash:

    def test_lock_released_after_fd_close(self, tmp_path):
        """SIGKILL scenario: процесс умирает, fd закрывается, lock освобождается."""
        lease1 = WriterLease(tmp_path)
        lease1.acquire()

        # Simulate crash: закрываем fd без release()
        fd = lease1._lock_fd
        os.close(fd)
        lease1._lock_fd = None
        lease1._acquired = False
        # flock освобождён автоматически при close(fd)

        # Новый writer должен успешно захватить lease
        lease2 = WriterLease(tmp_path)
        epoch = lease2.acquire()
        try:
            assert epoch == 2
            assert lease2.is_active
        finally:
            lease2.release()

    def test_epoch_persists_after_crash(self, tmp_path):
        """Epoch в epoch_file сохраняется после краша."""
        lease1 = WriterLease(tmp_path)
        lease1.acquire()  # epoch=1

        # Simulate crash: просто закрываем fd
        os.close(lease1._lock_fd)
        lease1._lock_fd = None

        # После краша epoch_file содержит 1
        epoch_file = tmp_path / ".writer.epoch"
        assert epoch_file.exists()
        assert int(epoch_file.read_text()) == 1

        # Новый writer получает epoch=2
        lease2 = WriterLease(tmp_path)
        epoch = lease2.acquire()
        try:
            assert epoch == 2
        finally:
            lease2.release()


# ------------------------------------------------------------------
# Observability
# ------------------------------------------------------------------

class TestLeaseObservability:

    def test_read_current_lease_returns_info(self, tmp_path):
        lease = WriterLease(tmp_path)
        lease.acquire()
        try:
            info = read_current_lease(tmp_path)
            assert info is not None
            assert info.epoch == 1
            assert info.pid == os.getpid()
        finally:
            lease.release()

    def test_read_current_lease_returns_none_when_empty(self, tmp_path):
        info = read_current_lease(tmp_path)
        assert info is None

    def test_lease_info_contains_hostname(self, tmp_path):
        lease = WriterLease(tmp_path)
        lease.acquire()
        try:
            info = read_current_lease(tmp_path)
            assert info is not None
            assert len(info.hostname) > 0
        finally:
            lease.release()

    def test_lease_info_contains_timestamp(self, tmp_path):
        before = time.time()
        lease = WriterLease(tmp_path)
        lease.acquire()
        after = time.time()
        try:
            info = read_current_lease(tmp_path)
            assert info is not None
            assert before <= info.acquired_at <= after
        finally:
            lease.release()


# ------------------------------------------------------------------
# LeaseInfo serialization
# ------------------------------------------------------------------

class TestLeaseInfo:

    def test_roundtrip(self):
        info = LeaseInfo(epoch=5, pid=12345, hostname="host1", acquired_at=1234567890.0)
        restored = LeaseInfo.from_dict(info.to_dict())
        assert restored.epoch == 5
        assert restored.pid == 12345
        assert restored.hostname == "host1"
        assert restored.acquired_at == 1234567890.0
