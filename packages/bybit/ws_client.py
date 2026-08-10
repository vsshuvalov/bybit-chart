"""
Bybit WebSocket Client для публичных потоков (Stage 2 / P2-S2-001).

Источник: Roadmap §5, §8; BTCUSDT_Bybit_Intraday_Strategies.md §2
Официальная документация: https://bybit-exchange.github.io/docs/v5/websocket/connect

Поддерживаемые каналы:
- publicTrade.{symbol} — реальные сделки
- orderbook.{depth}.{symbol} — снимки и обновления книги заявок
"""

import asyncio
import json
import logging
from typing import Any, Callable, Optional

import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


class BybitWebSocketClient:
    """Asyncio WebSocket client для Bybit public streams.

    Использование:
        client = BybitWebSocketClient()
        await client.connect()
        await client.subscribe("publicTrade", "BTCUSDT")
        await client.run(on_message=handle_message)
    """

    BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"
    PING_INTERVAL = 20  # seconds (Bybit требует ping каждые 30s)
    RECONNECT_DELAY = 5  # seconds

    def __init__(self):
        self.ws: Optional[WebSocketClientProtocol] = None
        self.subscriptions: list[dict[str, str]] = []
        self.running = False
        self._ping_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Установить WebSocket соединение с Bybit.

        Raises:
            ConnectionError: не удалось подключиться
        """
        try:
            self.ws = await websockets.connect(
                self.BYBIT_WS_URL,
                ping_interval=None,  # управляем ping вручную
            )
            logger.info(f"Подключено к {self.BYBIT_WS_URL}")
        except Exception as exc:
            raise ConnectionError(f"Не удалось подключиться к Bybit WebSocket: {exc}") from exc

    async def subscribe(self, channel: str, symbol: str) -> None:
        """Подписаться на канал.

        Args:
            channel: имя канала (publicTrade, orderbook.200)
            symbol: инструмент (BTCUSDT)

        Пример:
            await client.subscribe("publicTrade", "BTCUSDT")
            await client.subscribe("orderbook.200", "BTCUSDT")
        """
        if self.ws is None:
            raise RuntimeError("WebSocket не подключен — вызовите connect() сначала")

        topic = f"{channel}.{symbol}"
        subscription = {
            "op": "subscribe",
            "args": [topic],
        }

        await self.ws.send(json.dumps(subscription))
        self.subscriptions.append(subscription)
        logger.info(f"Подписка на {topic}")

    async def _send_ping(self) -> None:
        """Отправить ping для keepalive (каждые 20s)."""
        while self.running and self.ws:
            try:
                await self.ws.send(json.dumps({"op": "ping"}))
                logger.debug("Отправлен ping")
                await asyncio.sleep(self.PING_INTERVAL)
            except Exception as exc:
                logger.warning(f"Ошибка ping: {exc}")
                break

    async def run(
        self,
        on_message: Callable[[dict[str, Any]], None],
        auto_reconnect: bool = True,
    ) -> None:
        """Основной цикл обработки сообщений.

        Args:
            on_message: callback для обработки входящих сообщений
            auto_reconnect: автоматический reconnect при разрыве соединения

        Пример:
            async def handle(msg):
                if msg.get("topic", "").startswith("publicTrade"):
                    print(f"Trade: {msg}")

            await client.run(on_message=handle)
        """
        self.running = True

        while self.running:
            try:
                if self.ws is None:
                    logger.info("Переподключение...")
                    await self.connect()
                    # Восстанавливаем подписки
                    for sub in self.subscriptions:
                        await self.ws.send(json.dumps(sub))

                # Запуск ping task
                if self._ping_task is None or self._ping_task.done():
                    self._ping_task = asyncio.create_task(self._send_ping())

                # Получение сообщений
                async for raw_message in self.ws:
                    try:
                        message = json.loads(raw_message)

                        # Обработка pong
                        if message.get("op") == "pong":
                            logger.debug("Получен pong")
                            continue

                        # Обработка subscribe response
                        if message.get("op") == "subscribe":
                            if message.get("success"):
                                logger.info(f"Подписка успешна: {message.get('ret_msg')}")
                            else:
                                logger.error(f"Ошибка подписки: {message}")
                            continue

                        # Передача в callback
                        await on_message(message)

                    except json.JSONDecodeError as exc:
                        logger.warning(f"Некорректный JSON: {exc}")
                    except Exception as exc:
                        logger.error(f"Ошибка обработки сообщения: {exc}", exc_info=True)

            except websockets.exceptions.ConnectionClosed as exc:
                logger.warning(f"Соединение закрыто: {exc}")
                if not auto_reconnect:
                    break
                await asyncio.sleep(self.RECONNECT_DELAY)

            except Exception as exc:
                logger.error(f"Неожиданная ошибка в цикле: {exc}", exc_info=True)
                if not auto_reconnect:
                    break
                await asyncio.sleep(self.RECONNECT_DELAY)

    async def close(self) -> None:
        """Закрыть WebSocket соединение."""
        self.running = False
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
        if self.ws:
            await self.ws.close()
            logger.info("WebSocket закрыт")
