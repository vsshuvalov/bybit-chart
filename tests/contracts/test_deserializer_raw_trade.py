"""
Тесты Event Deserializer для RawTrade (P2-S2-002).

Проверяют корректность парсинга Bybit JSON → RawTrade.
"""

from decimal import Decimal

import pytest

from contracts.schemas import RawTrade, TakerSide
from packages.bybit.deserializer import deserialize_raw_trade
from packages.numeric import BTCUSDT_PRICE_TICK, BTCUSDT_QTY_STEP

pytestmark = pytest.mark.contract


class TestDeserializeRawTrade:
    """Тесты десериализации publicTrade."""

    def test_single_trade_buy(self):
        """Парсинг одной Buy-сделки."""
        message = {
            "topic": "publicTrade.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304486868,
            "data": [
                {
                    "T": 1672304486865,
                    "s": "BTCUSDT",
                    "S": "Buy",
                    "v": "0.001",
                    "p": "16578.50",
                    "L": "PlusTick",
                    "i": "20f43950-d8dd-5b31-9112-a178eb6023af",
                    "BT": False,
                }
            ],
        }

        trades = deserialize_raw_trade(message, receive_timestamp_ms=1672304487000)

        assert len(trades) == 1
        trade = trades[0]

        assert trade.venue == "BYBIT"
        assert trade.category == "linear"
        assert trade.symbol == "BTCUSDT"
        assert trade.trade_id == "20f43950-d8dd-5b31-9112-a178eb6023af"
        assert trade.exchange_timestamp_ms == 1672304486865
        assert trade.outer_timestamp_ms == 1672304486868
        assert trade.receive_timestamp_ms == 1672304487000
        assert trade.taker_side == TakerSide.BUY
        assert trade.is_block_trade is False
        assert trade.is_rpi_trade is False

    def test_single_trade_sell(self):
        """Парсинг одной Sell-сделки."""
        message = {
            "topic": "publicTrade.BTCUSDT",
            "ts": 1672304486868,
            "data": [
                {
                    "T": 1672304486865,
                    "s": "BTCUSDT",
                    "S": "Sell",
                    "v": "0.100",
                    "p": "16580.00",
                    "i": "trade-123",
                    "BT": False,
                }
            ],
        }

        trades = deserialize_raw_trade(message, receive_timestamp_ms=1672304487000)

        assert len(trades) == 1
        assert trades[0].taker_side == TakerSide.SELL

    def test_price_qty_conversion_to_ticks(self):
        """price/qty конвертируются в масштабированные целые."""
        message = {
            "topic": "publicTrade.BTCUSDT",
            "ts": 1672304486868,
            "data": [
                {
                    "T": 1672304486865,
                    "s": "BTCUSDT",
                    "S": "Buy",
                    "v": "0.001",
                    "p": "16578.50",
                    "i": "trade-1",
                }
            ],
        }

        trades = deserialize_raw_trade(message, receive_timestamp_ms=1672304487000)
        trade = trades[0]

        # Проверка конверсии
        expected_price_ticks = int(Decimal("16578.50") / BTCUSDT_PRICE_TICK)
        expected_qty_steps = int(Decimal("0.001") / BTCUSDT_QTY_STEP)

        assert trade.price_ticks == expected_price_ticks
        assert trade.qty_steps == expected_qty_steps

    def test_multiple_trades_in_message(self):
        """message.data может содержать несколько сделок."""
        message = {
            "topic": "publicTrade.BTCUSDT",
            "ts": 1672304486868,
            "data": [
                {
                    "T": 1672304486865,
                    "s": "BTCUSDT",
                    "S": "Buy",
                    "v": "0.001",
                    "p": "16578.50",
                    "i": "trade-1",
                },
                {
                    "T": 1672304486866,
                    "s": "BTCUSDT",
                    "S": "Sell",
                    "v": "0.002",
                    "p": "16579.00",
                    "i": "trade-2",
                },
            ],
        }

        trades = deserialize_raw_trade(message, receive_timestamp_ms=1672304487000)

        assert len(trades) == 2
        assert trades[0].trade_id == "trade-1"
        assert trades[1].trade_id == "trade-2"
        assert trades[0].taker_side == TakerSide.BUY
        assert trades[1].taker_side == TakerSide.SELL

    def test_block_trade_flag(self):
        """BT=true → isBlockTrade=true."""
        message = {
            "topic": "publicTrade.BTCUSDT",
            "ts": 1672304486868,
            "data": [
                {
                    "T": 1672304486865,
                    "s": "BTCUSDT",
                    "S": "Buy",
                    "v": "10.000",
                    "p": "16578.50",
                    "i": "block-trade-1",
                    "BT": True,
                }
            ],
        }

        trades = deserialize_raw_trade(message, receive_timestamp_ms=1672304487000)

        assert trades[0].is_block_trade is True

    def test_rpi_trade_flag(self):
        """RPI=true → isRpiTrade=true."""
        message = {
            "topic": "publicTrade.BTCUSDT",
            "ts": 1672304486868,
            "data": [
                {
                    "T": 1672304486865,
                    "s": "BTCUSDT",
                    "S": "Buy",
                    "v": "0.001",
                    "p": "16578.50",
                    "i": "rpi-trade-1",
                    "RPI": True,
                }
            ],
        }

        trades = deserialize_raw_trade(message, receive_timestamp_ms=1672304487000)

        assert trades[0].is_rpi_trade is True

    def test_missing_topic_raises(self):
        """Отсутствие topic → ValueError."""
        message = {"data": []}

        with pytest.raises(ValueError, match="Отсутствует поле 'topic'"):
            deserialize_raw_trade(message)

    def test_missing_data_raises(self):
        """Отсутствие data → ValueError."""
        message = {"topic": "publicTrade.BTCUSDT"}

        with pytest.raises(ValueError, match="Отсутствует поле 'data'"):
            deserialize_raw_trade(message)

    def test_wrong_topic_raises(self):
        """Некорректный topic → ValueError."""
        message = {"topic": "orderbook.200.BTCUSDT", "data": []}

        with pytest.raises(ValueError, match="Некорректный topic"):
            deserialize_raw_trade(message)

    def test_invalid_side_raises(self):
        """Некорректный takerSide → ValueError."""
        message = {
            "topic": "publicTrade.BTCUSDT",
            "ts": 1672304486868,
            "data": [
                {
                    "T": 1672304486865,
                    "s": "BTCUSDT",
                    "S": "Unknown",
                    "v": "0.001",
                    "p": "16578.50",
                    "i": "trade-1",
                }
            ],
        }

        with pytest.raises(ValueError, match="Некорректный takerSide"):
            deserialize_raw_trade(message, receive_timestamp_ms=1672304487000)

    def test_unique_key_generation(self):
        """RawTrade.unique_key() возвращает детерминированный ключ."""
        message = {
            "topic": "publicTrade.BTCUSDT",
            "ts": 1672304486868,
            "data": [
                {
                    "T": 1672304486865,
                    "s": "BTCUSDT",
                    "S": "Buy",
                    "v": "0.001",
                    "p": "16578.50",
                    "i": "20f43950-d8dd-5b31-9112-a178eb6023af",
                }
            ],
        }

        trades = deserialize_raw_trade(message, receive_timestamp_ms=1672304487000)
        key = trades[0].unique_key()

        assert key == "BYBIT:linear:BTCUSDT:20f43950-d8dd-5b31-9112-a178eb6023af"

    def test_default_receive_timestamp(self):
        """Если receive_timestamp_ms не передан, используется текущее время."""
        message = {
            "topic": "publicTrade.BTCUSDT",
            "ts": 1672304486868,
            "data": [
                {
                    "T": 1672304486865,
                    "s": "BTCUSDT",
                    "S": "Buy",
                    "v": "0.001",
                    "p": "16578.50",
                    "i": "trade-1",
                }
            ],
        }

        trades = deserialize_raw_trade(message)

        # Проверка, что receive_timestamp_ms установлен и близок к текущему времени
        assert trades[0].receive_timestamp_ms > 0
