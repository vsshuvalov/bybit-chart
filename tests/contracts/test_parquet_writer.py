"""
Контрактные тесты Parquet writer (ADR-004).

Проверяют:
- Arrow Schema с Decimal128(18, 4) для coverageBps
- Запись и чтение BookCheckpoint через PyArrow
- Валидация footer
- Интеграция с commit_segment
"""

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
import pyarrow.parquet as pq

from packages.storage import (
    BTCUSDT_SCHEMA,
    SCHEMA_VERSION_MAJOR,
    SCHEMA_VERSION_MINOR,
    ParquetWriter,
    commit_segment,
    validate_parquet_footer,
)

pytestmark = pytest.mark.contract


class TestArrowSchema:
    """ADR-004: Arrow Schema с Decimal128 для coverageBps."""

    def test_schema_contains_decimal128_coverage_bps(self):
        """coverageBps объявлен как Decimal128(18, 4)."""
        field = BTCUSDT_SCHEMA.field("coverageBps")
        # PyArrow представляет как pa.decimal128(18, 4)
        assert "decimal128" in str(field.type)
        assert "18" in str(field.type) and "4" in str(field.type)

    def test_schema_metadata_contains_version(self):
        """Footer метаданные фиксируют schema version (ADR-004 §4)."""
        meta = BTCUSDT_SCHEMA.metadata
        assert meta is not None
        assert b"schema_version_major" in meta
        assert b"schema_version_minor" in meta
        assert meta[b"schema_version_major"] == str(SCHEMA_VERSION_MAJOR).encode()
        assert meta[b"schema_version_minor"] == str(SCHEMA_VERSION_MINOR).encode()

    def test_schema_has_int64_for_price_and_qty(self):
        """price/qty остаются int64 (масштабированные целые)."""
        price_field = BTCUSDT_SCHEMA.field("priceTicks")
        qty_field = BTCUSDT_SCHEMA.field("qtySteps")
        assert str(price_field.type) == "int64"
        assert str(qty_field.type) == "int64"


class TestParquetWriter:
    """Запись и валидация Parquet-сегментов."""

    def test_write_and_read_book_checkpoint(self, tmp_path):
        """Round-trip: записать BookCheckpoint, прочитать через PyArrow."""
        segment = tmp_path / "segment.parquet"
        writer = ParquetWriter(segment)

        rows = [
            {
                "timestampUs": 1_700_000_000_000,
                "eventType": "BookCheckpoint",
                "symbol": "BTCUSDT",
                "priceTicks": 50000_00000000,
                "qtySteps": 1_00000000,
                "depth": 200,
                "updateId": 1000,
                "sequence": 1,
                "levelCount": 10,
                "coverageBoundaryTicks": 50000,
                "coverageBps": Decimal("25.1234"),  # ADR-004: Decimal128(18, 4)
                "isFeedRangeComplete": True,
                "connectionEpoch": "epoch-1",
                "exchangeTimestampMs": 1_700_000_000_000,
                "outerTimestampMs": 1_700_000_000_100,
                "receiveTimestampMs": 1_700_000_000_200,
            }
        ]

        writer.write_batch(rows)
        writer.close()

        assert segment.exists()

        # Чтение через PyArrow
        table = pq.read_table(segment)
        assert table.num_rows == 1

        row = table.to_pylist()[0]
        assert row["eventType"] == "BookCheckpoint"
        assert row["symbol"] == "BTCUSDT"
        assert row["coverageBps"] == Decimal("25.1234")
        assert row["priceTicks"] == 50000_00000000
        assert row["isFeedRangeComplete"] is True

    def test_write_batch_accepts_string_for_decimal(self, tmp_path):
        """Decimal128 принимается строкой из JSON (wire-format)."""
        segment = tmp_path / "segment.parquet"
        writer = ParquetWriter(segment)

        rows = [
            {
                "timestampUs": 1_700_000_000_000,
                "eventType": "BookCheckpoint",
                "symbol": "BTCUSDT",
                "priceTicks": 50000_00000000,
                "qtySteps": 1_00000000,
                "depth": 200,
                "updateId": 1000,
                "sequence": 1,
                "levelCount": 10,
                "coverageBoundaryTicks": 50000,
                "coverageBps": "25.1234",  # строка, не Decimal
                "isFeedRangeComplete": True,
                "connectionEpoch": "epoch-1",
                "exchangeTimestampMs": 1_700_000_000_000,
                "outerTimestampMs": 1_700_000_000_100,
                "receiveTimestampMs": 1_700_000_000_200,
            }
        ]

        writer.write_batch(rows)
        writer.close()

        table = pq.read_table(segment)
        row = table.to_pylist()[0]
        assert row["coverageBps"] == Decimal("25.1234")

    def test_close_is_idempotent(self, tmp_path):
        """Повторный close() не падает."""
        segment = tmp_path / "segment.parquet"
        writer = ParquetWriter(segment)
        writer.write_batch([{
            "timestampUs": 1000, "eventType": "test", "symbol": "BTCUSDT",
            "priceTicks": 1, "qtySteps": 1, "depth": 1, "updateId": 1,
            "sequence": 1, "levelCount": 1, "coverageBoundaryTicks": 1,
            "coverageBps": Decimal("0.0001"), "isFeedRangeComplete": True,
            "connectionEpoch": "e", "exchangeTimestampMs": 1,
            "outerTimestampMs": 1, "receiveTimestampMs": 1,
        }])
        writer.close()
        writer.close()  # второй раз

    def test_empty_batch_is_noop(self, tmp_path):
        """Пустой батч не ломает writer."""
        segment = tmp_path / "segment.parquet"
        writer = ParquetWriter(segment)
        writer.write_batch([])
        writer.write_batch([{
            "timestampUs": 1000, "eventType": "test", "symbol": "BTCUSDT",
            "priceTicks": 1, "qtySteps": 1, "depth": 1, "updateId": 1,
            "sequence": 1, "levelCount": 1, "coverageBoundaryTicks": 1,
            "coverageBps": Decimal("1.0000"), "isFeedRangeComplete": True,
            "connectionEpoch": "e", "exchangeTimestampMs": 1,
            "outerTimestampMs": 1, "receiveTimestampMs": 1,
        }])
        writer.close()
        table = pq.read_table(segment)
        assert table.num_rows == 1


