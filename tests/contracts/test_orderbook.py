"""
Тесты Order Book Reconstruction (Roadmap §8.2).

Проверяют: OrderBookState, snapshot application, imbalance calculation.
"""

import pytest

from packages.analytics.orderbook import (
    OrderBookLevel,
    OrderBookSnapshot,
    OrderBookState,
    reconstruct_from_checkpoint,
)

pytestmark = pytest.mark.contract


class TestOrderBookState:
    """Тесты OrderBookState."""

    def test_initial_state(self):
        """Начальное состояние пустое."""
        ob = OrderBookState("BTCUSDT")

        assert ob.symbol == "BTCUSDT"
        assert ob.bids == []
        assert ob.asks == []
        assert ob.timestamp_us == 0
        assert ob.update_id == 0

    def test_apply_snapshot(self):
        """apply_snapshot() обновляет bids/asks."""
        ob = OrderBookState("BTCUSDT")

        snapshot = OrderBookSnapshot(
            timestamp_us=1000,
            bids=[
                OrderBookLevel(price_ticks=10000, qty_steps=100),
                OrderBookLevel(price_ticks=9999, qty_steps=200),
            ],
            asks=[
                OrderBookLevel(price_ticks=10001, qty_steps=150),
                OrderBookLevel(price_ticks=10002, qty_steps=250),
            ],
            depth=2,
            update_id=123,
        )

        ob.apply_snapshot(snapshot)

        assert len(ob.bids) == 2
        assert len(ob.asks) == 2
        assert ob.timestamp_us == 1000
        assert ob.update_id == 123
        assert ob.depth == 2

    def test_get_best_bid(self):
        """get_best_bid() возвращает первый bid."""
        ob = OrderBookState("BTCUSDT")

        snapshot = OrderBookSnapshot(
            timestamp_us=1000,
            bids=[
                OrderBookLevel(price_ticks=10000, qty_steps=100),
                OrderBookLevel(price_ticks=9999, qty_steps=200),
            ],
            asks=[],
            depth=2,
            update_id=123,
        )

        ob.apply_snapshot(snapshot)

        best_bid = ob.get_best_bid()
        assert best_bid is not None
        assert best_bid.price_ticks == 10000
        assert best_bid.qty_steps == 100

    def test_get_best_ask(self):
        """get_best_ask() возвращает первый ask."""
        ob = OrderBookState("BTCUSDT")

        snapshot = OrderBookSnapshot(
            timestamp_us=1000,
            bids=[],
            asks=[
                OrderBookLevel(price_ticks=10001, qty_steps=150),
                OrderBookLevel(price_ticks=10002, qty_steps=250),
            ],
            depth=2,
            update_id=123,
        )

        ob.apply_snapshot(snapshot)

        best_ask = ob.get_best_ask()
        assert best_ask is not None
        assert best_ask.price_ticks == 10001
        assert best_ask.qty_steps == 150

    def test_get_spread_ticks(self):
        """get_spread_ticks() рассчитывает spread."""
        ob = OrderBookState("BTCUSDT")

        snapshot = OrderBookSnapshot(
            timestamp_us=1000,
            bids=[OrderBookLevel(price_ticks=10000, qty_steps=100)],
            asks=[OrderBookLevel(price_ticks=10005, qty_steps=150)],
            depth=1,
            update_id=123,
        )

        ob.apply_snapshot(snapshot)

        spread = ob.get_spread_ticks()
        assert spread == 5  # 10005 - 10000

    def test_get_spread_ticks_empty(self):
        """get_spread_ticks() возвращает None для пустого orderbook."""
        ob = OrderBookState("BTCUSDT")
        assert ob.get_spread_ticks() is None

    def test_get_depth_levels(self):
        """get_depth_levels() возвращает top N levels."""
        ob = OrderBookState("BTCUSDT")

        snapshot = OrderBookSnapshot(
            timestamp_us=1000,
            bids=[
                OrderBookLevel(price_ticks=10000, qty_steps=100),
                OrderBookLevel(price_ticks=9999, qty_steps=200),
                OrderBookLevel(price_ticks=9998, qty_steps=300),
            ],
            asks=[
                OrderBookLevel(price_ticks=10001, qty_steps=150),
                OrderBookLevel(price_ticks=10002, qty_steps=250),
            ],
            depth=3,
            update_id=123,
        )

        ob.apply_snapshot(snapshot)

        depth = ob.get_depth_levels(num_levels=2)

        assert len(depth["bids"]) == 2
        assert len(depth["asks"]) == 2
        assert depth["spread_ticks"] == 1
        assert depth["timestamp_us"] == 1000

    def test_calculate_imbalance_balanced(self):
        """calculate_imbalance() для сбалансированного orderbook."""
        ob = OrderBookState("BTCUSDT")

        snapshot = OrderBookSnapshot(
            timestamp_us=1000,
            bids=[OrderBookLevel(price_ticks=10000, qty_steps=100)],
            asks=[OrderBookLevel(price_ticks=10001, qty_steps=100)],
            depth=1,
            update_id=123,
        )

        ob.apply_snapshot(snapshot)

        imbalance = ob.calculate_imbalance(depth_levels=1)

        assert imbalance["bid_volume"] == 100
        assert imbalance["ask_volume"] == 100
        assert imbalance["imbalance"] == 0.0  # balanced
        assert imbalance["imbalance_ratio"] == 1.0

    def test_calculate_imbalance_bullish(self):
        """calculate_imbalance() для bullish pressure (больше bids)."""
        ob = OrderBookState("BTCUSDT")

        snapshot = OrderBookSnapshot(
            timestamp_us=1000,
            bids=[OrderBookLevel(price_ticks=10000, qty_steps=300)],
            asks=[OrderBookLevel(price_ticks=10001, qty_steps=100)],
            depth=1,
            update_id=123,
        )

        ob.apply_snapshot(snapshot)

        imbalance = ob.calculate_imbalance(depth_levels=1)

        assert imbalance["bid_volume"] == 300
        assert imbalance["ask_volume"] == 100
        assert imbalance["imbalance"] == 0.5  # (300-100)/(300+100) = 0.5
        assert imbalance["imbalance_ratio"] == 3.0

    def test_calculate_imbalance_bearish(self):
        """calculate_imbalance() для bearish pressure (больше asks)."""
        ob = OrderBookState("BTCUSDT")

        snapshot = OrderBookSnapshot(
            timestamp_us=1000,
            bids=[OrderBookLevel(price_ticks=10000, qty_steps=100)],
            asks=[OrderBookLevel(price_ticks=10001, qty_steps=300)],
            depth=1,
            update_id=123,
        )

        ob.apply_snapshot(snapshot)

        imbalance = ob.calculate_imbalance(depth_levels=1)

        assert imbalance["bid_volume"] == 100
        assert imbalance["ask_volume"] == 300
        assert imbalance["imbalance"] == -0.5  # (100-300)/(100+300) = -0.5
        assert imbalance["imbalance_ratio"] == pytest.approx(0.333, rel=0.01)

    def test_to_dict(self):
        """to_dict() сериализует orderbook state."""
        ob = OrderBookState("BTCUSDT")

        snapshot = OrderBookSnapshot(
            timestamp_us=1000,
            bids=[OrderBookLevel(price_ticks=10000, qty_steps=100)],
            asks=[OrderBookLevel(price_ticks=10001, qty_steps=150)],
            depth=1,
            update_id=123,
        )

        ob.apply_snapshot(snapshot)

        data = ob.to_dict()

        assert data["symbol"] == "BTCUSDT"
        assert data["timestamp_us"] == 1000
        assert data["update_id"] == 123
        assert len(data["bids"]) == 1
        assert len(data["asks"]) == 1


