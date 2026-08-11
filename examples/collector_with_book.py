#!/usr/bin/env python3
"""
Collector with orderbook support (Roadmap Этап 3).

Подписывается на:
- publicTrade.{SYMBOL}
- orderbook.200.{SYMBOL}

Записывает:
- RawTrade → WAL → Parquet
- BookCheckpoint → WAL → Parquet

Использование:
    python examples/collector_with_book.py --symbol BTCUSDT --output-dir /opt/bybit-chart/data
"""

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from packages.bybit.collector import EventCollector
from packages.bybit.deserializer import deserialize_raw_trade
from packages.bybit.deserializer_book import deserialize_book_snapshot
from packages.bybit.ws_client import BybitWebSocketClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_collector(
    symbol: str,
    output_dir: Path,
    duration: int = None,
):
    """Запустить collector с trade + orderbook.

    Args:
        symbol: торговая пара (например, BTCUSDT)
        output_dir: базовый каталог (создаётся {output_dir}/{symbol}/)
        duration: длительность работы в секундах (None = бесконечно)
    """
    symbol_dir = output_dir / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)

    # EventCollector
    collector = EventCollector(symbol_dir, symbol)
    logger.info(f"EventCollector восстановлен: {symbol_dir}")

    # Счётчики
    trade_count = 0
    book_count = 0
    start_time = asyncio.get_event_loop().time()

    # WebSocket callback
    async def on_message(message: dict):
        nonlocal trade_count, book_count

        try:
            topic = message.get("topic", "")

            # publicTrade
            if topic.startswith("publicTrade."):
                trades = deserialize_raw_trade(message)
                for trade in trades:
                    collector.append_trade(trade)
                    trade_count += 1
                    if trade_count % 1000 == 0:
                        logger.info(f"Записано trades: {trade_count}, books: {book_count}")

            # orderbook (snapshot + delta)
            elif topic.startswith("orderbook."):
                msg_type = message.get("type", "")
                if msg_type == "snapshot":
                    # Snapshot — полная книга
                    book = deserialize_book_snapshot(message)
                    collector.append_book_checkpoint(book)
                    book_count += 1
                    logger.info(f"Записан orderbook snapshot (books={book_count})")
                elif msg_type == "delta":
                    # Delta — записываем как raw BookCheckpoint без reconstruction
                    # Reconstruction будет реализован в Roadmap §8.2
                    # Пока просто логируем, что delta пришёл
                    pass  # TODO: implement delta reconstruction (§8.2)

            # Проверка таймаута
            if duration:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= duration:
                    logger.info(f"Завершение по таймауту ({duration}s)")
                    raise asyncio.CancelledError()

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Ошибка обработки сообщения: {exc}", exc_info=True)

    # WebSocket client
    ws_client = BybitWebSocketClient()

    logger.info(f"Подключение к Bybit WebSocket...")
    await ws_client.connect()

    logger.info(f"Подписка на publicTrade.{symbol}...")
    await ws_client.subscribe("publicTrade", symbol)

    logger.info(f"Подписка на orderbook.200.{symbol}...")
    await ws_client.subscribe("orderbook.200", symbol)

    logger.info(f"Начало записи trades + orderbook → WAL...")
    if duration:
        logger.info(f"Длительность: {duration}s")
    else:
        logger.info(f"Нажмите Ctrl+C для остановки")

    # Run
    try:
        await ws_client.run(on_message=on_message)
    except asyncio.CancelledError:
        logger.info("Завершение...")
    finally:
        collector.flush()
        collector.close()
        logger.info(f"Итого: trades={trade_count}, books={book_count}")


def main():
    parser = argparse.ArgumentParser(
        description="Bybit Collector: publicTrade + orderbook.200"
    )
    parser.add_argument(
        "--symbol",
        default="BTCUSDT",
        help="Символ для подписки. По умолчанию: BTCUSDT",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/bybit-collector"),
        help="Каталог для WAL и .parquet файлов. По умолчанию: /tmp/bybit-collector",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Длительность работы (секунды). По умолчанию: бесконечно",
    )

    args = parser.parse_args()

    asyncio.run(
        run_collector(
            symbol=args.symbol,
            output_dir=args.output_dir,
            duration=args.duration,
        )
    )


if __name__ == "__main__":
    main()
