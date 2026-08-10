#!/usr/bin/env python3
"""
Live Demo: Bybit WebSocket → WAL → Parquet (Stage 2 / P2-S2-005).

Подключается к Bybit publicTrade.BTCUSDT, получает реальные сделки,
записывает в WAL, периодически публикует Parquet сегменты.

Использование:
    python examples/bybit_live_demo.py [--duration SECONDS] [--output-dir PATH]

Пример:
    python examples/bybit_live_demo.py --duration 60 --output-dir /tmp/demo

Нажмите Ctrl+C для остановки.
"""

import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

from packages.bybit.collector import EventCollector
from packages.bybit.deserializer import deserialize_raw_trade
from packages.bybit.ws_client import BybitWebSocketClient

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class LiveDemo:
    """Live demo для Bybit → WAL → Parquet pipeline."""

    def __init__(
        self,
        output_dir: Path,
        symbol: str = "BTCUSDT",
        publish_interval: int = 30,
    ):
        """Инициализировать demo.

        Args:
            output_dir: каталог для WAL и .parquet файлов
            symbol: символ для подписки (BTCUSDT)
            publish_interval: интервал публикации Parquet сегментов (секунды)
        """
        self.output_dir = Path(output_dir)
        self.symbol = symbol
        self.publish_interval = publish_interval

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Инициализация компонентов
        self.ws_client = BybitWebSocketClient()
        self.collector = EventCollector(
            partition_dir=self.output_dir / symbol,
            partition_id=symbol,
        )

        # Статистика
        self.stats = {
            "trades_received": 0,
            "trades_written": 0,
            "parquet_published": 0,
            "last_publish_offset": 0,
            "start_time": datetime.now(),
        }

        self.running = False

    async def handle_message(self, message: dict) -> None:
        """Обработать входящее WebSocket сообщение."""
        try:
            # Фильтруем только publicTrade сообщения
            topic = message.get("topic", "")
            if not topic.startswith("publicTrade."):
                return

            # Десериализация
            trades = deserialize_raw_trade(message)
            self.stats["trades_received"] += len(trades)

            # Запись в WAL
            for trade in trades:
                self.collector.append_trade(trade)
                self.stats["trades_written"] += 1

                # Логируем первые несколько trades
                if self.stats["trades_written"] <= 3:
                    logger.info(
                        f"Trade: {trade.trade_id} | "
                        f"price={trade.price_ticks} | "
                        f"qty={trade.qty_steps} | "
                        f"side={trade.taker_side}"
                    )

        except Exception as exc:
            logger.error(f"Ошибка обработки сообщения: {exc}", exc_info=True)

    async def publish_segment_periodically(self) -> None:
        """Периодически публиковать Parquet сегменты."""
        while self.running:
            await asyncio.sleep(self.publish_interval)

            try:
                # Flush pending records
                self.collector.flush()

                # Roll segment
                self.collector.wal.roll_segment()

                # Проверка, есть ли что публиковать
                start_offset = self.stats["last_publish_offset"]
                end_offset = self.collector.wal.offsets.closed

                if end_offset > start_offset:
                    parquet_path = self.collector.wal.close_and_publish_segment(
                        start_offset, end_offset, use_real_deserialization=True
                    )

                    self.stats["parquet_published"] += 1
                    self.stats["last_publish_offset"] = end_offset

                    logger.info(
                        f"Опубликован Parquet сегмент: {parquet_path.name} | "
                        f"offsets=[{start_offset}, {end_offset}) | "
                        f"trades={end_offset - start_offset}"
                    )

            except Exception as exc:
                logger.error(f"Ошибка публикации сегмента: {exc}", exc_info=True)

    def print_stats(self) -> None:
        """Вывести статистику."""
        elapsed = (datetime.now() - self.stats["start_time"]).total_seconds()
        rate = self.stats["trades_written"] / elapsed if elapsed > 0 else 0

        logger.info("=" * 60)
        logger.info("Статистика:")
        logger.info(f"  Trades получено:      {self.stats['trades_received']}")
        logger.info(f"  Trades записано:      {self.stats['trades_written']}")
        logger.info(f"  Parquet опубликовано: {self.stats['parquet_published']}")
        logger.info(f"  Скорость записи:      {rate:.1f} trades/sec")
        logger.info(f"  Время работы:         {elapsed:.1f} sec")
        logger.info(f"  WAL accepted offset:  {self.collector.wal.accepted_offset}")
        logger.info(f"  WAL durable offset:   {self.collector.wal.durable_offset}")
        logger.info(f"  WAL closed offset:    {self.collector.wal.offsets.closed}")
        logger.info(f"  Выходной каталог:     {self.output_dir}")
        logger.info("=" * 60)

    async def run(self, duration: int | None = None) -> None:
        """Запустить demo.

        Args:
            duration: длительность работы (секунды), None = бесконечно
        """
        self.running = True
        publish_task = None

        try:
            # Подключение к WebSocket
            logger.info(f"Подключение к Bybit WebSocket...")
            await self.ws_client.connect()

            # Подписка на publicTrade
            logger.info(f"Подписка на publicTrade.{self.symbol}...")
            await self.ws_client.subscribe("publicTrade", self.symbol)

            # Запуск задачи публикации сегментов
            publish_task = asyncio.create_task(self.publish_segment_periodically())

            # Запуск основного цикла WebSocket
            logger.info(f"Начало записи trades → WAL → Parquet...")
            logger.info(f"Нажмите Ctrl+C для остановки")

            if duration:
                # Запуск с таймаутом
                try:
                    await asyncio.wait_for(
                        self.ws_client.run(
                            on_message=self.handle_message, auto_reconnect=True
                        ),
                        timeout=duration,
                    )
                except asyncio.TimeoutError:
                    logger.info(f"Достигнут таймаут {duration} секунд")
            else:
                # Бесконечный запуск
                await self.ws_client.run(
                    on_message=self.handle_message, auto_reconnect=True
                )

        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки (Ctrl+C)")
        except Exception as exc:
            logger.error(f"Неожиданная ошибка: {exc}", exc_info=True)
        finally:
            # Остановка
            self.running = False
            if publish_task:
                publish_task.cancel()

            # Финальная публикация
            logger.info("Финальная публикация сегментов...")
            self.collector.flush()
            self.collector.wal.roll_segment()

            start_offset = self.stats["last_publish_offset"]
            end_offset = self.collector.wal.offsets.closed

            if end_offset > start_offset:
                parquet_path = self.collector.wal.close_and_publish_segment(
                    start_offset, end_offset, use_real_deserialization=True
                )
                self.stats["parquet_published"] += 1
                logger.info(f"Финальный сегмент: {parquet_path.name}")

            # Закрытие
            await self.ws_client.close()
            self.collector.close()

            # Статистика
            self.print_stats()


async def main():
    """Entry point."""
    parser = argparse.ArgumentParser(description="Bybit Live Demo: WebSocket → WAL → Parquet")
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Длительность работы (секунды). По умолчанию: бесконечно (Ctrl+C для остановки)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="/tmp/bybit-demo",
        help="Каталог для WAL и .parquet файлов. По умолчанию: /tmp/bybit-demo",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="Символ для подписки. По умолчанию: BTCUSDT",
    )
    parser.add_argument(
        "--publish-interval",
        type=int,
        default=30,
        help="Интервал публикации Parquet сегментов (секунды). По умолчанию: 30",
    )

    args = parser.parse_args()

    demo = LiveDemo(
        output_dir=Path(args.output_dir),
        symbol=args.symbol,
        publish_interval=args.publish_interval,
    )

    await demo.run(duration=args.duration)


if __name__ == "__main__":
    asyncio.run(main())
