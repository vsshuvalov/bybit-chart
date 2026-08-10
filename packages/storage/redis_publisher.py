"""
Redis publisher для real-time event broadcast (Roadmap §2.1).

Источник: Roadmap §2.1 (Redis pub/sub), §8 (live feeds, zero-latency)

Архитектура:
- EventCollector публикует события в Redis при append_trade/append_book_checkpoint
- Redis channel: bybit:live:{symbol} (например, bybit:live:BTCUSDT)
- Message format: JSON с полным событием (RawTrade или BookCheckpoint)
- FastAPI WebSocket подписывается на channels и broadcast подписчикам

Преимущества над polling:
- Zero-latency: <10ms вместо 5s polling delay
- Horizontal scaling: multiple API instances share Redis
- Pub/sub pattern: decoupling между collector и API
- Backpressure handling через Redis streams (future)

Requirements:
- Redis server (redis-server)
- redis-py client
"""

import json
import logging
from typing import Any

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None  # type: ignore

logger = logging.getLogger(__name__)


class RedisPublisher:
    """Redis publisher для real-time event broadcast.

    Roadmap §2.1: публикация событий в Redis pub/sub для instant broadcast.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """Инициализировать Redis publisher.

        Args:
            redis_url: URL Redis server (default: localhost:6379/0)
        """
        if not REDIS_AVAILABLE:
            logger.warning("Redis not available, real-time pub/sub disabled")
            self.client = None
            return

        try:
            self.client = redis.from_url(redis_url, decode_responses=True)
            # Test connection
            self.client.ping()
            logger.info(f"Redis publisher connected: {redis_url}")
        except Exception as exc:
            logger.error(f"Failed to connect to Redis: {exc}")
            self.client = None

    def publish_event(self, symbol: str, event: dict[str, Any]) -> bool:
        """Опубликовать событие в Redis channel.

        Args:
            symbol: BTCUSDT, ETHUSDT, XRPUSDT
            event: десериализованное событие (RawTrade или BookCheckpoint)

        Returns:
            True если успешно опубликовано, False иначе
        """
        if not self.client:
            return False

        try:
            channel = f"bybit:live:{symbol}"
            message = json.dumps(event)
            self.client.publish(channel, message)
            return True

        except Exception as exc:
            logger.error(f"Failed to publish event to Redis: {exc}")
            return False

    def close(self):
        """Закрыть Redis connection."""
        if self.client:
            self.client.close()
            logger.info("Redis publisher closed")


# Глобальный instance (опционально)
_global_publisher: RedisPublisher | None = None


def get_redis_publisher(redis_url: str = "redis://localhost:6379/0") -> RedisPublisher:
    """Получить глобальный Redis publisher (singleton).

    Args:
        redis_url: URL Redis server

    Returns:
        RedisPublisher instance
    """
    global _global_publisher

    if _global_publisher is None:
        _global_publisher = RedisPublisher(redis_url)

    return _global_publisher


def publish_trade(symbol: str, trade: dict[str, Any]) -> bool:
    """Convenience функция для публикации RawTrade.

    Args:
        symbol: BTCUSDT, ETHUSDT, XRPUSDT
        trade: RawTrade dict (после model_dump())

    Returns:
        True если успешно опубликовано
    """
    publisher = get_redis_publisher()
    return publisher.publish_event(symbol, {"type": "trade", "data": trade})


def publish_book_checkpoint(symbol: str, checkpoint: dict[str, Any]) -> bool:
    """Convenience функция для публикации BookCheckpoint.

    Args:
        symbol: BTCUSDT, ETHUSDT, XRPUSDT
        checkpoint: BookCheckpoint dict (после model_dump())

    Returns:
        True если успешно опубликовано
    """
    publisher = get_redis_publisher()
    return publisher.publish_event(symbol, {"type": "book_checkpoint", "data": checkpoint})
