#!/usr/bin/env python3
"""
RPI feed collector (Roadmap §19 Этап 3).

Записывает kline.1.{SYMBOL} отдельно от standard feeds (publicTrade, orderbook).
RPI feed не участвует в detector/Heatmap — только для account-independent validation.

Feature flag: RPI_ENABLED (env variable или config)

Использование:
    # С RPI feed
    RPI_ENABLED=1 python examples/rpi_collector.py --symbol BTCUSDT --output-dir /opt/bybit-chart/data

    # Без RPI feed (baseline)
    python examples/rpi_collector.py --symbol BTCUSDT --output-dir /opt/bybit-chart/data
"""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

from packages.bybit.deserializer_kline import deserialize_kline
from packages.bybit.ws_client import BybitWebSocketClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_rpi_collector(
    symbol: str,
    output_dir: Path,
    duration: int = None,
    rpi_enabled: bool = True,
):
    """Запустить RPI collector.

    Args:
        symbol: торговая пара (например, BTCUSDT)
        output_dir: базовый каталог (создаётся {output_dir}/{symbol}-rpi/)
        duration: длительность работы в секундах (None = бесконечно)
        rpi_enabled: включить RPI feed (feature flag)
    """
    if not rpi_enabled:
        logger.warning("RPI_ENABLED=0, collector не запустится")
        return

    # Отдельная директория для RPI feed
    rpi_dir = output_dir / f"{symbol}-rpi"
    rpi_dir.mkdir(parents=True, exist_ok=True)

    # JSON log для RPI klines (простейший формат для capacity measurement)
    kline_log_path = rpi_dir / "klines.jsonl"
    kline_log = open(kline_log_path, "a", encoding="utf-8")

    logger.info(f"RPI collector инициализирован: {rpi_dir}")
    logger.info(f"Kline log: {kline_log_path}")

    # Счётчики
    kline_count = 0
    confirmed_count = 0
    start_time = asyncio.get_event_loop().time()

    # WebSocket callback
    async def on_message(message: dict):
        nonlocal kline_count, confirmed_count

        try:
            topic = message.get("topic", "")

            # kline.1.{SYMBOL}
            if topic.startswith("kline."):
                kline = deserialize_kline(message)

                # Записать в JSON log (mode='json' для Decimal serialization)
                kline_dict = kline.model_dump(mode='json')
                kline_log.write(json.dumps(kline_dict) + "\n")
                kline_log.flush()

                kline_count += 1
                if kline.confirm:
                    confirmed_count += 1
                    logger.info(
                        f"Confirmed kline: {kline.symbol} "
                        f"start={kline.start_timestamp_ms} "
                        f"OHLC={kline.open}/{kline.high}/{kline.low}/{kline.close} "
                        f"vol={kline.volume}"
                    )

                if kline_count % 10 == 0:
                    logger.info(f"RPI klines: {kline_count} (confirmed: {confirmed_count})")

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

    logger.info(f"Подписка на kline.1.{symbol} (RPI feed)...")
    await ws_client.subscribe("kline.1", symbol)

    logger.info(f"Начало записи RPI klines → WAL...")
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
        kline_log.close()
        logger.info(f"Итого RPI klines: {kline_count} (confirmed: {confirmed_count})")
        logger.info(f"Размер kline log: {kline_log_path.stat().st_size} bytes")


def main():
    parser = argparse.ArgumentParser(
        description="Bybit RPI Collector: kline.1.{SYMBOL}"
    )
    parser.add_argument(
        "--symbol",
        default="BTCUSDT",
        help="Символ для подписки. По умолчанию: BTCUSDT",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/bybit-rpi"),
        help="Каталог для WAL и .parquet файлов. По умолчанию: /tmp/bybit-rpi",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Длительность работы (секунды). По умолчанию: бесконечно",
    )

    args = parser.parse_args()

    # Feature flag
    rpi_enabled = os.getenv("RPI_ENABLED", "1") == "1"

    if rpi_enabled:
        logger.info("RPI_ENABLED=1, запуск RPI collector")
    else:
        logger.info("RPI_ENABLED=0, RPI collector отключён (baseline mode)")

    asyncio.run(
        run_rpi_collector(
            symbol=args.symbol,
            output_dir=args.output_dir,
            duration=args.duration,
            rpi_enabled=rpi_enabled,
        )
    )


if __name__ == "__main__":
    main()
