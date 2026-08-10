"""
Тесты Redis pub/sub для real-time broadcast (Roadmap §2.1).

Проверяют: RedisPublisher, redis_subscriber_task, integration.
"""

import pytest

pytestmark = pytest.mark.contract


def _redis_available() -> bool:
    """Проверить, доступен ли Redis."""
    try:
        import redis
        client = redis.Redis(host='localhost', port=6379, socket_connect_timeout=1)
        client.ping()
        return True
    except:
        return False


class TestRedisPublisher:
    """Тесты RedisPublisher."""

    def test_redis_publisher_init_without_redis(self):
        """RedisPublisher работает без Redis (graceful degradation)."""
        from packages.storage.redis_publisher import RedisPublisher

        # Подключение к несуществующему Redis
        publisher = RedisPublisher(redis_url="redis://localhost:9999/0")

        # Должен инициализироваться с client=None
        assert publisher.client is None

    def test_redis_publisher_publish_without_client(self):
        """publish_event() возвращает False без Redis client."""
        from packages.storage.redis_publisher import RedisPublisher

        publisher = RedisPublisher(redis_url="redis://localhost:9999/0")
        result = publisher.publish_event("BTCUSDT", {"type": "trade", "data": {}})

        assert result is False

    def test_get_redis_publisher_singleton(self):
        """get_redis_publisher() возвращает singleton."""
        from packages.storage.redis_publisher import get_redis_publisher, _global_publisher

        # Очищаем глобальный instance
        import packages.storage.redis_publisher as module
        module._global_publisher = None

        pub1 = get_redis_publisher()
        pub2 = get_redis_publisher()

        assert pub1 is pub2


class TestRedisIntegration:
    """Интеграционные тесты Redis pub/sub (требуют запущенный Redis)."""

    @pytest.mark.skipif(
        not _redis_available(),
        reason="Redis not available"
    )
    def test_redis_publisher_publish_success(self):
        """RedisPublisher успешно публикует события (если Redis доступен)."""
        from packages.storage.redis_publisher import RedisPublisher

        publisher = RedisPublisher()

        if publisher.client:
            result = publisher.publish_event("BTCUSDT", {"type": "test", "data": {"value": 123}})
            assert result is True
            publisher.close()

    @pytest.mark.skipif(
        not _redis_available(),
        reason="Redis not available"
    )
    def test_redis_pubsub_roundtrip(self):
        """Полный roundtrip: publish → subscribe → receive."""
        import asyncio
        import json

        from packages.storage.redis_publisher import RedisPublisher

        async def test():
            try:
                import redis.asyncio as aioredis
            except ImportError:
                pytest.skip("redis[asyncio] not installed")
                return

            # Publisher
            publisher = RedisPublisher()
            if not publisher.client:
                pytest.skip("Redis not available")
                return

            # Subscriber
            redis_client = await aioredis.from_url("redis://localhost:6379/0", decode_responses=True)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("bybit:live:TESTBTC")

            # Publish event
            publisher.publish_event("TESTBTC", {"type": "trade", "value": 42})

            # Receive event (with timeout)
            received = False
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    assert data["type"] == "trade"
                    assert data["value"] == 42
                    received = True
                    break

            await redis_client.close()
            publisher.close()

            assert received

        asyncio.run(test())
