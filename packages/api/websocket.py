"""
WebSocket endpoint для real-time updates (Roadmap §2.1).

Источник: Roadmap §2.1 (real-time streaming), §8 (live feeds)

Архитектура:
- FastAPI WebSocket endpoint /ws/live/{symbol}
- Broadcast новых RawTrade событий подписчикам
- Graceful disconnect handling
- Heartbeat/ping для keepalive

MVP: polling-based (проверка новых файлов каждые N секунд)
Future: pub/sub через Redis/channels для zero-latency
"""

import asyncio
import json
import logging
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class LiveFeedManager:
    """Менеджер для WebSocket live feeds.

    Roadmap §2.1: каждый symbol имеет список активных подписчиков.
    При появлении новых данных — broadcast всем подписчикам.
    """

    def __init__(self):
        # symbol → list[WebSocket]
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, symbol: str):
        """Подключить WebSocket к live feed для symbol."""
        await websocket.accept()

        if symbol not in self.active_connections:
            self.active_connections[symbol] = []

        self.active_connections[symbol].append(websocket)
        logger.info(f"WebSocket connected: {symbol}, total={len(self.active_connections[symbol])}")

    def disconnect(self, websocket: WebSocket, symbol: str):
        """Отключить WebSocket от live feed."""
        if symbol in self.active_connections:
            if websocket in self.active_connections[symbol]:
                self.active_connections[symbol].remove(websocket)
                logger.info(f"WebSocket disconnected: {symbol}, remaining={len(self.active_connections[symbol])}")

    async def broadcast(self, symbol: str, message: dict):
        """Broadcast сообщение всем подписчикам symbol."""
        if symbol not in self.active_connections:
            return

        disconnected = []

        for connection in self.active_connections[symbol]:
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.warning(f"Failed to send to WebSocket: {exc}")
                disconnected.append(connection)

        # Очистка отключённых connections
        for conn in disconnected:
            if conn in self.active_connections[symbol]:
                self.active_connections[symbol].remove(conn)

    async def send_heartbeat(self, symbol: str):
        """Отправить heartbeat всем подписчикам."""
        await self.broadcast(symbol, {"type": "heartbeat", "timestamp": asyncio.get_event_loop().time()})


# Глобальный instance
live_feed_manager = LiveFeedManager()


async def live_feed_poller(reader, symbol: str, interval_seconds: int = 5):
    """Polling-based live feed (MVP).

    Roadmap §2.1: каждые N секунд проверяем новые Parquet файлы
    и отправляем последние trades подписчикам.

    Future: pub/sub через Redis для zero-latency.

    Args:
        reader: ParquetReader instance
        symbol: BTCUSDT, ETHUSDT, XRPUSDT
        interval_seconds: интервал polling (default: 5s)
    """
    last_timestamp_us = 0

    while True:
        try:
            # Читаем последние N секунд данных
            end_ts = asyncio.get_event_loop().time() * 1_000_000
            start_ts = end_ts - (interval_seconds * 2 * 1_000_000)  # 2x buffer

            events = reader.read_range(
                symbol=symbol,
                start_ts=int(start_ts),
                end_ts=int(end_ts),
                event_type="RawTrade",
            )

            # Фильтруем только новые события
            new_events = [e for e in events if e.get("timestampUs", 0) > last_timestamp_us]

            if new_events:
                # Обновляем last_timestamp
                last_timestamp_us = max(e.get("timestampUs", 0) for e in new_events)

                # Broadcast новых trades
                for event in new_events:
                    await live_feed_manager.broadcast(symbol, {
                        "type": "trade",
                        "data": event,
                    })

                logger.debug(f"Broadcasted {len(new_events)} new trades for {symbol}")

            # Heartbeat каждые 10 секунд
            if int(asyncio.get_event_loop().time()) % 10 == 0:
                await live_feed_manager.send_heartbeat(symbol)

        except FileNotFoundError:
            # Symbol не имеет данных — ждём
            pass
        except Exception as exc:
            logger.error(f"Error in live feed poller for {symbol}: {exc}", exc_info=True)

        await asyncio.sleep(interval_seconds)


def register_websocket_endpoints(app, reader):
    """Зарегистрировать WebSocket endpoints в FastAPI app.

    Args:
        app: FastAPI application
        reader: ParquetReader instance
    """

    @app.websocket("/ws/live/{symbol}")
    async def websocket_live_feed(websocket: WebSocket, symbol: str):
        """WebSocket endpoint для real-time trades.

        Roadmap §2.1: подписка на live feed для symbol.

        Usage (JavaScript):
            const ws = new WebSocket('ws://localhost:8000/ws/live/BTCUSDT');
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'trade') {
                    console.log('New trade:', data.data);
                }
            };
        """
        await live_feed_manager.connect(websocket, symbol)

        try:
            # Отправляем initial status
            await websocket.send_json({
                "type": "connected",
                "symbol": symbol,
                "message": f"Connected to live feed for {symbol}",
            })

            # Keep connection alive + receive messages (ping/pong)
            while True:
                try:
                    # Ждём сообщения от клиента (ping или close)
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    message = json.loads(data)

                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})

                except asyncio.TimeoutError:
                    # Timeout — отправляем heartbeat
                    await websocket.send_json({"type": "heartbeat"})

        except WebSocketDisconnect:
            live_feed_manager.disconnect(websocket, symbol)
            logger.info(f"WebSocket disconnected cleanly: {symbol}")

        except Exception as exc:
            logger.error(f"WebSocket error for {symbol}: {exc}", exc_info=True)
            live_feed_manager.disconnect(websocket, symbol)

    # Запускаем background poller для каждого symbol
    # Roadmap §8: три инструмента
    @app.on_event("startup")
    async def start_live_feed_pollers():
        """Запустить background tasks для polling новых данных."""
        symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]

        for symbol in symbols:
            asyncio.create_task(live_feed_poller(reader, symbol, interval_seconds=5))
            logger.info(f"Started live feed poller for {symbol}")
