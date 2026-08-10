"""
Тесты BookCheckpoint integration в EventCollector (Этап 1 / P1-B1).

Проверяют:
- append_book_checkpoint() → WAL
- deserialize_event_from_payload() → BookCheckpoint
- book_checkpoint_to_parquet_row()
- close_and_publish_segment() с BookCheckpoint
"""

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from contracts.schemas import BookCheckpoint, RawBookLevel
from packages.bybit.collector import (
    EventCollector,
    deserialize_event_from_payload,
    book_checkpoint_to_parquet_row,
)

pytestmark = pytest.mark.contract


class TestBookCheckpointIntegration:
    """Тесты интеграции BookCheckpoint в EventCollector."""

    def test_append_book_checkpoint(self):
        """append_book_checkpoint() записывает checkpoint в WAL."""
        with tempfile.TemporaryDirectory() as td:
            collector = EventCollector(Path(td) / "BTCUSDT", "BTCUSDT")

            checkpoint = BookCheckpoint(
                symbol="BTCUSDT",
                depth=50,
                update_id=123456,
                sequence=1,
                exchange_timestamp_ms=1000,
                outer_timestamp_ms=1001,
                receive_timestamp_ms=1002,
                bids=[
                    RawBookLevel(price_ticks=64000000, qty_steps=1000),
                    RawBookLevel(price_ticks=63999900, qty_steps=2000),
                ],
                asks=[
                    RawBookLevel(price_ticks=64000100, qty_steps=1500),
                    RawBookLevel(price_ticks=64000200, qty_steps=2500),
                ],
                level_count=4,
                coverage_boundary_ticks=200,
                coverage_bps=Decimal("0.3125"),
                is_feed_range_complete=True,
                connection_epoch="test-epoch",
            )

            offset = collector.append_book_checkpoint(checkpoint)

            assert offset == 0  # первая запись
            assert collector.wal.offsets.closed == 0
            assert collector.wal.offsets.durable == 0

            # Flush → commit
            collector.flush()
            assert collector.wal.offsets.durable > 0

            collector.close()

    def test_deserialize_event_book_checkpoint(self):
        """deserialize_event_from_payload() корректно десериализует BookCheckpoint."""
        checkpoint = BookCheckpoint(
            symbol="BTCUSDT",
            depth=50,
            update_id=123456,
            sequence=1,
            exchange_timestamp_ms=1000,
            outer_timestamp_ms=1001,
            receive_timestamp_ms=1002,
            bids=[RawBookLevel(price_ticks=64000000, qty_steps=1000)],
            asks=[RawBookLevel(price_ticks=64000100, qty_steps=1500)],
            level_count=2,
            coverage_boundary_ticks=100,
            coverage_bps=Decimal("0.1563"),
            is_feed_range_complete=True,
            connection_epoch="test",
        )

        # Сериализация через EventCollector
        with tempfile.TemporaryDirectory() as td:
            collector = EventCollector(Path(td) / "BTCUSDT", "BTCUSDT")
            payload = collector._serialize_event(checkpoint)
            collector.close()

        # Десериализация
        deserialized = deserialize_event_from_payload(payload)

        assert isinstance(deserialized, BookCheckpoint)
        assert deserialized.symbol == "BTCUSDT"
        assert deserialized.depth == 50
        assert deserialized.update_id == 123456
        assert deserialized.level_count == 2
        assert len(deserialized.bids) == 1
        assert len(deserialized.asks) == 1
        assert deserialized.bids[0].price_ticks == 64000000
        assert deserialized.asks[0].price_ticks == 64000100

    def test_book_checkpoint_to_parquet_row(self):
        """book_checkpoint_to_parquet_row() конвертирует BookCheckpoint → row."""
        checkpoint = BookCheckpoint(
            symbol="BTCUSDT",
            depth=50,
            update_id=123456,
            sequence=1,
            exchange_timestamp_ms=1000,
            outer_timestamp_ms=1001,
            receive_timestamp_ms=1002,
            bids=[
                RawBookLevel(price_ticks=64000000, qty_steps=1000),
                RawBookLevel(price_ticks=63999900, qty_steps=2000),
            ],
            asks=[RawBookLevel(price_ticks=64000100, qty_steps=1500)],
            level_count=3,
            coverage_boundary_ticks=200,
            coverage_bps=Decimal("0.3125"),
            is_feed_range_complete=True,
            connection_epoch="test-epoch",
        )

        row = book_checkpoint_to_parquet_row(checkpoint)

        assert row["timestampUs"] == 1000 * 1000  # ms → µs
        assert row["eventType"] == "BookCheckpoint"
        assert row["symbol"] == "BTCUSDT"
        assert row["depth"] == 50
        assert row["updateId"] == 123456
        assert row["sequence"] == 1
        assert row["levelCount"] == 3
        assert row["coverageBoundaryTicks"] == 200
        assert row["coverageBps"] == Decimal("0.3125")
        assert row["isFeedRangeComplete"] is True
        assert row["connectionEpoch"] == "test-epoch"

        # Проверка bids/asks как JSON strings
        import json
        bids = json.loads(row["bids"])
        asks = json.loads(row["asks"])

        assert len(bids) == 2
        assert bids[0] == {"price": 64000000, "qty": 1000}
        assert bids[1] == {"price": 63999900, "qty": 2000}

        assert len(asks) == 1
        assert asks[0] == {"price": 64000100, "qty": 1500}

        # RawTrade-специфичные поля = stub
        assert row["priceTicks"] == 0
        assert row["qtySteps"] == 0

    def test_publish_segment_with_book_checkpoint(self):
        """close_and_publish_segment() с BookCheckpoint → Parquet."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            checkpoint = BookCheckpoint(
                symbol="BTCUSDT",
                depth=50,
                update_id=123456,
                sequence=1,
                exchange_timestamp_ms=1000,
                outer_timestamp_ms=1001,
                receive_timestamp_ms=1002,
                bids=[RawBookLevel(price_ticks=64000000, qty_steps=1000)],
                asks=[RawBookLevel(price_ticks=64000100, qty_steps=1500)],
                level_count=2,
                coverage_boundary_ticks=100,
                coverage_bps=Decimal("0.1563"),
                is_feed_range_complete=True,
                connection_epoch="test",
            )

            collector.append_book_checkpoint(checkpoint)
            collector.flush()
            collector.wal.roll_segment()

            # Публикация с реальной десериализацией
            parquet_path = collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )

            assert parquet_path.exists()
            assert parquet_path.suffix == ".parquet"

            # Чтение через ParquetReader
            from packages.storage.parquet_reader import ParquetReader

            reader = ParquetReader(base_dir)
            events = reader.read_range(
                symbol="BTCUSDT",
                start_ts=0,
                end_ts=10000 * 1000,
                event_type="BookCheckpoint",
            )

            assert len(events) == 1
            event = events[0]

            assert event["eventType"] == "BookCheckpoint"
            assert event["symbol"] == "BTCUSDT"
            assert event["depth"] == 50
            assert event["levelCount"] == 2

            # Проверка bids/asks
            import json
            bids = json.loads(event["bids"])
            asks = json.loads(event["asks"])

            assert len(bids) == 1
            assert bids[0]["price"] == 64000000
            assert len(asks) == 1
            assert asks[0]["price"] == 64000100

            collector.close()

    def test_mixed_events_in_segment(self):
        """Сегмент с RawTrade + BookCheckpoint публикуется корректно."""
        with tempfile.TemporaryDirectory() as td:
            from contracts.schemas import RawTrade, TakerSide

            base_dir = Path(td)
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            # Добавляем trade
            trade = RawTrade(
                symbol="BTCUSDT",
                trade_id="trade-1",
                sequence=1,
                exchange_timestamp_ms=1000,
                outer_timestamp_ms=1001,
                receive_timestamp_ms=1002,
                price_ticks=64000000,
                qty_steps=1000,
                taker_side=TakerSide.BUY,
            )
            collector.append_trade(trade)

            # Добавляем checkpoint
            checkpoint = BookCheckpoint(
                symbol="BTCUSDT",
                depth=50,
                update_id=123456,
                sequence=2,
                exchange_timestamp_ms=2000,
                outer_timestamp_ms=2001,
                receive_timestamp_ms=2002,
                bids=[RawBookLevel(price_ticks=64000000, qty_steps=1000)],
                asks=[RawBookLevel(price_ticks=64000100, qty_steps=1500)],
                level_count=2,
                coverage_boundary_ticks=100,
                coverage_bps=Decimal("0.1563"),
                is_feed_range_complete=True,
                connection_epoch="test",
            )
            collector.append_book_checkpoint(checkpoint)

            collector.flush()
            collector.wal.roll_segment()

            # Публикация
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )

            # Чтение обоих типов событий
            from packages.storage.parquet_reader import ParquetReader

            reader = ParquetReader(base_dir)

            # Все события
            all_events = reader.read_range(
                symbol="BTCUSDT",
                start_ts=0,
                end_ts=10000 * 1000,
            )

            assert len(all_events) == 2
            assert all_events[0]["eventType"] == "RawTrade"
            assert all_events[1]["eventType"] == "BookCheckpoint"

            # Только RawTrade
            trades = reader.read_range(
                symbol="BTCUSDT",
                start_ts=0,
                end_ts=10000 * 1000,
                event_type="RawTrade",
            )
            assert len(trades) == 1

            # Только BookCheckpoint
            checkpoints = reader.read_range(
                symbol="BTCUSDT",
                start_ts=0,
                end_ts=10000 * 1000,
                event_type="BookCheckpoint",
            )
            assert len(checkpoints) == 1

            collector.close()
