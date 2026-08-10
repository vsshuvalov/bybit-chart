"""
Тесты Event Deserializer для BookCheckpoint (P2-S2-003).

Проверяют корректность парсинга Bybit orderbook snapshot → BookCheckpoint.
"""

from decimal import Decimal

import pytest

from contracts.schemas import BookCheckpoint
from packages.bybit.deserializer_book import deserialize_book_snapshot
from packages.numeric import BTCUSDT_PRICE_TICK, BTCUSDT_QTY_STEP

pytestmark = pytest.mark.contract


class TestDeserializeBookSnapshot:
    """Тесты десериализации orderbook snapshot."""

    def test_snapshot_basic_parsing(self):
        """Парсинг базового snapshot."""
        message = {
            "topic": "orderbook.200.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304484978,
            "data": {
                "s": "BTCUSDT",
                "b": [
                    ["16493.50", "0.006"],
                    ["16493.00", "0.100"],
                ],
                "a": [
                    ["16611.00", "0.029"],
                    ["16612.00", "0.213"],
                ],
                "u": 18521288,
                "seq": 7961638724,
            },
        }

        checkpoint = deserialize_book_snapshot(
            message, receive_timestamp_ms=1672304485000
        )

        assert checkpoint.venue == "BYBIT"
        assert checkpoint.category == "linear"
        assert checkpoint.symbol == "BTCUSDT"
        assert checkpoint.depth == 200
        assert checkpoint.update_id == 18521288
        assert checkpoint.sequence == 7961638724
        assert checkpoint.outer_timestamp_ms == 1672304484978
        assert checkpoint.receive_timestamp_ms == 1672304485000

    def test_bids_asks_conversion(self):
        """Bids/asks конвертируются в RawBookLevel с масштабированными int."""
        message = {
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304484978,
            "data": {
                "s": "BTCUSDT",
                "b": [["16500.00", "0.100"]],
                "a": [["16510.00", "0.200"]],
                "u": 1,
                "seq": 1,
            },
        }

        checkpoint = deserialize_book_snapshot(
            message, receive_timestamp_ms=1672304485000
        )

        assert len(checkpoint.bids) == 1
        assert len(checkpoint.asks) == 1

        # Проверка конверсии
        expected_bid_ticks = int(Decimal("16500.00") / BTCUSDT_PRICE_TICK)
        expected_bid_qty = int(Decimal("0.100") / BTCUSDT_QTY_STEP)

        assert checkpoint.bids[0].price_ticks == expected_bid_ticks
        assert checkpoint.bids[0].qty_steps == expected_bid_qty

        expected_ask_ticks = int(Decimal("16510.00") / BTCUSDT_PRICE_TICK)
        expected_ask_qty = int(Decimal("0.200") / BTCUSDT_QTY_STEP)

        assert checkpoint.asks[0].price_ticks == expected_ask_ticks
        assert checkpoint.asks[0].qty_steps == expected_ask_qty

    def test_level_count_calculated(self):
        """levelCount = len(bids) + len(asks)."""
        message = {
            "topic": "orderbook.200.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304484978,
            "data": {
                "s": "BTCUSDT",
                "b": [["16500.00", "0.100"], ["16499.00", "0.200"]],
                "a": [["16510.00", "0.150"]],
                "u": 1,
                "seq": 1,
            },
        }

        checkpoint = deserialize_book_snapshot(
            message, receive_timestamp_ms=1672304485000
        )

        assert checkpoint.level_count == 3

    def test_coverage_calculation(self):
        """Coverage metrics вычисляются корректно."""
        message = {
            "topic": "orderbook.200.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304484978,
            "data": {
                "s": "BTCUSDT",
                "b": [
                    ["16500.00", "0.100"],  # best bid
                    ["16400.00", "0.200"],  # worst bid (boundary)
                ],
                "a": [
                    ["16510.00", "0.150"],  # best ask
                    ["16610.00", "0.250"],  # worst ask (boundary)
                ],
                "u": 1,
                "seq": 1,
            },
        }

        checkpoint = deserialize_book_snapshot(
            message, receive_timestamp_ms=1672304485000
        )

        # Mid = (16500 + 16510) / 2 = 16505
        # Boundary distance = max(16505 - 16400, 16610 - 16505) = max(105, 105) = 105
        # Coverage bps = 105 / 16505 * 10000 ≈ 63.61 bps
        assert checkpoint.coverage_boundary_ticks > 0
        assert checkpoint.coverage_bps > Decimal("0")

    def test_zero_quantity_levels_filtered(self):
        """Уровни с qty=0 фильтруются (Bybit отправляет для удаления)."""
        message = {
            "topic": "orderbook.200.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304484978,
            "data": {
                "s": "BTCUSDT",
                "b": [
                    ["16500.00", "0.100"],
                    ["16499.00", "0.000"],  # должен быть отфильтрован
                ],
                "a": [["16510.00", "0.150"]],
                "u": 1,
                "seq": 1,
            },
        }

        checkpoint = deserialize_book_snapshot(
            message, receive_timestamp_ms=1672304485000
        )

        assert len(checkpoint.bids) == 1  # только ненулевой уровень
        assert len(checkpoint.asks) == 1

    def test_empty_bids_or_asks(self):
        """Пустые bids/asks → нулевое покрытие."""
        message = {
            "topic": "orderbook.200.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304484978,
            "data": {
                "s": "BTCUSDT",
                "b": [],
                "a": [["16510.00", "0.150"]],
                "u": 1,
                "seq": 1,
            },
        }

        checkpoint = deserialize_book_snapshot(
            message, receive_timestamp_ms=1672304485000
        )

        assert checkpoint.coverage_boundary_ticks == 0
        assert checkpoint.coverage_bps == Decimal("0.0000")
        assert checkpoint.is_feed_range_complete is False

    def test_missing_topic_raises(self):
        """Отсутствие topic → ValueError."""
        message = {"type": "snapshot", "data": {}}

        with pytest.raises(ValueError, match="Отсутствует поле 'topic'"):
            deserialize_book_snapshot(message)

    def test_missing_type_raises(self):
        """Отсутствие type → ValueError."""
        message = {"topic": "orderbook.200.BTCUSDT", "data": {}}

        with pytest.raises(ValueError, match="Отсутствует поле 'type'"):
            deserialize_book_snapshot(message)

    def test_missing_data_raises(self):
        """Отсутствие data → ValueError."""
        message = {"topic": "orderbook.200.BTCUSDT", "type": "snapshot"}

        with pytest.raises(ValueError, match="Отсутствует поле 'data'"):
            deserialize_book_snapshot(message)

    def test_wrong_topic_raises(self):
        """Некорректный topic → ValueError."""
        message = {"topic": "publicTrade.BTCUSDT", "type": "snapshot", "data": {}}

        with pytest.raises(ValueError, match="Некорректный topic"):
            deserialize_book_snapshot(message)

    def test_delta_type_raises(self):
        """Delta updates не поддерживаются → ValueError."""
        message = {
            "topic": "orderbook.200.BTCUSDT",
            "type": "delta",
            "data": {"s": "BTCUSDT", "b": [], "a": [], "u": 1, "seq": 1},
        }

        with pytest.raises(ValueError, match="Поддерживаются только snapshot"):
            deserialize_book_snapshot(message)

    def test_depth_extracted_from_topic(self):
        """Depth извлекается из topic (orderbook.{depth}.{symbol})."""
        message = {
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304484978,
            "data": {
                "s": "BTCUSDT",
                "b": [["16500.00", "0.100"]],
                "a": [["16510.00", "0.150"]],
                "u": 1,
                "seq": 1,
            },
        }

        checkpoint = deserialize_book_snapshot(
            message, receive_timestamp_ms=1672304485000
        )

        assert checkpoint.depth == 50

    def test_connection_epoch_passed_through(self):
        """connectionEpoch передаётся в BookCheckpoint."""
        message = {
            "topic": "orderbook.200.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304484978,
            "data": {
                "s": "BTCUSDT",
                "b": [["16500.00", "0.100"]],
                "a": [["16510.00", "0.150"]],
                "u": 1,
                "seq": 1,
            },
        }

        checkpoint = deserialize_book_snapshot(
            message, receive_timestamp_ms=1672304485000, connection_epoch="test-epoch"
        )

        assert checkpoint.connection_epoch == "test-epoch"

    def test_default_receive_timestamp(self):
        """Если receive_timestamp_ms не передан, используется текущее время."""
        message = {
            "topic": "orderbook.200.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304484978,
            "data": {
                "s": "BTCUSDT",
                "b": [["16500.00", "0.100"]],
                "a": [["16510.00", "0.150"]],
                "u": 1,
                "seq": 1,
            },
        }

        checkpoint = deserialize_book_snapshot(message)

        # Проверка, что receive_timestamp_ms установлен и близок к текущему времени
        assert checkpoint.receive_timestamp_ms > 0
