"""
Контрактные тесты offsets и WAL-фреймов.
Источник: Roadmap §5.1, §6.2
"""

import pytest

from packages.storage import (
    ConsumerOffset,
    CorruptFrameError,
    OffsetInvariantError,
    OffsetSet,
    TornFrameError,
    decode_frame,
    encode_frame,
    frame_size,
    scan_frames,
)
from packages.storage.frames import HEADER_SIZE, MAGIC

pytestmark = pytest.mark.contract


# ===========================================================================
# OffsetSet — инварианты §6.2
# ===========================================================================

class TestOffsetInvariants:
    def test_default_is_valid(self):
        o = OffsetSet(partition_id="p0")
        assert o.accepted == o.durable == o.closed == o.published == 0

    def test_durable_cannot_exceed_accepted(self):
        with pytest.raises(OffsetInvariantError, match="durable"):
            OffsetSet(partition_id="p0", accepted=10, durable=20)

    def test_closed_cannot_exceed_durable(self):
        with pytest.raises(OffsetInvariantError, match="closed"):
            OffsetSet(partition_id="p0", accepted=30, durable=10, closed=20)

    def test_published_cannot_exceed_closed(self):
        with pytest.raises(OffsetInvariantError, match="published"):
            OffsetSet(partition_id="p0", accepted=30, durable=30, closed=10, published=20)

    def test_negative_rejected(self):
        with pytest.raises(OffsetInvariantError):
            OffsetSet(partition_id="p0", accepted=-1)

    def test_valid_chain(self):
        o = OffsetSet(partition_id="p0", accepted=100, durable=80, closed=60, published=40)
        o.validate()


class TestOffsetAdvance:
    def test_monotonic_accepted(self):
        o = OffsetSet(partition_id="p0").advance_accepted(50)
        assert o.accepted == 50
        with pytest.raises(OffsetInvariantError, match="не может убывать"):
            o.advance_accepted(40)

    def test_monotonic_durable(self):
        o = OffsetSet(partition_id="p0").advance_accepted(50).advance_durable(50)
        with pytest.raises(OffsetInvariantError, match="не может убывать"):
            o.advance_durable(10)

    def test_durable_beyond_accepted_rejected(self):
        o = OffsetSet(partition_id="p0").advance_accepted(10)
        with pytest.raises(OffsetInvariantError, match="durable"):
            o.advance_durable(20)


class TestLivePublishCeiling:
    def test_ceiling_is_durable_not_accepted(self):
        """Roadmap §5.1: speculative pre-fsync tail запрещён."""
        o = OffsetSet(partition_id="p0", accepted=100, durable=60)
        assert o.live_publish_ceiling() == 60
        assert o.live_publish_ceiling() < o.accepted


class TestConsumerOffsets:
    def test_upsert_and_read(self):
        o = OffsetSet(partition_id="p0").upsert_consumer(
            ConsumerOffset("analytics-0", 10, "1.0")
        )
        c = o.consumer("analytics-0")
        assert c is not None and c.wal_offset == 10

    def test_rollback_without_new_lease_rejected(self):
        o = OffsetSet(partition_id="p0").upsert_consumer(
            ConsumerOffset("analytics-0", 100, "1.0", lease_generation=1)
        )
        with pytest.raises(OffsetInvariantError, match="откатывает offset"):
            o.upsert_consumer(
                ConsumerOffset("analytics-0", 50, "1.0", lease_generation=1)
            )

    def test_rollback_with_new_lease_allowed(self):
        """Takeover начинает с durable checkpoint — откат допустим (§6.2)."""
        o = OffsetSet(partition_id="p0").upsert_consumer(
            ConsumerOffset("analytics-0", 100, "1.0", lease_generation=1)
        )
        o2 = o.upsert_consumer(
            ConsumerOffset("analytics-0", 50, "1.0", lease_generation=2)
        )
        c = o2.consumer("analytics-0")
        assert c is not None and c.wal_offset == 50

    def test_missing_required_consumer_counts_as_zero(self):
        o = OffsetSet(partition_id="p0", accepted=100, durable=100, closed=100, published=100)
        assert o.min_consumer_offset(frozenset({"absent"})) == 0


