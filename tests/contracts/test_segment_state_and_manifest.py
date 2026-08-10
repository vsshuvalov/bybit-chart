"""
Контрактные тесты state machine сегментов и манифеста.
Источник: Roadmap §6.1, §6.3, §6.4, §6.5
"""

import json

import pytest

from packages.storage import (
    Manifest,
    ManifestEntry,
    ManifestError,
    QuarantineReason,
    Segment,
    SegmentState,
    SegmentTransitionError,
    LeaseError,
    partition_path,
)

pytestmark = pytest.mark.contract


def make_segment(**kwargs) -> Segment:
    defaults = dict(segment_id="seg-001", partition_id="p0", start_offset=0)
    defaults.update(kwargs)
    return Segment(**defaults)  # type: ignore[arg-type]


# ===========================================================================
# State machine §6.3
# ===========================================================================

class TestSegmentHappyPath:
    def test_full_lifecycle(self):
        seg = make_segment()
        assert seg.state is SegmentState.ACTIVE

        seg = seg.close(end_offset=1024)
        assert seg.state is SegmentState.CLOSED_PENDING
        assert seg.end_offset == 1024

        seg = seg.claim("maintenance-0", generation=1, expires_at_ms=10_000)
        assert seg.state is SegmentState.PUBLISHING
        assert seg.lease is not None and seg.lease.holder == "maintenance-0"

        seg = seg.commit("maintenance-0")
        assert seg.state is SegmentState.COMMITTED
        assert seg.lease is None


class TestForbiddenTransitions:
    def test_active_cannot_commit_directly(self):
        with pytest.raises(SegmentTransitionError):
            make_segment().commit("maintenance-0")

    def test_active_cannot_be_claimed(self):
        with pytest.raises(SegmentTransitionError):
            make_segment().claim("maintenance-0", 1, 10_000)

    def test_committed_is_terminal(self):
        seg = make_segment().close(10).claim("m0", 1, 10_000).commit("m0")
        with pytest.raises(SegmentTransitionError):
            seg.close(20)
        with pytest.raises(SegmentTransitionError):
            seg.claim("m0", 2, 20_000)

    def test_close_with_smaller_end_offset_rejected(self):
        seg = make_segment(start_offset=100)
        with pytest.raises(SegmentTransitionError):
            seg.close(end_offset=50)


class TestLease:
    def test_only_holder_may_commit(self):
        seg = make_segment().close(10).claim("maintenance-0", 1, 10_000)
        with pytest.raises(LeaseError, match="не владеет lease"):
            seg.commit("maintenance-1")

    def test_expired_lease_returns_to_closed_pending(self):
        """Roadmap §6.3: просроченный lease возвращает сегмент в CLOSED_PENDING."""
        seg = make_segment().close(10).claim("maintenance-0", 1, expires_at_ms=5_000)
        seg = seg.expire_lease(now_ms=5_000)
        assert seg.state is SegmentState.CLOSED_PENDING
        assert seg.lease is None

    def test_active_lease_cannot_be_expired(self):
        seg = make_segment().close(10).claim("maintenance-0", 1, expires_at_ms=5_000)
        with pytest.raises(LeaseError, match="ещё активен"):
            seg.expire_lease(now_ms=4_999)

    def test_takeover_requires_higher_generation(self):
        seg = make_segment().close(10).claim("m0", generation=2, expires_at_ms=5_000)
        seg = seg.expire_lease(now_ms=5_000)
        with pytest.raises(LeaseError, match="не больше"):
            seg.claim("m1", generation=2, expires_at_ms=10_000)
        seg2 = seg.claim("m1", generation=3, expires_at_ms=10_000)
        assert seg2.lease is not None and seg2.lease.generation == 3

    def test_stale_holder_cannot_reclaim_after_expiry(self):
        """Просроченный writer не пишет старым fencing token (§19 Этап 2)."""
        seg = make_segment().close(10).claim("m0", generation=1, expires_at_ms=5_000)
        seg = seg.expire_lease(now_ms=5_000)
        assert seg.lease is None
        assert seg.last_lease_generation == 1
        with pytest.raises(LeaseError):
            seg.claim("m0", generation=1, expires_at_ms=20_000)

    def test_generation_floor_survives_failed_retry(self):
        seg = make_segment().close(10).claim("m0", generation=4, expires_at_ms=5_000)
        seg = seg.fail("m0", reason="checksum mismatch").retry()
        with pytest.raises(LeaseError):
            seg.claim("m1", generation=4, expires_at_ms=10_000)
        assert seg.claim("m1", generation=5, expires_at_ms=10_000).state is SegmentState.PUBLISHING

    def test_expire_lease_only_from_publishing(self):
        seg = make_segment().close(10)
        with pytest.raises(SegmentTransitionError):
            seg.expire_lease(now_ms=10_000)


