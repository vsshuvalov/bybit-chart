"""
Crash-matrix atomic commit protocol.
Источник: Roadmap §6.4, §19 Этап 1; all-modules-changes §7.1

Обязательные точки аварии:
    crash до close
    crash после close до rename
    crash после rename до manifest
    crash после manifest до checkpoint

Проверяется:
    - незавершённый файл не публикуется как история;
    - committed segment читается;
    - manifest/checkpoint согласованы;
    - recovery не создаёт дублей.
"""

import pytest

from packages.storage import (
    CommitStage,
    InjectedCrash,
    Manifest,
    SegmentPayload,
    ValidationError,
    commit_segment,
    compute_checksum,
    recover_orphan_tmp_files,
)

pytestmark = pytest.mark.fault


CONTENT = b"row-data-" * 32
FOOTER = b"FOOTER-v1"


def writer(handle, payload: SegmentPayload) -> bytes:
    handle.write(CONTENT)
    handle.write(FOOTER)
    return FOOTER


def make_payload(segment_id="seg-001", min_off=0, max_off=1024) -> SegmentPayload:
    return SegmentPayload(
        segment_id=segment_id,
        schema_version=1,
        row_count=32,
        min_event_time_ms=1_691_636_400_000,
        max_event_time_ms=1_691_636_460_000,
        min_wal_offset=min_off,
        max_wal_offset=max_off,
        connection_epochs=("epoch-001",),
    )


class TestHappyPath:
    def test_commit_succeeds(self, tmp_path):
        manifest = Manifest(tmp_path / "manifest.json")
        checkpoints: list[int] = []

        result = commit_segment(
            directory=tmp_path / "data",
            payload=make_payload(),
            writer=writer,
            manifest=manifest,
            advance_checkpoint=checkpoints.append,
        )

        assert result.committed_path.exists()
        assert result.committed_path.name == "seg-001.parquet"
        assert result.checksum == compute_checksum(result.committed_path)
        assert checkpoints == [1024]
        assert len(manifest) == 1
        assert manifest.published_offset() == 1024

    def test_no_tmp_left_behind(self, tmp_path):
        manifest = Manifest(tmp_path / "manifest.json")
        commit_segment(
            directory=tmp_path / "data",
            payload=make_payload(),
            writer=writer,
            manifest=manifest,
        )
        assert recover_orphan_tmp_files(tmp_path / "data") == []


class TestCrashMatrix:
    """Каждая точка аварии: история не публикуется, checkpoint не продвигается."""

    @pytest.mark.parametrize(
        "stage",
        [
            CommitStage.BEFORE_WRITE,
            CommitStage.AFTER_WRITE_BEFORE_CLOSE,
            CommitStage.AFTER_CLOSE_BEFORE_VALIDATE,
            CommitStage.AFTER_VALIDATE_BEFORE_FSYNC,
            CommitStage.AFTER_FSYNC_BEFORE_RENAME,
        ],
    )
    def test_crash_before_rename_publishes_nothing(self, tmp_path, stage):
        data_dir = tmp_path / "data"
        manifest = Manifest(tmp_path / "manifest.json")
        checkpoints: list[int] = []

        with pytest.raises(InjectedCrash):
            commit_segment(
                directory=data_dir,
                payload=make_payload(),
                writer=writer,
                manifest=manifest,
                advance_checkpoint=checkpoints.append,
                crash_at=stage,
            )

        assert not (data_dir / "seg-001.parquet").exists()
        assert len(manifest) == 0
        assert manifest.published_offset() == 0
        assert checkpoints == []
        # .tmp собственной операции убран, ACTIVE-файлы не тронуты
        assert recover_orphan_tmp_files(data_dir) == []

    def test_crash_after_rename_before_manifest(self, tmp_path):
        """Файл на диске есть, но историей не считается: манифест пуст."""
        data_dir = tmp_path / "data"
        manifest_path = tmp_path / "manifest.json"
        manifest = Manifest(manifest_path)
        checkpoints: list[int] = []

        with pytest.raises(InjectedCrash):
            commit_segment(
                directory=data_dir,
                payload=make_payload(),
                writer=writer,
                manifest=manifest,
                advance_checkpoint=checkpoints.append,
                crash_at=CommitStage.AFTER_RENAME_BEFORE_MANIFEST,
            )

        assert (data_dir / "seg-001.parquet").exists()
        assert len(Manifest(manifest_path)) == 0
        assert Manifest(manifest_path).published_offset() == 0
        assert checkpoints == []

    def test_orphan_after_rename_is_not_adopted(self, tmp_path):
        """Повторный commit не усыновляет файл без записи в манифесте."""
        data_dir = tmp_path / "data"
        manifest = Manifest(tmp_path / "manifest.json")

        with pytest.raises(InjectedCrash):
            commit_segment(
                directory=data_dir, payload=make_payload(), writer=writer,
                manifest=manifest, crash_at=CommitStage.AFTER_RENAME_BEFORE_MANIFEST,
            )

        with pytest.raises(Exception, match="orphan не усыновляется"):
            commit_segment(
                directory=data_dir, payload=make_payload(), writer=writer,
                manifest=manifest,
            )

    def test_crash_after_manifest_before_checkpoint(self, tmp_path):
        """Манифест записан, checkpoint нет: повтор идемпотентен."""
        data_dir = tmp_path / "data"
        manifest_path = tmp_path / "manifest.json"
        manifest = Manifest(manifest_path)
        checkpoints: list[int] = []

        with pytest.raises(InjectedCrash):
            commit_segment(
                directory=data_dir,
                payload=make_payload(),
                writer=writer,
                manifest=manifest,
                advance_checkpoint=checkpoints.append,
                crash_at=CommitStage.AFTER_MANIFEST_BEFORE_CHECKPOINT,
            )

        reloaded = Manifest(manifest_path)
        assert len(reloaded) == 1
        assert reloaded.published_offset() == 1024
        assert checkpoints == []

        # Повторный запуск после restart: дубля нет, checkpoint догоняет
        result = commit_segment(
            directory=data_dir,
            payload=make_payload(),
            writer=writer,
            manifest=reloaded,
            advance_checkpoint=checkpoints.append,
        )
        assert len(reloaded) == 1
        assert result.checkpoint_offset == 1024


