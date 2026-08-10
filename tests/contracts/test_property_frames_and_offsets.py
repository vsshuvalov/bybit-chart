"""
Property-based тесты формата фрейма и инвариантов offsets.
Источник: Roadmap §4 («Backend tests | pytest + Hypothesis»), §6.2.

Example-based тесты фиксируют выбранные случаи. Здесь проверяются
утверждения, обязанные держаться на любом входе: round-trip фрейма,
отсутствие валидных данных за boundary при обрезке и сохранение
инвариантов offsets при произвольной последовательности продвижений.

Задача P1-S1-005.
"""

from __future__ import annotations

import struct
import zlib

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from packages.storage.frames import (
    FRAME_VERSION,
    HEADER_SIZE,
    MAGIC,
    MAX_PAYLOAD_BYTES,
    CorruptFrameError,
    FrameError,
    TornFrameError,
    decode_frame,
    encode_frame,
    frame_size,
    scan_frames,
)
from packages.storage.offsets import (
    ConsumerOffset,
    OffsetInvariantError,
    OffsetSet,
)

pytestmark = [pytest.mark.contract, pytest.mark.property]

# Границы подобраны так, чтобы примеры оставались быстрыми: формат фрейма
# не зависит от размера payload. Сам лимит MAX_PAYLOAD_BYTES проверяется
# отдельно в TestPayloadLimit ниже — генерировать payload такого размера
# в каждом примере бессмысленно дорого.
payloads = st.binary(min_size=0, max_size=1024)
payload_lists = st.lists(payloads, min_size=0, max_size=16)
offset_values = st.integers(min_value=0, max_value=10**9)

# ===========================================================================
# Round-trip фрейма
# ===========================================================================

class TestFrameRoundTrip:
    @given(payloads)
    def test_encode_decode_preserves_payload(self, payload: bytes) -> None:
        """Основное свойство: любой payload проходит encode→decode без потерь."""
        frame = decode_frame(encode_frame(payload))
        assert frame.payload == payload

    @given(payloads)
    def test_encoded_size_matches_frame_size(self, payload: bytes) -> None:
        assert len(encode_frame(payload)) == frame_size(len(payload))

    @given(payloads)
    def test_decoded_total_size_matches_encoding(self, payload: bytes) -> None:
        encoded = encode_frame(payload)
        frame = decode_frame(encoded)
        assert frame.total_size == len(encoded)
        assert frame.end_offset == len(encoded)

    @given(payload_lists)
    def test_scan_returns_every_payload_in_order(self, items: list[bytes]) -> None:
        """Конкатенация фреймов сканируется в те же payload и в том же порядке."""
        buffer = b"".join(encode_frame(p) for p in items)
        result = scan_frames(buffer)
        assert [f.payload for f in result.frames] == items
        assert result.trailing_bytes == 0
        assert not result.torn and not result.corrupt
        assert result.last_valid_offset == len(buffer)

    @given(payload_lists)
    def test_scan_offsets_are_frame_boundaries(self, items: list[bytes]) -> None:
        """Каждый offset — сумма размеров предыдущих фреймов."""
        assume(items)
        buffer = b"".join(encode_frame(p) for p in items)
        result = scan_frames(buffer)
        expected = 0
        for frame, payload in zip(result.frames, items):
            assert frame.offset == expected
            expected += frame_size(len(payload))
        assert result.last_valid_offset == expected

    @given(payload_lists, st.integers(min_value=0, max_value=16))
    def test_scan_from_frame_boundary_returns_remainder(
        self, items: list[bytes], skip: int
    ) -> None:
        """`start_offset` продолжает чтение с границы, не теряя остаток.

        Так RawEventReader дочитывает диапазон после своего checkpoint
        (Roadmap §6.2), поэтому свойство проверяется, а не только offset 0.
        """
        assume(items)
        skip = skip % (len(items) + 1)
        buffer = b"".join(encode_frame(p) for p in items)
        boundary = sum(frame_size(len(p)) for p in items[:skip])

        result = scan_frames(buffer, boundary)

        assert [f.payload for f in result.frames] == items[skip:]
        assert result.last_valid_offset == len(buffer)
        assert result.trailing_bytes == 0
        assert not result.torn and not result.corrupt
        for frame in result.frames:
            assert frame.offset >= boundary