class TestFailureAndQuarantine:
    def test_fail_then_retry(self):
        seg = make_segment().close(10).claim("m0", 1, 10_000)
        seg = seg.fail("m0", reason="footer validation failed")
        assert seg.state is SegmentState.FAILED
        assert seg.retry_count == 1
        seg = seg.retry()
        assert seg.state is SegmentState.CLOSED_PENDING
        assert seg.failure_reason is None

    def test_quarantine_reasons_are_distinct(self):
        """corrupt/incomplete/legacy/schemaMismatch — разные состояния (§6.3)."""
        reasons = [
            QuarantineReason.CORRUPT,
            QuarantineReason.INCOMPLETE,
            QuarantineReason.LEGACY,
            QuarantineReason.SCHEMA_MISMATCH,
        ]
        assert len({r.value for r in reasons}) == 4
        for reason in reasons:
            seg = make_segment().close(10).quarantine(reason)
            assert seg.state is SegmentState.QUARANTINED
            assert seg.quarantine_reason is reason

    def test_quarantined_not_published_automatically(self):
        seg = make_segment().close(10).quarantine(QuarantineReason.CORRUPT)
        with pytest.raises(SegmentTransitionError):
            seg.claim("m0", 1, 10_000)


class TestDeletionRules:
    def test_only_committed_deletable(self):
        active = make_segment()
        closed = active.close(10)
        publishing = closed.claim("m0", 1, 10_000)
        committed = publishing.commit("m0")

        assert active.may_delete(retention_ok=True) is False
        assert closed.may_delete(retention_ok=True) is False
        assert publishing.may_delete(retention_ok=True) is False
        assert committed.may_delete(retention_ok=True) is True

    def test_committed_requires_retention_check(self):
        committed = make_segment().close(10).claim("m0", 1, 10_000).commit("m0")
        assert committed.may_delete(retention_ok=False) is False

    def test_orphan_never_adopted(self):
        """Roadmap §6.3: orphan не усыновляется по короткому mtime."""
        assert make_segment().is_adoptable_orphan() is False


# ===========================================================================
# Manifest §6.4, §6.5
# ===========================================================================

def make_entry(segment_id="seg-001", min_off=0, max_off=100, checksum="abc") -> ManifestEntry:
    return ManifestEntry(
        segment_id=segment_id,
        relative_path=f"{segment_id}.parquet",
        schema_version=1,
        checksum=checksum,
        row_count=10,
        min_event_time_ms=1_691_636_400_000,
        max_event_time_ms=1_691_636_460_000,
        min_wal_offset=min_off,
        max_wal_offset=max_off,
        connection_epochs=("epoch-001",),
        source_data_revision="rev-1",
        byte_size=2048,
    )


