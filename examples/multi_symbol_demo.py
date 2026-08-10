#!/usr/bin/env python3
"""
Multi-symbol live demo (Этап 1 / P1-B3).

Источник: Roadmap §8 (три инструмента: BTCUSDT, ETHUSDT, XRPUSDT)

Демонстрирует:
- Одновременный сбор данных с 3 symbols
- Separate EventCollector instances per symbol
- WebSocket subscriptions для publicTrade.BTCUSDT, publicTrade.ETHUSDT, publicTrade.XRPUSDT
- Публикация в отдельные Parquet partitions

Использование:
    python examples/multi_symbol_demo.py --duration 60 --output-dir /tmp/bybit-multi-symbol
"""

import argparse
import asyncio
import logging
from pathlib import Path

from packages.bybit.collector import EventCollector
from packages.bybit.deserializer_trade import deserialize_raw_trade
from packages.bybit.ws_client import BybitWebSocketClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Roadmap §8: три инструмента
SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]


async def run_multi_symbol_demo(
    output_dir: Path,
    duration: int = 60,
    publish_interval: int = 10,
):
    """Запустить multi-symbol demo.

    Args:
        output_dir: базовый каталог для всех symbols (создаются {output_dir}/{symbol}/)
        duration: длительность сбора данных (секунды)
        publish_interval: интервал публикации сегментов (секунды)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Создаём EventCollector для каждого symbol
    collectors = {}
    for symbol in SYMBOLS:
        symbol_dir = output_dir / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)

        collector = EventCollector(symbol_dir, symbol)
        collectors[symbol] = collector
        logger.info(f"Создан EventCollector для {symbol}: {symbol_dir}")

    # Счётчики
    trade_counts = {symbol: 0 for symbol in SYMBOLS}

    # WebSocket callback
    def on_trade_message(message: dict):
        """Обработка publicTrade сообщения."""
        try:
            # Определяем symbol из topic
            topic = message.get("topic", "")
            if not topic.startswith("publicTrade."):
                return

            symbol = topic.replace("publicTrade.", "")
            if symbol not in collectors:
                logger.warning(f"Получен trade для неизвестного symbol: {symbol}")
                return

            # Десериализация
            data = message.get("data", [])
            for item in data:
                trade = deserialize_raw_trade(item, symbol)
                collectors[symbol].append_trade(trade)
                trade_counts[symbol] += 1

        except Exception as exc:
            logger.error(f"Ошибка обработки trade: {exc}", exc_info=True)

    # WebSocket client
    ws_client = BybitWebSocketClient(
        url="wss://stream.bybit.com/v5/public/linear",
        on_message=on_trade_message,
    )

    # Подписываемся на publicTrade для всех symbols
    topics = [f"publicTrade.{symbol}" for symbol in SYMBOLS]

    logger.info(f"Начинаем сбор данных для {len(SYMBOLS)} symbols: {', '.join(SYMBOLS)}")
    logger.info(f"Длительность: {duration}s, publish каждые {publish_interval}s")

    try:
        # Подключаемся
        await ws_client.connect()
        await ws_client.subscribe(topics)

        # Периодическая публикация сегментов
        elapsed = 0
        while elapsed < duration:
            await asyncio.sleep(min(publish_interval, duration - elapsed))
            elapsed += min(publish_interval, duration - elapsed)

            # Flush и публикация для каждого symbol
            for symbol, collector in collectors.items():
                collector.flush()

                if collector.wal.offsets.closed > 0:
                    collector.wal.roll_segment()
                    collector.wal.close_and_publish_segment(
                        0,
                        collector.wal.offsets.closed,
                        use_real_deserialization=True,
                    )

            # Статистика
            total_trades = sum(trade_counts.values())
            stats = ", ".join([f"{s}: {c}" for s, c in trade_counts.items()])
            logger.info(f"[{elapsed}s / {duration}s] Собрано trades: {stats} (total: {total_trades})")

    except asyncio.CancelledError:
        logger.info("Demo прерван пользователем")
    except Exception as exc:
        logger.error(f"Ошибка в demo: {exc}", exc_info=True)
    finally:
        # Финальная публикация
        logger.info("Финальная публикация сегментов...")
        for symbol, collector in collectors.items():
            collector.flush()

            if collector.wal.offsets.closed > 0:
                collector.wal.roll_segment()
                collector.wal.close_and_publish_segment(
                    0,
                    collector.wal.offsets.closed,
                    use_real_deserialization=True,
                )

            collector.close()
            logger.info(f"EventCollector {symbol} закрыт")

        # Отключаемся от WebSocket
        await ws_client.disconnect()

        # Финальная статистика
        total_trades = sum(trade_counts.values())
        logger.info("\n=== Финальная статистика ===")
        for symbol in SYMBOLS:
            count = trade_counts[symbol]
            logger.info(f"  {symbol}: {count} trades")
        logger.info(f"  TOTAL: {total_trades} trades")
        logger.info(f"\nДанные сохранены в: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="Multi-symbol Bybit live demo")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/bybit-multi-symbol"),
        help="Output directory (default: /tmp/bybit-multi-symbol)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Длительность сбора данных в секундах (default: 60)",
    )
    parser.add_argument(
        "--publish-interval",
        type=int,
        default=10,
        help="Интервал публикации сегментов в секундах (default: 10)",
    )

    args = parser.parse_args()

    asyncio.run(
        run_multi_symbol_demo(
            output_dir=args.output_dir,
            duration=args.duration,
            publish_interval=args.publish_interval,
        )
    )


if __name__ == "__main__":
    main()
