"""
Redis subscriber для WebSocket real-time broadcast (Roadmap §2.1).

Источник: Roadmap §2.1 (Redis pub/sub zero-latency)

Архитектура:
- Подписывается на Redis channels: bybit:live:{symbol}
- Получает события от EventCollector через Redis pub/sub
- Broadcast всем WebSocket подписчикам через LiveFeedManager
- Zero-latency: <10ms вместо 5s polling

Integration:
- Заменяет live_feed_poller() в websocket.py
- Background task подписывается на Redis при startup
- FastAPI WebSocket endpoints используют LiveFeedManager (без изменений)
"""

import asyncio
import json
import logging

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None  # type: ignore

logger = logging.getLogger(__name__)


async def redis_subscriber_task(
    redis_url: str,
    symbols: list[str],
    live_feed_manager,
):
    """Background task для подписки на Redis channels и broadcast.

    Roadmap §2.1: заменяет polling на pub/sub для zero-latency.

    Args:
        redis_url: Redis connection URL
        symbols: список symbols для подписки (BTCUSDT, ETHUSDT, XRPUSDT)
        live_feed_manager: LiveFeedManager instance для broadcast
    """
    if not REDIS_AVAILABLE:
        logger.warning("Redis not available, falling back to polling")
        return

    try:
        # Подключаемся к Redis
        redis_client = await aioredis.from_url(redis_url, decode_responses=True)
        pubsub = redis_client.pubsub()

        # Подписываемся на все channels
        channels = [f"bybit:live:{symbol}" for symbol in symbols]
        await pubsub.subscribe(*channels)
        logger.info(f"Redis subscriber connected, channels: {channels}")

        # Слушаем сообщения
        async for message in pubsub.listen():
            try:
                if message["type"] == "message":
                    channel = message["channel"]
                    data = message["data"]

                    # Извлекаем symbol из channel
                    symbol = channel.replace("bybit:live:", "")

                    # Парсим JSON
                    event = json.loads(data)

                    # Broadcast всем WebSocket подписчикам
                    await live_feed_manager.broadcast(symbol, event)

                    logger.debug(f"Broadcasted event from Redis: {symbol}, type={event.get('type')}")

            except Exception as exc:
                logger.error(f"Error processing Redis message: {exc}", exc_info=True)

    except Exception as exc:
        logger.error(f"Redis subscriber error: {exc}", exc_info=True)
    finally:
        if redis_client:
            await redis_client.close()
            logger.info("Redis subscriber closed")


def register_redis_subscriber(app, live_feed_manager, redis_url: str = "redis://localhost:6379/0"):
    """Зарегистрировать Redis subscriber в FastAPI app.

    Roadmap §2.1: заменяет polling на pub/sub.

    Args:
        app: FastAPI application
        live_feed_manager: LiveFeedManager instance
        redis_url: Redis connection URL
    """

    @app.on_event("startup")
    async def start_redis_subscriber():
        """Запустить Redis subscriber при startup."""
        symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]

        if REDIS_AVAILABLE:
            # Redis pub/sub (zero-latency)
            asyncio.create_task(
                redis_subscriber_task(redis_url, symbols, live_feed_manager)
            )
            logger.info("Started Redis subscriber (zero-latency mode)")
        else:
            # Fallback: polling mode
            logger.warning("Redis not available, using polling mode")
            # Polling задачи уже зарегистрированы в websocket.py
