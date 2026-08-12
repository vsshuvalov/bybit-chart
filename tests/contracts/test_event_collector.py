"""
Тесты EventCollector для записи событий в WAL (P2-S2-004).

Проверяют: append_trade → WAL, сериализацию/десериализацию, flush, конверсию в Parquet row.
"""

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from contracts.schemas import RawTrade, TakerSide
from packages.bybit.collector import (
    EventCollector,
    deserialize_trade_from_payload,
    raw_trade_to_parquet_row,
)

pytestmark = pytest.mark.contract


class TestEventCollector:
    """Тесты EventCollector."""

    def test_append_trade_writes_to_wal(self):
        """append_trade записывает в WAL и возвращает offset."""
        with tempfile.TemporaryDirectory() as td:
            collector = EventCollector(td, "BTCUSDT")

            trade = RawTrade(
                symbol="BTCUSDT",
                trade_id="test-1",
                sequence=1,
                exchange_timestamp_ms=1672304486865,
                outer_timestamp_ms=1672304486868,
                receive_timestamp_ms=1672304487000,
                price_ticks=165785,
                qty_steps=1,
                taker_side=TakerSide.BUY,
            )

            offset = collector.append_trade(trade)

            assert offset >= 0
            assert collector.wal.accepted_offset > 0

    def test_multiple_trades_sequential_offsets(self):
        """Множественные trades получают последовательные offsets."""
        with tempfile.TemporaryDirectory() as td:
            collector = EventCollector(td, "BTCUSDT")

            trade1 = RawTrade(
                symbol="BTCUSDT",
                trade_id="test-1",
                sequence=1,
                exchange_timestamp_ms=1672304486865,
                outer_timestamp_ms=1672304486868,
                receive_timestamp_ms=1672304487000,
                price_ticks=165785,
                qty_steps=1,
                taker_side=TakerSide.BUY,
            )

            trade2 = RawTrade(
                symbol="BTCUSDT",
                trade_id="test-2",
                sequence=2,
                exchange_timestamp_ms=1672304486866,
                outer_timestamp_ms=1672304486869,
                receive_timestamp_ms=1672304487001,
                price_ticks=165790,
                qty_steps=2,
                taker_side=TakerSide.SELL,
            )

            offset1 = collector.append_trade(trade1)
            offset2 = collector.append_trade(trade2)

            assert offset2 > offset1

    def test_flush_commits_pending_records(self):
        """flush продвигает durable_offset."""
        with tempfile.TemporaryDirectory() as td:
            collector = EventCollector(td, "BTCUSDT")

            trade = RawTrade(
                symbol="BTCUSDT",
                trade_id="test-1",
                sequence=1,
                exchange_timestamp_ms=1672304486865,
                outer_timestamp_ms=1672304486868,
                receive_timestamp_ms=1672304487000,
                price_ticks=165785,
                qty_steps=1,
                taker_side=TakerSide.BUY,
            )

            collector.append_trade(trade)
            durable_before = collector.wal.durable_offset

            collector.flush()
            durable_after = collector.wal.durable_offset

            assert durable_after > durable_before

    def test_close_finalizes_wal(self):
        """close закрывает WAL partition."""
        with tempfile.TemporaryDirectory() as td:
            collector = EventCollector(td, "BTCUSDT")

            trade = RawTrade(
                symbol="BTCUSDT",
                trade_id="test-1",
                sequence=1,
                exchange_timestamp_ms=1672304486865,
                outer_timestamp_ms=1672304486868,
                receive_timestamp_ms=1672304487000,
                price_ticks=165785,
                qty_steps=1,
                taker_side=TakerSide.BUY,
            )

            collector.append_trade(trade)
            collector.close()

            # После close WAL закрыт
            assert collector.wal._closed


class TestDeserializeTradeFromPayload:
    """Тесты десериализации Frame.payload → RawTrade."""

    def test_round_trip_serialization(self):
        """Сериализация → десериализация сохраняет данные."""
        with tempfile.TemporaryDirectory() as td:
            collector = EventCollector(td, "BTCUSDT")

            original = RawTrade(
                symbol="BTCUSDT",
                trade_id="test-1",
                sequence=1,
                exchange_timestamp_ms=1672304486865,
                outer_timestamp_ms=1672304486868,
                receive_timestamp_ms=1672304487000,
                price_ticks=165785,
                qty_steps=1,
                taker_side=TakerSide.BUY,
            )

            payload = collector._serialize_trade(original)
            deserialized = deserialize_trade_from_payload(payload)

            assert deserialized.trade_id == original.trade_id
            assert deserialized.price_ticks == original.price_ticks
            assert deserialized.qty_steps == original.qty_steps
            assert deserialized.taker_side == original.taker_side

    def test_invalid_payload_raises(self):
        """Некорректный payload → ValueError."""
        with pytest.raises(ValueError, match="Не удалось десериализовать"):
            deserialize_trade_from_payload(b"invalid json")