# ===========================================================================
# Обрезка в произвольной точке: за boundary валидных данных нет
# ===========================================================================

class TestArbitraryTruncation:
    @given(payload_lists, st.integers(min_value=0, max_value=10**6))
    def test_no_valid_data_beyond_boundary(
        self, items: list[bytes], cut: int
    ) -> None:
        """Ключевое свойство задачи (Roadmap §6.2).

        При обрезке в любой точке scan отдаёт только те фреймы, что
        полностью уложились до неё, и не выдаёт ничего за boundary.
        """
        assume(items)
        buffer = b"".join(encode_frame(p) for p in items)
        cut = cut % (len(buffer) + 1)
        truncated = buffer[:cut]

        result = scan_frames(truncated)

        # Ожидаемый префикс: фреймы, целиком попавшие в обрезок.
        expected: list[bytes] = []
        consumed = 0
        for payload in items:
            size = frame_size(len(payload))
            if consumed + size > cut:
                break
            expected.append(payload)
            consumed += size

        assert [f.payload for f in result.frames] == expected
        assert result.last_valid_offset == consumed
        assert result.last_valid_offset <= cut
        assert result.trailing_bytes == cut - consumed

    @given(payload_lists, st.integers(min_value=0, max_value=10**6))
    def test_incomplete_tail_is_reported(
        self, items: list[bytes], cut: int
    ) -> None:
        """Неполный хвост обязан быть помечен, а не пропущен молча."""
        assume(items)
        buffer = b"".join(encode_frame(p) for p in items)
        cut = cut % (len(buffer) + 1)
        result = scan_frames(buffer[:cut])
        if result.trailing_bytes:
            assert result.torn or result.corrupt
            assert result.error

    @given(payloads)
    def test_truncated_single_frame_is_torn_not_silent(self, payload: bytes) -> None:
        """Обрезанный одиночный фрейм — TornFrameError, а не пустой результат."""
        encoded = encode_frame(payload)
        for cut in (0, HEADER_SIZE - 1, len(encoded) - 1):
            if cut < 0 or cut >= len(encoded):
                continue
            with pytest.raises(TornFrameError):
                decode_frame(encoded[:cut])


# ===========================================================================
# Повреждение содержимого обнаруживается
# ===========================================================================

