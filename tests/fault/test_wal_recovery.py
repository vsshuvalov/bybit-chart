"""
WAL: group commit, torn-frame recovery, live-tail ceiling.
Источник: Roadmap §5.1, §6.2, §19 Этап 1

Проверяется:
    - torn/CRC frame отбрасывается до последнего валидного boundary;
    - partial group commit не теряет уже durable записи;
    - live publish не обгоняет durableOffset;
    - premature WAL truncation запрещена;
    - duplicate replay не удваивает записи.
"""

import os

import pytest

from packages.storage import (
    GroupCommitPolicy,
    WalPartition,
    encode_frame,
    segment_name,
)
from packages.storage.frames import HEADER_SIZE

pytestmark = pytest.mark.fault


def open_wal(tmp_path, **kwargs) -> WalPartition:
    return WalPartition(tmp_path / "wal" / "p0", partition_id="p0", **kwargs)


class TestAppendAndCommit:
    def test_append_returns_monotonic_offsets(self, tmp_path):
        with open_wal(tmp_path) as wal:
            r1 = wal.append(b"event-1")
            r2 = wal.append(b"event-2")
            assert r1.wal_offset == 0
            assert r2.wal_offset == r1.end_offset
            assert wal.accepted_offset == r2.end_offset

    def test_durable_lags_accepted_until_commit(self, tmp_path):
        """Roadmap §5.1: durable продвигается только после fsync."""
        with open_wal(tmp_path, group_commit=GroupCommitPolicy(max_records=1000)) as wal:
            wal.append(b"event-1")
            assert wal.accepted_offset > 0
            assert wal.durable_offset == 0
            wal.commit()
            assert wal.durable_offset == wal.accepted_offset

    def test_group_commit_triggers_on_record_limit(self, tmp_path):
        with open_wal(tmp_path, group_commit=GroupCommitPolicy(max_records=3)) as wal:
            wal.append(b"a")
            wal.append(b"b")
            assert wal.durable_offset == 0
            result = wal.append(b"c")
            assert result.durable is True
            assert wal.durable_offset == wal.accepted_offset
            assert wal.pending_records == 0

    def test_group_commit_triggers_on_byte_limit(self, tmp_path):
        policy = GroupCommitPolicy(max_records=1000, max_bytes=HEADER_SIZE + 4)
        with open_wal(tmp_path, group_commit=policy) as wal:
            result = wal.append(b"data")
            assert result.durable is True


class TestLiveTailCeiling:
    def test_read_beyond_durable_rejected(self, tmp_path):
        """Speculative pre-fsync tail запрещён (§5.1)."""
        with open_wal(tmp_path, group_commit=GroupCommitPolicy(max_records=1000)) as wal:
            wal.append(b"event-1")
            with pytest.raises(ValueError, match="speculative pre-fsync tail"):
                wal.read_range(0, wal.accepted_offset)

    def test_read_up_to_durable_allowed(self, tmp_path):
        with open_wal(tmp_path) as wal:
            wal.append(b"event-1")
            wal.append(b"event-2")
            wal.commit()
            frames = wal.read_range(0)
            assert [f.payload for f in frames] == [b"event-1", b"event-2"]

    def test_offsets_absolute_in_read(self, tmp_path):
        with open_wal(tmp_path) as wal:
            r1 = wal.append(b"first")
            r2 = wal.append(b"second")
            wal.commit()
            frames = wal.read_range(0)
            assert frames[0].offset == r1.wal_offset
            assert frames[1].offset == r2.wal_offset

    def test_partial_range_read(self, tmp_path):
        with open_wal(tmp_path) as wal:
            wal.append(b"a")
            r2 = wal.append(b"b")
            wal.append(b"c")
            wal.commit()
            frames = wal.read_range(r2.wal_offset)
            assert [f.payload for f in frames] == [b"b", b"c"]