class TestRawTradeToParquetRow:
    """Тесты конверсии RawTrade → Parquet row."""

    def test_conversion_maps_fields_correctly(self):
        """Поля RawTrade корректно маппятся в Parquet row."""
        trade = RawTrade(
            symbol="BTCUSDT",
            trade_id="test-1",
            sequence=123,
            exchange_timestamp_ms=1672304486865,
            outer_timestamp_ms=1672304486868,
            receive_timestamp_ms=1672304487000,
            price_ticks=165785,
            qty_steps=1,
            taker_side=TakerSide.BUY,
        )

        row = raw_trade_to_parquet_row(trade)

        assert row["timestampUs"] == 1672304486865 * 1000
        assert row["eventType"] == "RawTrade"
        assert row["symbol"] == "BTCUSDT"
        assert row["priceTicks"] == 165785
        assert row["qtySteps"] == 1
        assert row["sequence"] == 123
        assert row["exchangeTimestampMs"] == 1672304486865
        assert row["outerTimestampMs"] == 1672304486868
        assert row["receiveTimestampMs"] == 1672304487000

    def test_book_checkpoint_fields_are_zero(self):
        """BookCheckpoint-специфичные поля = 0 для RawTrade."""
        trade = RawTrade(
            symbol="BTCUSDT",
            trade_id="test-1",
            sequence=1,
            exchange_timestamp_ms=1672304486865,
            outer_timestamp_ms=1672304486868,
            receive_timestamp_ms=1672304487000,
            price_ticks=165785,
            qty_steps=1,
            taker_side=TakerSide.BUY,
        )

        row = raw_trade_to_parquet_row(trade)

        assert row["depth"] == 0
        assert row["updateId"] == 0
        assert row["levelCount"] == 0
        assert row["coverageBoundaryTicks"] == 0
        assert row["coverageBps"] == Decimal("0.0000")
        assert row["isFeedRangeComplete"] is False


class TestEventCollectorFencing:
    """Тесты интеграции WriterLease в EventCollector (ADR-013)."""

    def test_fencing_enabled_by_default(self, tmp_path):
        """По умолчанию fencing включён, lease захватывается при инициализации."""
        collector = EventCollector(tmp_path, "BTCUSDT")
        try:
            assert collector._lease is not None
            assert collector._lease.is_active
            assert collector._lease.epoch == 1
        finally:
            collector.close()

    def test_fencing_disabled(self, tmp_path):
        """use_fencing=False — lease не захватывается."""
        collector = EventCollector(tmp_path, "BTCUSDT", use_fencing=False)
        try:
            assert collector._lease is None
        finally:
            collector.close()

    def test_second_collector_fails_while_first_active(self, tmp_path):
        """Второй коллектор не может стартовать пока первый держит lease."""
        from packages.storage.fencing import LeaseAcquisitionError
        collector1 = EventCollector(tmp_path, "BTCUSDT")
        try:
            with pytest.raises(RuntimeError, match="Cannot start collector"):
                EventCollector(tmp_path, "BTCUSDT")
        finally:
            collector1.close()

    def test_second_collector_starts_after_first_closed(self, tmp_path):
        """После close() первого — второй стартует с epoch+1."""
        collector1 = EventCollector(tmp_path, "BTCUSDT")
        collector1.close()

        collector2 = EventCollector(tmp_path, "BTCUSDT")
        try:
            assert collector2._lease.epoch == 2
        finally:
            collector2.close()

    def test_close_releases_lease(self, tmp_path):
        """close() освобождает lease."""
        collector = EventCollector(tmp_path, "BTCUSDT")
        collector.close()
        assert not collector._lease.is_active

    def test_epoch_violation_raises_on_append(self, tmp_path):
        """append_trade бросает EpochViolationError при cutover."""
        from packages.storage.fencing import EpochViolationError
        import os

        trade = RawTrade(
            symbol="BTCUSDT",
            trade_id="t1",
            sequence=1,
            exchange_timestamp_ms=1000,
            outer_timestamp_ms=1000,
            receive_timestamp_ms=1000,
            price_ticks=500000,
            qty_steps=1,
            taker_side=TakerSide.BUY,
        )

        collector = EventCollector(tmp_path, "BTCUSDT")
        # Симулируем cutover: принудительно сдвигаем epoch file
        (tmp_path / ".writer.epoch").write_text("99")
        try:
            with pytest.raises(EpochViolationError):
                collector.append_trade(trade)
        finally:
            # Восстановить epoch чтобы close не упал
            (tmp_path / ".writer.epoch").write_text("1")
            collector.close()
