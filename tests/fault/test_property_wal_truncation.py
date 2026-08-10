"""
Property-based тесты crash-recovery WAL при обрезке файла.
Источник: Roadmap §4 («Backend tests | pytest + Hypothesis»), §6.2.

    Frame имеет length + checksum/CRC; torn frame при старте отбрасывается
    до последнего валидного boundary и создаёт incident, если был объявлен
    durable.

Проверяемое свойство: при обрезке сегмента в ЛЮБОЙ точке recovery не даёт
валидных данных за boundary, а восстановленные записи — префикс записанных.

Работа идёт на настоящих файлах: обрезка проверяется вместе с truncate и
fsync, а не на буфере в памяти. Поэтому каталог создаётся внутри примера —
function-scoped fixture нельзя переиспользовать между примерами Hypothesis.

Задача P1-S1-005.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from packages.storage.frames import frame_size
from packages.storage.wal import GroupCommitPolicy, WalPartition, parse_segment_name

pytestmark = [pytest.mark.fault, pytest.mark.property]

PARTITION = "BTCUSDT"

payloads = st.lists(
    st.binary(min_size=1, max_size=64), min_size=1, max_size=12
)
cut_points = st.integers(min_value=0, max_value=10**6)

# Файловые примеры дороже вычислительных: ограничиваем их число и снимаем
# deadline — иначе тест станет flaky от дисковой задержки, а не от дефекта.
FILE_SETTINGS = settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

def write_records(directory: Path, items: list[bytes]) -> int:
    """Записать записи и вернуть durable offset.

    max_records=1 — fsync после каждой записи: durable должен покрывать всё
    записанное, иначе обрезка проверяла бы недостоверный хвост.
    """
    partition = WalPartition(
        directory, PARTITION, group_commit=GroupCommitPolicy(max_records=1)
    )
    for payload in items:
        partition.append(payload)
    partition.commit()
    durable = partition.durable_offset
    partition.close()
    return durable


def truncate_segment(segment: Path, cut: int) -> None:
    """Обрезать сегмент и довести обрезку до диска.

    Повторяет последовательность прод-кода (`WalPartition.recover`:
    truncate → flush → fsync). Без fsync тест проверял бы только состояние
    page cache, то есть заявленная проверка durability не выполнялась бы.
    """
    with open(segment, "r+b") as handle:
        handle.truncate(cut)
        handle.flush()
        os.fsync(handle.fileno())


def single_segment(directory: Path) -> Path:
    """Единственный сегмент партиции.

    Размеры примеров многократно меньше max_segment_bytes, поэтому сегмент
    один; утверждение фиксирует это допущение явно.
    """
    segments = [
        p for p in directory.iterdir()
        if p.is_file() and parse_segment_name(p.name) is not None
    ]
    assert len(segments) == 1, f"ожидался один сегмент, найдено {len(segments)}"
    return segments[0]


def surviving_prefix(items: list[bytes], cut: int) -> list[bytes]:
    """Записи, целиком уложившиеся до точки обрезки."""
    result: list[bytes] = []
    consumed = 0
    for payload in items:
        size = frame_size(len(payload))
        if consumed + size > cut:
            break
        result.append(payload)
        consumed += size
    return result


# ===========================================================================
# Обрезка в произвольной точке
# ===========================================================================

class TestArbitraryTruncationRecovery:
    @given(payloads, cut_points)
    @FILE_SETTINGS
    def test_recovery_yields_no_data_beyond_boundary(
        self, items: list[bytes], cut: int
    ) -> None:
        """Ключевое свойство задачи.

        Обрезка в любой точке → recovery отдаёт ровно префикс целых записей,
        а last_valid_offset не превышает точку обрезки.
        """
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            durable = write_records(directory, items)
            segment = single_segment(directory)
            size = segment.stat().st_size
            cut = cut % (size + 1)

            truncate_segment(segment, cut)

            expected = surviving_prefix(items, cut)
            partition = WalPartition(directory, PARTITION)
            report = partition.recover(declared_durable_offset=durable)

            assert report.valid_records == len(expected)
            assert report.last_valid_offset <= cut
            assert report.last_valid_offset == sum(
                frame_size(len(p)) for p in expected
            )
            frames = partition.read_range(0)
            assert [f.payload for f in frames] == expected

    @given(payloads, cut_points)
    @FILE_SETTINGS
    def test_recovered_records_are_prefix_of_written(
        self, items: list[bytes], cut: int
    ) -> None:
        """Recovery не переставляет и не изобретает записи — только усекает."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_records(directory, items)
            segment = single_segment(directory)
            cut = cut % (segment.stat().st_size + 1)
            truncate_segment(segment, cut)

            partition = WalPartition(directory, PARTITION)
            partition.recover()
            recovered = [f.payload for f in partition.read_range(0)]
            assert recovered == items[: len(recovered)]

    @given(payloads, cut_points)
    @FILE_SETTINGS
    def test_torn_tail_is_physically_discarded(
        self, items: list[bytes], cut: int
    ) -> None:
        """Непроверяемые байты не остаются в файле: durable-граница их не включает."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_records(directory, items)
            segment = single_segment(directory)
            cut = cut % (segment.stat().st_size + 1)
            truncate_segment(segment, cut)

            partition = WalPartition(directory, PARTITION)
            report = partition.recover()
            assert segment.stat().st_size == report.last_valid_offset

    @given(payloads, cut_points)
    @FILE_SETTINGS
    def test_offsets_stay_consistent_after_recovery(
        self, items: list[bytes], cut: int
    ) -> None:
        """После recovery accepted=durable=boundary, а инварианты сохранены."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_records(directory, items)
            segment = single_segment(directory)
            cut = cut % (segment.stat().st_size + 1)
            truncate_segment(segment, cut)

            partition = WalPartition(directory, PARTITION)
            report = partition.recover()
            offsets = partition.offsets
            offsets.validate()
            assert offsets.accepted == report.last_valid_offset
            assert offsets.durable == report.last_valid_offset
            assert offsets.closed <= offsets.durable
            assert offsets.published <= offsets.closed

    @given(payloads, cut_points)
    @FILE_SETTINGS
    def test_recovery_is_idempotent(self, items: list[bytes], cut: int) -> None:
        """Повторный recovery не должен отбрасывать ещё что-нибудь."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_records(directory, items)
            segment = single_segment(directory)
            cut = cut % (segment.stat().st_size + 1)
            truncate_segment(segment, cut)

            first = WalPartition(directory, PARTITION).recover()
            second = WalPartition(directory, PARTITION).recover()
            assert second.last_valid_offset == first.last_valid_offset
            assert second.valid_records == first.valid_records
            assert second.truncated_bytes == 0
            assert second.clean


# ===========================================================================
# Граница durable: incident, а не молчаливая потеря
# ===========================================================================

class TestDurableViolation:
    @given(payloads, cut_points)
    @FILE_SETTINGS
    def test_violation_reported_exactly_when_boundary_below_declared(
        self, items: list[bytes], cut: int
    ) -> None:
        """Roadmap §6.2: отброшенный хвост ниже durable — incident."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            durable = write_records(directory, items)
            segment = single_segment(directory)
            cut = cut % (segment.stat().st_size + 1)
            truncate_segment(segment, cut)

            report = WalPartition(directory, PARTITION).recover(
                declared_durable_offset=durable
            )
            assert report.durable_violation == (report.last_valid_offset < durable)

    @given(payloads)
    @FILE_SETTINGS
    def test_untouched_wal_recovers_clean(self, items: list[bytes]) -> None:
        """Без обрезки recovery обязан быть чистым и вернуть всё записанное."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            durable = write_records(directory, items)

            partition = WalPartition(directory, PARTITION)
            report = partition.recover(declared_durable_offset=durable)

            assert report.clean
            assert not report.durable_violation
            assert report.valid_records == len(items)
            assert report.last_valid_offset == durable
            assert [f.payload for f in partition.read_range(0)] == items


# ===========================================================================
# Обрезка ровно по границе фрейма
# ===========================================================================

class TestBoundaryAlignedTruncation:
    @given(payloads, st.integers(min_value=0, max_value=12))
    @FILE_SETTINGS
    def test_cut_on_frame_boundary_is_clean(
        self, items: list[bytes], keep: int
    ) -> None:
        """Обрезка по границе — потеря записей, но не torn: хвост не рваный."""
        assume(items)
        keep = keep % (len(items) + 1)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_records(directory, items)
            segment = single_segment(directory)
            boundary = sum(frame_size(len(p)) for p in items[:keep])
            truncate_segment(segment, boundary)

            partition = WalPartition(directory, PARTITION)
            report = partition.recover()

            assert not report.torn and not report.corrupt
            assert report.truncated_bytes == 0
            assert report.valid_records == keep
            assert report.last_valid_offset == boundary
            assert [f.payload for f in partition.read_range(0)] == items[:keep]