class TestCorruptionDetection:
    @given(payloads, st.integers(min_value=1, max_value=255))
    def test_payload_mutation_fails_crc(self, payload: bytes, delta: int) -> None:
        """Все assume — по входам, до мутации: иначе тест недетерминирован."""
        assume(payload)
        mutated = bytearray(payload)
        mutated[0] = (mutated[0] + delta) % 256
        assume(
            zlib.crc32(bytes(mutated)) & 0xFFFFFFFF
            != zlib.crc32(payload) & 0xFFFFFFFF
        )
        encoded = bytearray(encode_frame(payload))
        encoded[HEADER_SIZE:] = mutated
        with pytest.raises(CorruptFrameError):
            decode_frame(bytes(encoded))

    @given(payloads, st.integers(min_value=1, max_value=0xFFFFFFFF))
    def test_wrong_magic_is_corrupt(self, payload: bytes, magic: int) -> None:
        assume(magic != MAGIC)
        encoded = bytearray(encode_frame(payload))
        encoded[0:4] = struct.pack("<I", magic)
        with pytest.raises(CorruptFrameError):
            decode_frame(bytes(encoded))

    @given(payloads, st.integers(min_value=2, max_value=0xFFFF))
    def test_unknown_version_is_corrupt(self, payload: bytes, version: int) -> None:
        encoded = bytearray(encode_frame(payload))
        encoded[4:6] = struct.pack("<H", version)
        with pytest.raises(CorruptFrameError):
            decode_frame(bytes(encoded))

    @given(st.binary(min_size=0, max_size=256))
    def test_scan_of_arbitrary_bytes_never_raises(self, noise: bytes) -> None:
        """scan обязан возвращать результат, а не бросать: вход недоверенный."""
        result = scan_frames(noise)
        assert result.last_valid_offset <= len(noise)
        assert result.trailing_bytes == len(noise) - result.last_valid_offset
        if result.frames:
            assert result.frames[-1].end_offset == result.last_valid_offset

    @given(payload_lists, st.binary(min_size=1, max_size=64))
    def test_garbage_after_valid_frames_stops_scan(
        self, items: list[bytes], noise: bytes
    ) -> None:
        """Мусор после валидных фреймов не отбрасывает уже прочитанное."""
        assume(items)
        prefix = b"".join(encode_frame(p) for p in items)
        result = scan_frames(prefix + noise)
        assert [f.payload for f in result.frames][: len(items)] == items
        assert result.last_valid_offset >= len(prefix)


# ===========================================================================
# Защита от негабаритного payload
# ===========================================================================

class TestPayloadLimit:
    def test_encode_refuses_payload_above_limit(self) -> None:
        """Защита от выделения гигабайтов на недоверенном входе.

        Сама мутация MAX_PAYLOAD_BYTES не проверяется через Hypothesis —
        аллокация 64 MB на каждом примере бессмысленно дорога.
        """
        with pytest.raises(FrameError, match="превышает лимит"):
            encode_frame(bytes(MAX_PAYLOAD_BYTES + 1))

    @given(st.integers(min_value=MAX_PAYLOAD_BYTES + 1, max_value=2**32 - 1))
    def test_declared_length_above_limit_is_corrupt(self, huge: int) -> None:
        """Атакующий может подменить payload_len в header.

        Без проверки лимита в decode_frame атакующий принудил бы к
        выделению гигабайтов на подконтрольном ему байте (+DoS).
        """
        header = struct.pack("<IHHII", MAGIC, FRAME_VERSION, 0, huge, 0)
        fake = header + b"\x00" * 16  # payload не важен
        with pytest.raises(CorruptFrameError, match="превышает лимит"):
            decode_frame(fake)


# ===========================================================================
# Инварианты offsets при произвольной последовательности продвижений
# ===========================================================================

ADVANCE_METHODS = ("advance_accepted", "advance_durable",
                   "advance_closed", "advance_published")

# Плотные значения: при разбросе 0..10**9 окно успеха (floor..ceiling)
# почти никогда не попадается, и ветвь «операция принята» осталась бы
# непроверенной — тест выродился бы в проверку одних отказов.
dense_offsets = st.integers(min_value=0, max_value=64)

operations = st.lists(
    st.tuples(st.sampled_from(ADVANCE_METHODS), dense_offsets),
    min_size=0, max_size=24,
)


def expected_success(state: OffsetSet, method: str, value: int) -> bool:
    """Должна ли операция быть принята — модель, независимая от кода.

    Выведена из Roadmap §6.2 напрямую: продвижение только вперёд плюс
    цепочка published <= closed <= durable <= accepted. Сравнение с этой
    моделью отличает «отклонено правильно» от «отклонено всегда»:
    тест, принимающий любой OffsetInvariantError, пропустил бы мутанта,
    который отвергает вообще всё.
    """
    floor = {
        "advance_accepted": state.accepted,
        "advance_durable": state.durable,
        "advance_closed": state.closed,
        "advance_published": state.published,
    }[method]
    ceiling = {
        "advance_accepted": None,      # accepted сверху не ограничен
        "advance_durable": state.accepted,
        "advance_closed": state.durable,
        "advance_published": state.closed,
    }[method]

    if value < floor:
        return False
    return ceiling is None or value <= ceiling