class TestManifestEntryValidation:
    def test_valid(self):
        entry = make_entry()
        assert entry.row_count == 10

    def test_checksum_required(self):
        with pytest.raises(ManifestError, match="checksum"):
            make_entry(checksum="")

    def test_negative_rows_rejected(self):
        with pytest.raises(ManifestError, match="row_count"):
            ManifestEntry(
                segment_id="s", relative_path="s.parquet", schema_version=1,
                checksum="x", row_count=-1,
                min_event_time_ms=0, max_event_time_ms=0,
                min_wal_offset=0, max_wal_offset=1,
            )

    def test_inverted_time_range_rejected(self):
        with pytest.raises(ManifestError, match="event_time"):
            ManifestEntry(
                segment_id="s", relative_path="s.parquet", schema_version=1,
                checksum="x", row_count=1,
                min_event_time_ms=100, max_event_time_ms=50,
                min_wal_offset=0, max_wal_offset=1,
            )

    def test_inverted_offset_range_rejected(self):
        with pytest.raises(ManifestError, match="wal_offset"):
            ManifestEntry(
                segment_id="s", relative_path="s.parquet", schema_version=1,
                checksum="x", row_count=1,
                min_event_time_ms=0, max_event_time_ms=0,
                min_wal_offset=100, max_wal_offset=50,
            )


class TestManifestPersistence:
    def test_add_and_reload(self, tmp_path):
        path = tmp_path / "manifest.json"
        m = Manifest(path)
        m.add(make_entry())
        assert len(m) == 1

        reloaded = Manifest(path)
        assert len(reloaded) == 1
        entry = reloaded.get("seg-001")
        assert entry is not None
        assert entry.checksum == "abc"
        assert entry.connection_epochs == ("epoch-001",)

    def test_atomic_write_leaves_no_tmp(self, tmp_path):
        path = tmp_path / "manifest.json"
        m = Manifest(path)
        m.add(make_entry())
        leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []

    def test_incompatible_version_rejected(self, tmp_path):
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps({"manifest_version": 999, "entries": []}))
        with pytest.raises(ManifestError, match="несовместимая версия"):
            Manifest(path)

    def test_corrupt_json_rejected(self, tmp_path):
        path = tmp_path / "manifest.json"
        path.write_text("{ not json")
        with pytest.raises(ManifestError, match="повреждённый JSON"):
            Manifest(path)


class TestManifestIdempotency:
    def test_same_segment_same_checksum_is_noop(self, tmp_path):
        m = Manifest(tmp_path / "manifest.json")
        m.add(make_entry())
        m.add(make_entry())
        assert len(m) == 1

    def test_same_segment_different_checksum_rejected(self, tmp_path):
        m = Manifest(tmp_path / "manifest.json")
        m.add(make_entry(checksum="aaa"))
        with pytest.raises(ManifestError, match="другим checksum"):
            m.add(make_entry(checksum="bbb"))


class TestManifestPublishedOffset:
    def test_contiguous_range(self, tmp_path):
        m = Manifest(tmp_path / "manifest.json")
        m.add(make_entry("seg-001", 0, 100), flush=False)
        m.add(make_entry("seg-002", 100, 250), flush=False)
        assert m.published_offset() == 250

    def test_gap_stops_progress(self, tmp_path):
        """Пропуск не объявляется опубликованным (§6.2)."""
        m = Manifest(tmp_path / "manifest.json")
        m.add(make_entry("seg-001", 0, 100), flush=False)
        m.add(make_entry("seg-003", 500, 700), flush=False)
        assert m.published_offset() == 100

    def test_covers_offset(self, tmp_path):
        m = Manifest(tmp_path / "manifest.json")
        m.add(make_entry("seg-001", 0, 100), flush=False)
        assert m.covers_offset(50) is True
        assert m.covers_offset(150) is False

    def test_total_rows(self, tmp_path):
        m = Manifest(tmp_path / "manifest.json")
        m.add(make_entry("seg-001", 0, 100), flush=False)
        m.add(make_entry("seg-002", 100, 200), flush=False)
        assert m.total_rows() == 20


class TestPartitionPath:
    def test_canonical_layout(self):
        """Roadmap §6.5."""
        p = partition_path(
            venue="BYBIT", category="linear", symbol="BTCUSDT",
            event_type="RAW_TRADE", date="2026-08-10",
        )
        assert p.as_posix() == (
            "venue=bybit/category=linear/symbol=BTCUSDT/"
            "event_type=RAW_TRADE/date=2026-08-10"
        )