class TestValidateParquetFooter:
    """Валидация footer закрытого Parquet-файла (Roadmap §6.4)."""

    def test_valid_footer_returns_metadata(self, tmp_path):
        """Валидный footer возвращает row_count и schema_version."""
        segment = tmp_path / "segment.parquet"
        writer = ParquetWriter(segment)
        writer.write_batch([{
            "timestampUs": 1000, "eventType": "test", "symbol": "BTCUSDT",
            "priceTicks": 1, "qtySteps": 1, "depth": 1, "updateId": 1,
            "sequence": 1, "levelCount": 1, "coverageBoundaryTicks": 1,
            "coverageBps": Decimal("1.0000"), "isFeedRangeComplete": True,
            "connectionEpoch": "e", "exchangeTimestampMs": 1,
            "outerTimestampMs": 1, "receiveTimestampMs": 1,
        }])
        writer.close()

        meta = validate_parquet_footer(segment)
        assert meta["row_count"] == 1
        assert meta["schema_version_major"] == SCHEMA_VERSION_MAJOR
        assert meta["schema_version_minor"] == SCHEMA_VERSION_MINOR

    def test_missing_file_raises(self, tmp_path):
        """Отсутствующий файл → ValueError."""
        with pytest.raises(ValueError, match="не найден"):
            validate_parquet_footer(tmp_path / "nonexistent.parquet")

    def test_empty_file_raises(self, tmp_path):
        """Пустой Parquet (0 строк) → ValueError."""
        segment = tmp_path / "empty.parquet"
        writer = ParquetWriter(segment)
        # writer.write_batch([])  # не пишем ничего
        writer.close()

        with pytest.raises(ValueError, match="пуст|0 строк"):
            validate_parquet_footer(segment)


class TestCommitSegmentIntegration:
    """Интеграция ParquetWriter с commit_segment."""

    @pytest.mark.skip(reason="требует адаптацию к SegmentPayload/Manifest API")
    def test_commit_segment_with_parquet_writer(self, tmp_path):
        """Полный цикл: write → validate → atomic rename.

        TODO: адаптировать к актуальной сигнатуре commit_segment после
        реализации интеграции WAL → Parquet в WalPartition.
        """
        pass

    @pytest.mark.skip(reason="требует адаптацию к SegmentPayload/Manifest API")
    def test_validator_rejects_corrupted_footer(self, tmp_path):
        """Валидатор отклоняет повреждённый footer.

        TODO: адаптировать к актуальной сигнатуре commit_segment.
        """
        pass