class TestOffsetInvariants:
    @given(operations)
    @settings(max_examples=300)
    def test_outcome_matches_independent_model(
        self, ops: list[tuple[str, int]]
    ) -> None:
        """Ключевое свойство: исход каждой операции совпадает с моделью.

        Проверяется не «не упало», а именно равенство предсказанию: и
        «всегда отклонять», и «всегда принимать» ломают этот тест.
        """
        state = OffsetSet(partition_id="BTCUSDT")
        for method, value in ops:
            predicted = expected_success(state, method, value)
            try:
                state = getattr(state, method)(value)
            except OffsetInvariantError:
                assert not predicted, (
                    f"{method}({value}) отклонён, хотя модель разрешает: "
                    f"accepted={state.accepted} durable={state.durable} "
                    f"closed={state.closed} published={state.published}"
                )
            else:
                assert predicted, (
                    f"{method}({value}) принят, хотя модель запрещает"
                )
                state.validate()

    @given(operations)
    @settings(max_examples=200)
    def test_refusal_leaves_state_untouched(
        self, ops: list[tuple[str, int]]
    ) -> None:
        """Отказ обязан быть без побочного эффекта."""
        state = OffsetSet(partition_id="BTCUSDT")
        for method, value in ops:
            before = state
            try:
                state = getattr(state, method)(value)
            except OffsetInvariantError:
                assert state is before

    @given(operations)
    @settings(max_examples=200)
    def test_no_field_decreases_on_success(
        self, ops: list[tuple[str, int]]
    ) -> None:
        """Принятая операция не откатывает ни один offset назад."""
        state = OffsetSet(partition_id="BTCUSDT")
        for method, value in ops:
            before = state
            try:
                state = getattr(state, method)(value)
            except OffsetInvariantError:
                continue
            for field in ("accepted", "durable", "closed", "published"):
                assert getattr(state, field) >= getattr(before, field)

    # Детерминированное покрытие обеих ветвей: floor-1, floor, ceiling,
    # ceiling+1 для каждого метода. Не зависит от того, что сгенерирует
    # Hypothesis, поэтому «всегда отклонять» падает при любом seed.
    BASE = dict(accepted=40, durable=30, closed=20, published=10)

    @pytest.mark.parametrize(
        ("method", "value", "accepted_expected"),
        [
            ("advance_accepted", -1, False),
            ("advance_accepted", 39, False),
            ("advance_accepted", 40, True),
            ("advance_accepted", 41, True),
            ("advance_durable", 29, False),
            ("advance_durable", 30, True),
            ("advance_durable", 40, True),
            ("advance_durable", 41, False),
            ("advance_closed", 19, False),
            ("advance_closed", 20, True),
            ("advance_closed", 30, True),
            ("advance_closed", 31, False),
            ("advance_published", 9, False),
            ("advance_published", 10, True),
            ("advance_published", 20, True),
            ("advance_published", 21, False),
        ],
    )
    def test_boundary_outcomes(
        self, method: str, value: int, accepted_expected: bool
    ) -> None:
        state = OffsetSet(partition_id="BTCUSDT", **self.BASE)
        assert expected_success(state, method, value) is accepted_expected
        try:
            getattr(state, method)(value)
        except OffsetInvariantError:
            assert not accepted_expected, f"{method}({value}) отклонён зря"
        else:
            assert accepted_expected, f"{method}({value}) принят зря"

    @given(offset_values, offset_values, offset_values, offset_values)
    def test_construction_accepts_only_ordered_offsets(
        self, accepted: int, durable: int, closed: int, published: int
    ) -> None:
        """Порядок durable≤accepted, closed≤durable, published≤closed обязателен."""
        ordered = durable <= accepted and closed <= durable and published <= closed
        try:
            OffsetSet(
                partition_id="BTCUSDT", accepted=accepted, durable=durable,
                closed=closed, published=published,
            )
        except OffsetInvariantError:
            assert not ordered
        else:
            assert ordered

    @given(operations)
    def test_live_publish_ceiling_never_exceeds_durable(
        self, ops: list[tuple[str, int]]
    ) -> None:
        """Roadmap §5.1: speculative pre-fsync tail запрещён."""
        state = OffsetSet(partition_id="BTCUSDT")
        for method, value in ops:
            try:
                state = getattr(state, method)(value)
            except OffsetInvariantError:
                continue
            assert state.live_publish_ceiling() == state.durable
            assert state.live_publish_ceiling() <= state.accepted

    @given(operations)
    def test_replay_safe_offset_never_exceeds_published(
        self, ops: list[tuple[str, int]]
    ) -> None:
        """Удалять WAL можно только до опубликованного диапазона (§6.2)."""
        state = OffsetSet(partition_id="BTCUSDT")
        for method, value in ops:
            try:
                state = getattr(state, method)(value)
            except OffsetInvariantError:
                continue
            assert 0 <= state.replay_safe_offset() <= state.published

    @given(operations)
    def test_retention_bytes_is_unpublished_remainder(
        self, ops: list[tuple[str, int]]
    ) -> None:
        state = OffsetSet(partition_id="BTCUSDT")
        for method, value in ops:
            try:
                state = getattr(state, method)(value)
            except OffsetInvariantError:
                continue
            assert state.wal_retention_bytes() == state.accepted - state.published
            assert state.wal_retention_bytes() >= 0


