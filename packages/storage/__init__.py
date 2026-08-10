"""
packages/storage — WAL, offsets, state machine сегментов, atomic commit, manifest.
Источник: Roadmap §6.1–6.5

Границы (Roadmap §3.3, §23):
- collector пишет WAL и закрывает сегменты; тяжёлый scan ему запрещён;
- maintenance публикует и компактит закрытые сегменты по lease;
- api-gateway не читает ACTIVE-файл другого процесса.
"""

from packages.storage.atomic_commit import (
    CommitError,
    CommitResult,
    CommitStage,
    InjectedCrash,
    SegmentPayload,
    ValidationError,
    commit_segment,
    compute_checksum,
    default_validator,
    recover_orphan_tmp_files,
)
from packages.storage.parquet_writer import (
    BTCUSDT_SCHEMA,
    SCHEMA_VERSION_MAJOR,
    SCHEMA_VERSION_MINOR,
    ParquetWriter,
    validate_parquet_footer,
)
from packages.storage.frames import (
    CorruptFrameError,
    Frame,
    FrameError,
    HEADER_SIZE,
    ScanResult,
    TornFrameError,
    decode_frame,
    encode_frame,
    frame_size,
    scan_frames,
)
from packages.storage.manifest import (
    Manifest,
    ManifestEntry,
    ManifestError,
    partition_path,
)
from packages.storage.offsets import (
    ConsumerOffset,
    OffsetInvariantError,
    OffsetSet,
)
from packages.storage.segment_state import (
    Lease,
    LeaseError,
    QuarantineReason,
    Segment,
    SegmentState,
    SegmentTransitionError,
)
from packages.storage.wal import (
    AppendResult,
    GroupCommitPolicy,
    RecoveryReport,
    WalPartition,
    parse_segment_name,
    segment_name,
)

__all__ = [
    # frames
    "Frame",
    "FrameError",
    "TornFrameError",
    "CorruptFrameError",
    "ScanResult",
    "HEADER_SIZE",
    "encode_frame",
    "decode_frame",
    "scan_frames",
    "frame_size",
    # offsets
    "OffsetSet",
    "ConsumerOffset",
    "OffsetInvariantError",
    # wal
    "WalPartition",
    "GroupCommitPolicy",
    "AppendResult",
    "RecoveryReport",
    "segment_name",
    "parse_segment_name",
    # segment state
    "Segment",
    "SegmentState",
    "QuarantineReason",
    "Lease",
    "SegmentTransitionError",
    "LeaseError",
    # manifest
    "Manifest",
    "ManifestEntry",
    "ManifestError",
    "partition_path",
    # atomic commit
    "commit_segment",
    "CommitStage",
    "CommitResult",
    "CommitError",
    "ValidationError",
    "InjectedCrash",
    "SegmentPayload",
    "compute_checksum",
    "default_validator",
    "recover_orphan_tmp_files",
    # parquet writer
    "ParquetWriter",
    "BTCUSDT_SCHEMA",
    "SCHEMA_VERSION_MAJOR",
    "SCHEMA_VERSION_MINOR",
    "validate_parquet_footer",
]