class TestReplaySafeOffset:
    def test_lagging_parquet_capable_consumer_does_not_block(self):
        """Отставший consumer переключается на Parquet и не держит WAL (§6.2)."""
        o = (
            OffsetSet(partition_id="p0", accepted=200, durable=200, closed=200, published=150)
            .upsert_consumer(ConsumerOffset("analytics-0", 10, "1.0"))
        )
        assert o.replay_safe_offset() == 150

    def test_wal_only_consumer_holds_wal(self):
        o = (
            OffsetSet(partition_id="p0", accepted=200, durable=200, closed=200, published=150)
            .upsert_consumer(ConsumerOffset("wal-only", 40, "1.0"))
        )
        assert o.replay_safe_offset(wal_only_consumer_ids=frozenset({"wal-only"})) == 40

    def test_unpublished_range_never_deletable(self):
        o = OffsetSet(partition_id="p0", accepted=500, durable=500, closed=500, published=0)
        assert o.replay_safe_offset() == 0

    def test_retention_bytes(self):
        o = OffsetSet(partition_id="p0", accepted=500, durable=500, closed=400, published=300)
        assert o.wal_retention_bytes() == 200


# ===========================================================================
# Frames — length + CRC §6.2
# ===========================================================================

class TestFrameRoundTrip:
    def test_round_trip(self):
        payload = b'{"eventId":"BYBIT:linear:BTCUSDT:1"}'
        frame = decode_frame(encode_frame(payload))
        assert frame.payload == payload
        assert frame.total_size == frame_size(len(payload))

    def test_empty_payload_round_trip(self):
        frame = decode_frame(encode_frame(b""))
        assert frame.payload == b""

    def test_offsets_are_contiguous(self):
        a, b = encode_frame(b"one"), encode_frame(b"two")
        scan = scan_frames(a + b)
        assert len(scan.frames) == 2
        assert scan.frames[0].end_offset == scan.frames[1].offset
        assert scan.trailing_bytes == 0

    def test_reject_non_bytes(self):
        with pytest.raises(TypeError):
            encode_frame("строка")  # type: ignore[arg-type]


class TestTornFrame:
    def test_truncated_header(self):
        data = encode_frame(b"payload")[: HEADER_SIZE - 2]
        with pytest.raises(TornFrameError):
            decode_frame(data)

    def test_truncated_payload(self):
        data = encode_frame(b"payload-long")[:-3]
        with pytest.raises(TornFrameError):
            decode_frame(data)

    def test_scan_stops_at_torn_tail(self):
        """Хвост отбрасывается до последнего валидного boundary (§6.2)."""
        good = encode_frame(b"good-record")
        torn = encode_frame(b"torn-record")[:-4]
        scan = scan_frames(good + torn)
        assert len(scan.frames) == 1
        assert scan.last_valid_offset == len(good)
        assert scan.trailing_bytes == len(torn)
        assert scan.torn is True
        assert scan.corrupt is False


class TestCorruptFrame:
    def test_bad_magic(self):
        data = bytearray(encode_frame(b"payload"))
        data[0] ^= 0xFF
        with pytest.raises(CorruptFrameError, match="magic"):
            decode_frame(bytes(data))

    def test_crc_mismatch(self):
        data = bytearray(encode_frame(b"payload"))
        data[HEADER_SIZE] ^= 0xFF  # портим payload, CRC уже не совпадёт
        with pytest.raises(CorruptFrameError, match="CRC"):
            decode_frame(bytes(data))

    def test_length_corruption_detected(self):
        """Повреждение длины не проходит валидацию."""
        import struct
        data = bytearray(encode_frame(b"payload"))
        struct.pack_into("<I", data, 8, 0xFFFFFF)  # payload_len
        with pytest.raises((CorruptFrameError, TornFrameError)):
            decode_frame(bytes(data))

    def test_scan_reports_corrupt(self):
        good = encode_frame(b"good")
        bad = bytearray(encode_frame(b"bad"))
        bad[HEADER_SIZE] ^= 0xFF
        scan = scan_frames(good + bytes(bad))
        assert len(scan.frames) == 1
        assert scan.corrupt is True
        assert scan.last_valid_offset == len(good)

    def test_magic_constant_stable(self):
        """Magic — часть формата; смена ломает совместимость."""
        assert MAGIC == 0x42574C31
