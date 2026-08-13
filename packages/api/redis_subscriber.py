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
    import sys
    print(f"[DEBUG] redis_subscriber_task started, REDIS_AVAILABLE={REDIS_AVAILABLE}", file=sys.stderr, flush=True)

    if not REDIS_AVAILABLE:
        logger.warning("Redis not available, falling back to polling")
        return

    redis_client = None
    pubsub = None

    try:
        print("[DEBUG] Creating Redis client...", file=sys.stderr, flush=True)
        # Подключаемся к Redis
        redis_client = await aioredis.from_url(redis_url, decode_responses=True)
        print("[DEBUG] Redis client created", file=sys.stderr, flush=True)

        pubsub = redis_client.pubsub()
        print("[DEBUG] PubSub created", file=sys.stderr, flush=True)

        # Подписываемся на все channels
        channels = [f"bybit:live:{symbol}" for symbol in symbols]
        await pubsub.subscribe(*channels)
        logger.info(f"[REDIS_SUBSCRIBER] Connected, listening on: {channels}")
        print(f"[DEBUG] Subscribed to: {channels}", file=sys.stderr, flush=True)

        # Слушаем сообщения (используем polling вместо async generator)
        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)

                if message is None:
                    await asyncio.sleep(0.01)  # Small delay to prevent busy loop
                    continue

                if message["type"] == "message":
                    channel = message["channel"]
                    data = message["data"]

                    # Извлекаем symbol из channel
                    symbol = channel.replace("bybit:live:", "")

                    # Парсим JSON
                    try:
                        event = json.loads(data)
                        # Broadcast всем WebSocket подписчикам
                        await live_feed_manager.broadcast(symbol, event)
                        logger.debug(f"[REDIS_SUBSCRIBER] Broadcast {symbol}: {event.get('eventType')}")
                    except json.JSONDecodeError as exc:
                        logger.error(f"[REDIS_SUBSCRIBER] Invalid JSON: {exc}")

            except asyncio.CancelledError:
                logger.info("[REDIS_SUBSCRIBER] Cancelled")
                break
            except Exception as exc:
                logger.error(f"[REDIS_SUBSCRIBER] Error in loop: {exc}", exc_info=True)
                await asyncio.sleep(1)  # Brief pause before retry

    except asyncio.CancelledError:
        logger.info("[REDIS_SUBSCRIBER] Task cancelled (shutdown)")
    except Exception as exc:
        logger.error(f"[REDIS_SUBSCRIBER] Fatal error: {exc}", exc_info=True)
        print(f"[DEBUG] Fatal error: {exc}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
    finally:
        # Cleanup
        print("[DEBUG] Cleanup started", file=sys.stderr, flush=True)
        if pubsub:
            try:
                await pubsub.unsubscribe()
                await pubsub.close()
            except Exception:
                pass

        if redis_client:
            try:
                await redis_client.close()
            except Exception:
                pass

        logger.info("[REDIS_SUBSCRIBER] Closed")
        print("[DEBUG] redis_subscriber_task finished", file=sys.stderr, flush=True)


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
        import sys
        print("[DEBUG] start_redis_subscriber called!", file=sys.stderr, flush=True)

        symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]

        logger.info(f"[REDIS_SUBSCRIBER] Initializing... REDIS_AVAILABLE={REDIS_AVAILABLE}")

        if REDIS_AVAILABLE:
            # Redis pub/sub (zero-latency)
            task = asyncio.create_task(
                redis_subscriber_task(redis_url, symbols, live_feed_manager)
            )
            logger.info(f"[REDIS_SUBSCRIBER] Started Redis subscriber task (zero-latency mode), channels: {symbols}")
            print(f"[DEBUG] Task created: {task}", file=sys.stderr, flush=True)
        else:
            # Fallback: polling mode
            logger.warning("[REDIS_SUBSCRIBER] Redis not available, using polling mode")
            # Polling задачи уже зарегистрированы в websocket.py