class TestReconstructFromCheckpoint:
    """Тесты reconstruct_from_checkpoint()."""

    def test_reconstruct_from_checkpoint(self):
        """reconstruct_from_checkpoint() парсит BookCheckpoint dict."""
        checkpoint_dict = {
            "timestampUs": 1000,
            "depth": 2,
            "updateId": 123,
            "bids": '[{"price": 10000, "qty": 100}, {"price": 9999, "qty": 200}]',
            "asks": '[{"price": 10001, "qty": 150}, {"price": 10002, "qty": 250}]',
        }

        snapshot = reconstruct_from_checkpoint(checkpoint_dict)

        assert snapshot.timestamp_us == 1000
        assert snapshot.depth == 2
        assert snapshot.update_id == 123
        assert len(snapshot.bids) == 2
        assert len(snapshot.asks) == 2
        assert snapshot.bids[0].price_ticks == 10000
        assert snapshot.asks[0].price_ticks == 10001

    def test_reconstruct_empty_orderbook(self):
        """reconstruct_from_checkpoint() с пустыми bids/asks."""
        checkpoint_dict = {
            "timestampUs": 1000,
            "depth": 0,
            "updateId": 123,
            "bids": "[]",
            "asks": "[]",
        }

        snapshot = reconstruct_from_checkpoint(checkpoint_dict)

        assert len(snapshot.bids) == 0
        assert len(snapshot.asks) == 0