class TestTornFrameRecovery:
    def test_torn_tail_truncated(self, tmp_path):
        """Оборванный хвост отбрасывается до последнего валидного boundary."""
        wal = open_wal(tmp_path)
        wal.append(b"good-1")
        wal.append(b"good-2")
        durable = wal.commit()
        wal.close()

        # Имитируем обрыв питания посреди третьей записи
        segment = (tmp_path / "wal" / "p0" / segment_name(0))
        with open(segment, "ab") as handle:
            handle.write(encode_frame(b"torn-record")[:-5])

        wal2 = open_wal(tmp_path)
        report = wal2.recover(declared_durable_offset=durable)

        assert report.torn is True
        assert report.truncated_bytes > 0
        assert report.valid_records == 2
        assert report.last_valid_offset == durable
        assert report.durable_violation is False
        assert segment.stat().st_size == durable

        frames = wal2.read_range(0)
        assert [f.payload for f in frames] == [b"good-1", b"good-2"]
        wal2.close()

    def test_crc_corruption_truncated(self, tmp_path):
        wal = open_wal(tmp_path)
        wal.append(b"good-1")
        first_end = wal.commit()
        wal.append(b"will-corrupt")
        wal.commit()
        wal.close()

        segment = tmp_path / "wal" / "p0" / segment_name(0)
        data = bytearray(segment.read_bytes())
        data[first_end + HEADER_SIZE] ^= 0xFF  # портим payload второй записи
        segment.write_bytes(bytes(data))

        wal2 = open_wal(tmp_path)
        report = wal2.recover(declared_durable_offset=first_end)
        assert report.corrupt is True
        assert report.valid_records == 1
        assert report.last_valid_offset == first_end
        wal2.close()

    def test_durable_violation_reported_as_incident(self, tmp_path):
        """Если отброшен участок ниже объявленного durable — это incident (§6.2)."""
        wal = open_wal(tmp_path)
        wal.append(b"record-1")
        wal.append(b"record-2")
        durable = wal.commit()
        wal.close()

        # Диск потерял часть уже подтверждённых данных
        segment = tmp_path / "wal" / "p0" / segment_name(0)
        with open(segment, "r+b") as handle:
            handle.truncate(durable - 3)

        wal2 = open_wal(tmp_path)
        report = wal2.recover(declared_durable_offset=durable)
        assert report.durable_violation is True
        assert report.clean is False
        wal2.close()

    def test_clean_recovery_reports_no_truncation(self, tmp_path):
        wal = open_wal(tmp_path)
        wal.append(b"record-1")
        durable = wal.commit()
        wal.close()

        wal2 = open_wal(tmp_path)
        report = wal2.recover(declared_durable_offset=durable)
        assert report.clean is True
        assert report.truncated_bytes == 0
        assert report.last_valid_offset == durable
        wal2.close()

    def test_append_continues_after_recovery(self, tmp_path):
        """После recovery запись продолжается без дублей и без разрыва offset."""
        wal = open_wal(tmp_path)
        wal.append(b"before-crash")
        durable = wal.commit()
        wal.close()

        segment = tmp_path / "wal" / "p0" / segment_name(0)
        with open(segment, "ab") as handle:
            handle.write(encode_frame(b"torn")[:-4])

        wal2 = open_wal(tmp_path)
        wal2.recover(declared_durable_offset=durable)
        result = wal2.append(b"after-recovery")
        wal2.commit()

        assert result.wal_offset == durable
        frames = wal2.read_range(0)
        assert [f.payload for f in frames] == [b"before-crash", b"after-recovery"]
        wal2.close()


class TestSegmentRolling:
    def test_roll_advances_closed_offset(self, tmp_path):
        with open_wal(tmp_path) as wal:
            wal.append(b"record")
            closed = wal.roll_segment()
            assert closed == wal.durable_offset
            assert wal.offsets.closed == closed

    def test_new_segment_after_roll(self, tmp_path):
        with open_wal(tmp_path) as wal:
            wal.append(b"first")
            closed = wal.roll_segment()
            wal.append(b"second")
            wal.commit()
            names = [p.name for p in wal.segment_paths()]
            assert segment_name(0) in names
            assert segment_name(closed) in names

    def test_read_across_segments(self, tmp_path):
        with open_wal(tmp_path) as wal:
            wal.append(b"seg1-a")
            wal.roll_segment()
            wal.append(b"seg2-a")
            wal.commit()
            frames = wal.read_range(0)
            assert [f.payload for f in frames] == [b"seg1-a", b"seg2-a"]

    def test_size_based_roll(self, tmp_path):
        wal = WalPartition(
            tmp_path / "wal" / "p0", partition_id="p0",
            max_segment_bytes=HEADER_SIZE + 8,
            group_commit=GroupCommitPolicy(max_records=1),
        )
        wal.append(b"12345678")
        wal.append(b"abcdefgh")
        wal.commit()
        assert len(wal.segment_paths()) >= 2
        frames = wal.read_range(0)
        assert [f.payload for f in frames] == [b"12345678", b"abcdefgh"]
        wal.close()


class TestPublishedOffset:
    def test_mark_published_requires_closed(self, tmp_path):
        with open_wal(tmp_path) as wal:
            wal.append(b"record")
            wal.commit()
            with pytest.raises(Exception):
                # published не может превышать closed
                wal.mark_published(wal.durable_offset)

    def test_mark_published_after_roll(self, tmp_path):
        with open_wal(tmp_path) as wal:
            wal.append(b"record")
            closed = wal.roll_segment()
            wal.mark_published(closed)
            assert wal.offsets.published == closed
            assert wal.offsets.replay_safe_offset() == closed


class TestNoDuplicateReplay:
    def test_repeated_read_is_identical(self, tmp_path):
        """Duplicate replay не удваивает записи (§19 Этап 1)."""
        with open_wal(tmp_path) as wal:
            wal.append(b"e1")
            wal.append(b"e2")
            wal.commit()
            first = [f.payload for f in wal.read_range(0)]
            second = [f.payload for f in wal.read_range(0)]
            assert first == second == [b"e1", b"e2"]

    def test_reopen_reads_same_records(self, tmp_path):
        wal = open_wal(tmp_path)
        wal.append(b"e1")
        wal.append(b"e2")
        durable = wal.commit()
        wal.close()

        wal2 = open_wal(tmp_path)
        wal2.recover(declared_durable_offset=durable)
        assert [f.payload for f in wal2.read_range(0)] == [b"e1", b"e2"]
        wal2.close()
