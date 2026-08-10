"""
End-to-End тест полного pipeline (P2-S2-004 finalization).

Проверяет: RawTrade → EventCollector → WAL → Parquet с реальной десериализацией.
"""

import tempfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from contracts.schemas import RawTrade, TakerSide
from packages.bybit.collector import EventCollector

pytestmark = pytest.mark.contract


class TestEndToEndPipeline:
    """End-to-End тесты полного pipeline."""

    def test_raw_trade_to_parquet_full_cycle(self):
        """Полный цикл: append RawTrade → WAL → Parquet с реальной десериализацией."""
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            collector = EventCollector(directory, "BTCUSDT")

            # 1. Создаём тестовые trades
            trades = [
                RawTrade(
                    symbol="BTCUSDT",
                    trade_id="trade-1",
                    sequence=100,
                    exchange_timestamp_ms=1672304486865,
                    outer_timestamp_ms=1672304486868,
                    receive_timestamp_ms=1672304487000,
                    price_ticks=165785,
                    qty_steps=10,
                    taker_side=TakerSide.BUY,
                ),
                RawTrade(
                    symbol="BTCUSDT",
                    trade_id="trade-2",
                    sequence=101,
                    exchange_timestamp_ms=1672304486866,
                    outer_timestamp_ms=1672304486869,
                    receive_timestamp_ms=1672304487001,
                    price_ticks=165790,
                    qty_steps=20,
                    taker_side=TakerSide.SELL,
                ),
            ]

            # 2. Записываем в WAL
            for trade in trades:
                collector.append_trade(trade)

            collector.flush()
            collector.wal.roll_segment()

            # 3. Публикуем как Parquet с реальной десериализацией
            start_offset = 0
            end_offset = collector.wal.offsets.closed

            parquet_path = collector.wal.close_and_publish_segment(
                start_offset, end_offset, use_real_deserialization=True
            )

            # 4. Проверяем .parquet файл
            assert parquet_path.exists()
            assert parquet_path.suffix == ".parquet"

            table = pq.read_table(parquet_path)
            assert table.num_rows == len(trades)

            rows = table.to_pylist()

            # 5. Проверяем первую запись
            row1 = rows[0]
            assert row1["eventType"] == "RawTrade"
            assert row1["symbol"] == "BTCUSDT"
            assert row1["priceTicks"] == 165785
            assert row1["qtySteps"] == 10
            assert row1["sequence"] == 100
            assert row1["timestampUs"] == 1672304486865 * 1000
            assert row1["exchangeTimestampMs"] == 1672304486865

            # 6. Проверяем вторую запись
            row2 = rows[1]
            assert row2["eventType"] == "RawTrade"
            assert row2["priceTicks"] == 165790
            assert row2["qtySteps"] == 20
            assert row2["sequence"] == 101

    def test_empty_wal_segment_raises(self):
        """Пустой WAL сегмент → ValueError."""
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            collector = EventCollector(directory, "BTCUSDT")

            with pytest.raises(ValueError, match="пуст|без записей"):
                collector.wal.close_and_publish_segment(
                    0, 0, use_real_deserialization=True
                )

    def test_multiple_segments_published_sequentially(self):
        """Можно опубликовать несколько сегментов подряд с реальной десериализацией."""
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            collector = EventCollector(directory, "BTCUSDT", max_segment_bytes=100)

            # Первый сегмент
            trade1 = RawTrade(
                symbol="BTCUSDT",
                trade_id="segment1-trade1",
                sequence=1,
                exchange_timestamp_ms=1672304486865,
                outer_timestamp_ms=1672304486868,
                receive_timestamp_ms=1672304487000,
                price_ticks=165785,
                qty_steps=10,
                taker_side=TakerSide.BUY,
            )
            collector.append_trade(trade1)
            collector.flush()
            collector.wal.roll_segment()

            end1 = collector.wal.offsets.closed
            path1 = collector.wal.close_and_publish_segment(
                0, end1, use_real_deserialization=True
            )

            # Второй сегмент
            trade2 = RawTrade(
                symbol="BTCUSDT",
                trade_id="segment2-trade1",
                sequence=2,
                exchange_timestamp_ms=1672304486866,
                outer_timestamp_ms=1672304486869,
                receive_timestamp_ms=1672304487001,
                price_ticks=165790,
                qty_steps=20,
                taker_side=TakerSide.SELL,
            )
            collector.append_trade(trade2)
            collector.flush()
            collector.wal.roll_segment()

            end2 = collector.wal.offsets.closed
            path2 = collector.wal.close_and_publish_segment(
                end1, end2, use_real_deserialization=True
            )

            assert path1.exists()
            assert path2.exists()
            assert path1 != path2

            # Проверка содержимого
            table1 = pq.read_table(path1)
            table2 = pq.read_table(path2)

            assert table1.num_rows == 1
            assert table2.num_rows == 1

            assert table1.to_pylist()[0]["priceTicks"] == 165785
            assert table2.to_pylist()[0]["priceTicks"] == 165790