class TestValidation:
    def test_empty_segment_not_published(self, tmp_path):
        manifest = Manifest(tmp_path / "manifest.json")

        def empty_writer(handle, payload):
            return FOOTER

        with pytest.raises(ValidationError, match="пустой файл"):
            commit_segment(
                directory=tmp_path / "data",
                payload=make_payload(),
                writer=empty_writer,
                manifest=manifest,
            )
        assert len(manifest) == 0

    def test_missing_footer_not_published(self, tmp_path):
        manifest = Manifest(tmp_path / "manifest.json")

        def no_footer_writer(handle, payload):
            handle.write(CONTENT)
            return b""

        with pytest.raises(ValidationError, match="footer"):
            commit_segment(
                directory=tmp_path / "data",
                payload=make_payload(),
                writer=no_footer_writer,
                manifest=manifest,
            )
        assert len(manifest) == 0

    def test_zero_rows_not_published(self, tmp_path):
        manifest = Manifest(tmp_path / "manifest.json")
        payload = SegmentPayload(
            segment_id="seg-empty", schema_version=1, row_count=0,
            min_event_time_ms=0, max_event_time_ms=0,
            min_wal_offset=0, max_wal_offset=10,
        )
        with pytest.raises(ValidationError, match="rowCount"):
            commit_segment(
                directory=tmp_path / "data", payload=payload,
                writer=writer, manifest=manifest,
            )

    def test_empty_wal_range_not_published(self, tmp_path):
        manifest = Manifest(tmp_path / "manifest.json")
        payload = make_payload(min_off=500, max_off=500)
        with pytest.raises(ValidationError, match="WAL-диапазон"):
            commit_segment(
                directory=tmp_path / "data", payload=payload,
                writer=writer, manifest=manifest,
            )


class TestSequentialCommits:
    def test_two_segments_advance_published_offset(self, tmp_path):
        manifest = Manifest(tmp_path / "manifest.json")
        checkpoints: list[int] = []

        commit_segment(
            directory=tmp_path / "data", payload=make_payload("seg-001", 0, 1024),
            writer=writer, manifest=manifest, advance_checkpoint=checkpoints.append,
        )
        commit_segment(
            directory=tmp_path / "data", payload=make_payload("seg-002", 1024, 2048),
            writer=writer, manifest=manifest, advance_checkpoint=checkpoints.append,
        )

        assert checkpoints == [1024, 2048]
        assert manifest.published_offset() == 2048
        assert len(manifest) == 2

    def test_gap_between_segments_blocks_published_offset(self, tmp_path):
        manifest = Manifest(tmp_path / "manifest.json")
        commit_segment(
            directory=tmp_path / "data", payload=make_payload("seg-001", 0, 1024),
            writer=writer, manifest=manifest,
        )
        commit_segment(
            directory=tmp_path / "data", payload=make_payload("seg-003", 5000, 6000),
            writer=writer, manifest=manifest,
        )
        assert manifest.published_offset() == 1024
