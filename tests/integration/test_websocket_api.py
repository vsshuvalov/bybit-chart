"""
Тесты WebSocket live feed endpoint (Roadmap §2.1).

Проверяют: WebSocket connection, broadcast, reconnect.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts.schemas import RawTrade, TakerSide

pytestmark = pytest.mark.contract


class TestWebSocketLiveFeed:
    """Тесты WebSocket /ws/live/{symbol}."""

    def test_websocket_connect(self):
        """WebSocket connection успешно устанавливается."""
        from packages.api.app import create_app
        from packages.bybit.collector import EventCollector

        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)

            # Создаём минимальные данные
            collector = EventCollector(base_dir / "BTCUSDT", "BTCUSDT")
            collector.append_trade(RawTrade(
                symbol="BTCUSDT", trade_id="1", sequence=1,
                exchange_timestamp_ms=1000, outer_timestamp_ms=1000, receive_timestamp_ms=1000,
                price_ticks=100, qty_steps=10, taker_side=TakerSide.BUY,
            ))
            collector.flush()
            collector.wal.roll_segment()
            collector.wal.close_and_publish_segment(
                0, collector.wal.offsets.closed, use_real_deserialization=True
            )
            collector.close()

            app = create_app(data_dir=base_dir)
            client = TestClient(app)

            # Подключаемся к WebSocket
            with client.websocket_connect("/ws/live/BTCUSDT") as websocket:
                # Ожидаем "connected" сообщение
                data = websocket.receive_json()
                assert data["type"] == "connected"
                assert data["symbol"] == "BTCUSDT"

    def test_websocket_invalid_symbol(self):
        """WebSocket для несуществующего symbol работает (но нет данных)."""
        from packages.api.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            # Подключаемся к несуществующему symbol
            with client.websocket_connect("/ws/live/UNKNOWN") as websocket:
                data = websocket.receive_json()
                assert data["type"] == "connected"
                assert data["symbol"] == "UNKNOWN"

    def test_websocket_ping_pong(self):
        """WebSocket поддерживает ping/pong."""
        from packages.api.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(data_dir=td)
            client = TestClient(app)

            with client.websocket_connect("/ws/live/BTCUSDT") as websocket:
                # Пропускаем "connected"
                websocket.receive_json()

                # Отправляем ping
                websocket.send_json({"type": "ping"})

                # Ожидаем pong
                data = websocket.receive_json()
                assert data["type"] == "pong"

    def test_live_feed_manager_broadcast(self):
        """LiveFeedManager корректно broadcast сообщения."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from packages.api.websocket import LiveFeedManager

        manager = LiveFeedManager()

        # Mock WebSocket connections
        ws1 = MagicMock()
        ws1.send_json = AsyncMock()
        ws2 = MagicMock()
        ws2.send_json = AsyncMock()

        # Добавляем connections вручную (без accept)
        manager.active_connections["BTCUSDT"] = [ws1, ws2]

        # Broadcast сообщения
        message = {"type": "trade", "data": {"price": 100}}

        async def test():
            await manager.broadcast("BTCUSDT", message)

            # Проверяем, что оба получили сообщение
            ws1.send_json.assert_called_once_with(message)
            ws2.send_json.assert_called_once_with(message)

        asyncio.run(test())

    def test_live_feed_manager_disconnect(self):
        """LiveFeedManager корректно удаляет disconnected connections."""
        from unittest.mock import MagicMock

        from packages.api.websocket import LiveFeedManager

        manager = LiveFeedManager()

        ws1 = MagicMock()
        ws2 = MagicMock()

        manager.active_connections["BTCUSDT"] = [ws1, ws2]
        assert len(manager.active_connections["BTCUSDT"]) == 2

        # Disconnect ws1
        manager.disconnect(ws1, "BTCUSDT")

        assert len(manager.active_connections["BTCUSDT"]) == 1
        assert ws2 in manager.active_connections["BTCUSDT"]
        assert ws1 not in manager.active_connections["BTCUSDT"]