# ===========================================================================
# Consumer checkpoints
# ===========================================================================

consumer_ids = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    min_size=1, max_size=6,
)


class TestConsumerCheckpoints:
    @given(consumer_ids, offset_values, offset_values,
           st.integers(min_value=0, max_value=5), st.integers(min_value=0, max_value=5))
    def test_rollback_requires_new_lease_generation(
        self, consumer_id: str, first: int, second: int,
        gen_first: int, gen_second: int,
    ) -> None:
        """Откат offset разрешён только с новой lease generation (§6.2)."""
        state = OffsetSet(partition_id="BTCUSDT").upsert_consumer(
            ConsumerOffset(consumer_id=consumer_id, wal_offset=first,
                           protocol_version="1.0", lease_generation=gen_first)
        )
        candidate = ConsumerOffset(
            consumer_id=consumer_id, wal_offset=second,
            protocol_version="1.0", lease_generation=gen_second,
        )
        rollback_without_takeover = second < first and gen_second <= gen_first
        try:
            updated = state.upsert_consumer(candidate)
        except OffsetInvariantError:
            assert rollback_without_takeover
        else:
            assert not rollback_without_takeover
            assert updated.consumer(consumer_id) == candidate

    @given(st.lists(consumer_ids, min_size=1, max_size=5, unique=True), offset_values)
    def test_missing_required_consumer_counts_as_zero(
        self, ids: list[str], published: int
    ) -> None:
        """Отсутствующий обязательный consumer держит WAL: его данные ещё нужны."""
        state = OffsetSet(
            partition_id="BTCUSDT", accepted=published, durable=published,
            closed=published, published=published,
        )
        required = frozenset(ids)
        assert state.min_consumer_offset(required) == 0
        assert state.replay_safe_offset(wal_only_consumer_ids=required) == 0

    @given(consumer_ids, offset_values)
    def test_upsert_does_not_duplicate_consumer(
        self, consumer_id: str, offset: int
    ) -> None:
        state = OffsetSet(partition_id="BTCUSDT")
        for generation in range(3):
            state = state.upsert_consumer(
                ConsumerOffset(consumer_id=consumer_id, wal_offset=offset,
                              protocol_version="1.0", lease_generation=generation)
            )
        assert len(state.consumers) == 1
