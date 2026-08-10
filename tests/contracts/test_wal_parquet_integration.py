"""
Интеграционные тесты WalPartition → Parquet (P1-S1-004 финализация).

Проверяют полный цикл: append → commit → roll → close_and_publish → .parquet.
"""

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
import pyarrow.parquet as pq

from packages.storage import WalPartition

pytestmark = pytest.mark.contract


class TestWalParquetIntegration:
    """Полный цикл WAL → Parquet через close_and_publish_segment."""

    def test_close_and_publish_creates_parquet_file(self):
        """append → commit → roll → close_and_publish → .parquet существует."""
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            wal = WalPartition(directory, "BTCUSDT", max_segment_bytes=1024)

            # Записываем несколько записей
            payloads = [b"event1", b"event2", b"event3"]
            offsets = []
            for payload in payloads:
                result = wal.append(payload)
                offsets.append(result.wal_offset)
            wal.commit()

            start_offset = offsets[0]
            end_offset = wal.accepted_offset

            # Закрываем сегмент (roll_segment продвигает closed)
            wal.roll_segment()

            # Публикуем сегмент
            parquet_path = wal.close_and_publish_segment(start_offset, end_offset)

            assert parquet_path.exists()
            assert parquet_path.suffix == ".parquet"
            assert parquet_path.parent == directory

    def test_parquet_contains_correct_row_count(self):
        """Parquet содержит столько строк, сколько было записей."""
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            wal = WalPartition(directory, "BTCUSDT", max_segment_bytes=1024)

            payloads = [b"a", b"b", b"c", b"d"]
            for payload in payloads:
                wal.append(payload)
            wal.commit()
            wal.roll_segment()

            parquet_path = wal.close_and_publish_segment(0, wal.offsets.closed)

            table = pq.read_table(parquet_path)
            assert table.num_rows == len(payloads)

    def test_parquet_rows_have_correct_structure(self):
        """Строки Parquet содержат все поля из BTCUSDT_SCHEMA."""
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            wal = WalPartition(directory, "BTCUSDT")

            wal.append(b"test_payload")
            wal.commit()
            wal.roll_segment()

            parquet_path = wal.close_and_publish_segment(0, wal.offsets.closed)

            table = pq.read_table(parquet_path)
            row = table.to_pylist()[0]

            # Проверка stub-полей
            assert row["eventType"] == "raw_frame"
            assert row["symbol"] == "BTCUSDT"
            assert row["coverageBps"] == Decimal("0.0000")
            assert row["connectionEpoch"] == "stub"
            assert row["timestampUs"] == 0  # offset первой записи

    def test_empty_range_raises_error(self):
        """Пустой диапазон → ValueError."""
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            wal = WalPartition(directory, "BTCUSDT")

            with pytest.raises(ValueError, match="пуст|без записей"):
                wal.close_and_publish_segment(0, 0)

    def test_published_offset_advances_after_commit(self):
        """published offset продвигается после успешного commit."""
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            wal = WalPartition(directory, "BTCUSDT")

            wal.append(b"payload1")
            wal.append(b"payload2")
            wal.commit()
            wal.roll_segment()

            end_offset = wal.offsets.closed
            assert wal.offsets.published == 0  # до публикации

            wal.close_and_publish_segment(0, end_offset)

            # После публикации published должен продвинуться до end_offset
            # (advance_checkpoint вызывается внутри commit_segment с payload.max_wal_offset)
            assert wal.offsets.published == end_offset

    def test_multiple_segments_can_be_published(self):
        """Можно опубликовать несколько сегментов подряд."""
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            wal = WalPartition(directory, "BTCUSDT", max_segment_bytes=100)

            # Первый сегмент
            wal.append(b"segment1_record1")
            wal.append(b"segment1_record2")
            wal.commit()
            wal.roll_segment()
            end1 = wal.offsets.closed

            path1 = wal.close_and_publish_segment(0, end1)

            # Второй сегмент
            wal.append(b"segment2_record1")
            wal.append(b"segment2_record2")
            wal.commit()
            wal.roll_segment()
            end2 = wal.offsets.closed

            path2 = wal.close_and_publish_segment(end1, end2)

            assert path1.exists()
            assert path2.exists()
            assert path1 != path2

            # Проверка row counts
            table1 = pq.read_table(path1)
            table2 = pq.read_table(path2)
            assert table1.num_rows == 2
            assert table2.num_rows == 2
