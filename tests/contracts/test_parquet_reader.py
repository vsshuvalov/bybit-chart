"""
Тесты ParquetReader для чтения Parquet сегментов (P3-S3-001).

Проверяют: чтение через manifest, фильтрация по timestampUs, multiple segments.
"""

import tempfile
from pathlib import Path

import pytest

from contracts.schemas import RawTrade, TakerSide
from packages.bybit.collector import EventCollector
from packages.storage.parquet_reader import ParquetReader

pytestmark = pytest.mark.contract


class TestParquetReader:
    """Тесты ParquetReader."""

    def test_read_range_single_segment(self):
        """Чтение событий из одного сегмента с фильтрацией по времени."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            # Создаём тестовые данные
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            trades = [
                RawTrade(
                    symbol="BTCUSDT",
                    trade_id="trade-1",
                    sequence=1,
                    exchange_timestamp_ms=1000,  # 1000000 µs
                    outer_timestamp_ms=1001,
                    receive_timestamp_ms=1002,
                    price_ticks=100,
                    qty_steps=10,
                    taker_side=TakerSide.BUY,
                ),
                RawTrade(
                    symbol="BTCUSDT",
                    trade_id="trade-2",
                    sequence=2,
                    exchange_timestamp_ms=2000,  # 2000000 µs
                    outer_timestamp_ms=2001,
                    receive_timestamp_ms=2002,
                    price_ticks=200,
                    qty_steps=20,
                    taker_side=TakerSide.SELL,
                ),
                RawTrade(
                    symbol="BTCUSDT",
                    trade_id="trade-3",
                    sequence=3,
                    exchange_timestamp_ms=3000,  # 3000000 µs
                    outer_timestamp_ms=3001,
                    receive_timestamp_ms=3002,
                    price_ticks=300,
                    qty_steps=30,
                    taker_side=TakerSide.BUY,
                ),
            ]

            for trade in trades:
                collector.append_trade(trade)

            collector.flush()
            collector.wal.roll_segment()

            # Публикуем Parquet
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            # Читаем через ParquetReader
            reader = ParquetReader(base_dir)

            # Диапазон захватывает trade-1 и trade-2 (1-2.5ms)
            events = reader.read_range(
                symbol="BTCUSDT",
                start_ts=1000 * 1000,  # 1ms в µs
                end_ts=2500 * 1000,     # 2.5ms в µs
            )

            assert len(events) == 2
            assert events[0]["timestampUs"] == 1000 * 1000
            assert events[0]["priceTicks"] == 100
            assert events[1]["timestampUs"] == 2000 * 1000
            assert events[1]["priceTicks"] == 200

    def test_read_range_filters_by_event_type(self):
        """Фильтрация по eventType работает."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            trade = RawTrade(
                symbol="BTCUSDT",
                trade_id="trade-1",
                sequence=1,
                exchange_timestamp_ms=1000,
                outer_timestamp_ms=1001,
                receive_timestamp_ms=1002,
                price_ticks=100,
                qty_steps=10,
                taker_side=TakerSide.BUY,
            )

            collector.append_trade(trade)
            collector.flush()
            collector.wal.roll_segment()
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            reader = ParquetReader(base_dir)

            # Фильтр по RawTrade
            events = reader.read_range(
                symbol="BTCUSDT",
                start_ts=0,
                end_ts=10000 * 1000,
                event_type="RawTrade",
            )
            assert len(events) == 1

            # Фильтр по BookCheckpoint (нет таких событий)
            events = reader.read_range(
                symbol="BTCUSDT",
                start_ts=0,
                end_ts=10000 * 1000,
                event_type="BookCheckpoint",
            )
            assert len(events) == 0

    def test_read_range_with_limit(self):
        """Limit ограничивает количество возвращаемых событий."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            # Создаём 5 trades
            for i in range(5):
                trade = RawTrade(
                    symbol="BTCUSDT",
                    trade_id=f"trade-{i}",
                    sequence=i,
                    exchange_timestamp_ms=1000 + i * 100,
                    outer_timestamp_ms=1001 + i * 100,
                    receive_timestamp_ms=1002 + i * 100,
                    price_ticks=100 + i * 10,
                    qty_steps=10,
                    taker_side=TakerSide.BUY,
                )
                collector.append_trade(trade)

            collector.flush()
            collector.wal.roll_segment()
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            reader = ParquetReader(base_dir)

            # Limit = 3
            events = reader.read_range(
                symbol="BTCUSDT",
                start_ts=0,
                end_ts=10000 * 1000,
                limit=3,
            )

            assert len(events) == 3

    def test_read_range_multiple_segments(self):
        """Чтение из нескольких сегментов с merge и sort."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT", max_segment_bytes=100)

            # Сегмент 1
            trade1 = RawTrade(
                symbol="BTCUSDT",
                trade_id="seg1-trade1",
                sequence=1,
                exchange_timestamp_ms=1000,
                outer_timestamp_ms=1001,
                receive_timestamp_ms=1002,
                price_ticks=100,
                qty_steps=10,
                taker_side=TakerSide.BUY,
            )
            collector.append_trade(trade1)
            collector.flush()
            collector.wal.roll_segment()

            end1 = collector.wal.offsets.closed
            collector.wal.close_and_publish_segment(
                0, end1, use_real_deserialization=True
            )

            # Сегмент 2
            trade2 = RawTrade(
                symbol="BTCUSDT",
                trade_id="seg2-trade1",
                sequence=2,
                exchange_timestamp_ms=2000,
                outer_timestamp_ms=2001,
                receive_timestamp_ms=2002,
                price_ticks=200,
                qty_steps=20,
                taker_side=TakerSide.SELL,
            )
            collector.append_trade(trade2)
            collector.flush()
            collector.wal.roll_segment()

            collector.wal.close_and_publish_segment(
                end1, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            # Читаем из обоих сегментов
            reader = ParquetReader(base_dir)
            events = reader.read_range(
                symbol="BTCUSDT",
                start_ts=0,
                end_ts=10000 * 1000,
            )

            assert len(events) == 2
            # Проверка сортировки
            assert events[0]["timestampUs"] < events[1]["timestampUs"]
            assert events[0]["priceTicks"] == 100
            assert events[1]["priceTicks"] == 200

    def test_read_range_empty_result(self):
        """Диапазон без событий возвращает пустой список."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")

            trade = RawTrade(
                symbol="BTCUSDT",
                trade_id="trade-1",
                sequence=1,
                exchange_timestamp_ms=1000,
                outer_timestamp_ms=1001,
                receive_timestamp_ms=1002,
                price_ticks=100,
                qty_steps=10,
                taker_side=TakerSide.BUY,
            )
            collector.append_trade(trade)
            collector.flush()
            collector.wal.roll_segment()
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            reader = ParquetReader(base_dir)

            # Диапазон не пересекается с данными
            events = reader.read_range(
                symbol="BTCUSDT",
                start_ts=5000 * 1000,
                end_ts=6000 * 1000,
            )

            assert len(events) == 0

    def test_read_range_invalid_params_raises(self):
        """Некорректные параметры → ValueError."""
        with tempfile.TemporaryDirectory() as td:
            reader = ParquetReader(td)

            with pytest.raises(ValueError, match="start_ts.*должен быть < end_ts"):
                reader.read_range(
                    symbol="BTCUSDT",
                    start_ts=2000,
                    end_ts=1000,
                )

    def test_read_range_missing_partition_raises(self):
        """Отсутствующая partition → FileNotFoundError."""
        with tempfile.TemporaryDirectory() as td:
            reader = ParquetReader(td)

            with pytest.raises(FileNotFoundError, match="Partition не существует"):
                reader.read_range(
                    symbol="NONEXISTENT",
                    start_ts=0,
                    end_ts=1000,
                )

    def test_list_symbols(self):
        """list_symbols возвращает доступные symbols."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            # Создаём две партиции с реальными данными
            # BTCUSDT
            collector1 = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")
            trade1 = RawTrade(
                symbol="BTCUSDT",
                trade_id="t1",
                sequence=1,
                exchange_timestamp_ms=1000,
                outer_timestamp_ms=1001,
                receive_timestamp_ms=1002,
                price_ticks=100,
                qty_steps=10,
                taker_side=TakerSide.BUY,
            )
            collector1.append_trade(trade1)
            collector1.flush()
            collector1.wal.roll_segment()
            collector1.wal.close_and_publish_segment(
                0, collector1.wal.offsets.closed, use_real_deserialization=True
            )
            collector1.close()

            # ETHUSDT
            collector2 = EventCollector(base_dir / "ETHUSDT", "ETHUSDT")
            trade2 = RawTrade(
                symbol="ETHUSDT",
                trade_id="t2",
                sequence=1,
                exchange_timestamp_ms=1000,
                outer_timestamp_ms=1001,
                receive_timestamp_ms=1002,
                price_ticks=200,
                qty_steps=20,
                taker_side=TakerSide.SELL,
            )
            collector2.append_trade(trade2)
            collector2.flush()
            collector2.wal.roll_segment()
            collector2.wal.close_and_publish_segment(
                0, collector2.wal.offsets.closed, use_real_deserialization=True
            )
            collector2.close()

            reader = ParquetReader(base_dir)
            symbols = reader.list_symbols()

            assert symbols == ["BTCUSDT", "ETHUSDT"]

    def test_list_symbols_empty_dir(self):
        """list_symbols на пустом каталоге возвращает []."""
        with tempfile.TemporaryDirectory() as td:
            reader = ParquetReader(td)
            symbols = reader.list_symbols()

            assert symbols == []
