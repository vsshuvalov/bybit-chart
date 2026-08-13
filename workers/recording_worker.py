#!/usr/bin/env python3
"""
Recording Worker - записывает live trades в PostgreSQL.

Usage:
    python workers/recording_worker.py BTCUSDT

Подключается к Bybit WebSocket, получает trades и записывает в таблицу raw_trades.
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime

import psycopg2
import websocket

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class RecordingWorker:
    """Worker для записи trades в PostgreSQL."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.running = True
        self.ws = None
        self.db_conn = None

        # Database connection
        self.db_config = {
            "host": os.environ.get("POSTGRES_HOST", "localhost"),
            "port": int(os.environ.get("POSTGRES_PORT", 5432)),
            "database": os.environ.get("POSTGRES_DB", "bybit_platform"),
            "user": os.environ.get("POSTGRES_USER", "bybit"),
            "password": os.environ.get("POSTGRES_PASSWORD", "bybit"),
        }

    def connect_db(self):
        """Подключиться к PostgreSQL."""
        try:
            self.db_conn = psycopg2.connect(**self.db_config)
            self.db_conn.autocommit = True
            logger.info(f"Connected to PostgreSQL: {self.db_config['database']}")

            # Создать таблицу если не существует
            with self.db_conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS raw_trades (
                        id BIGSERIAL PRIMARY KEY,
                        symbol VARCHAR(20) NOT NULL,
                        trade_id VARCHAR(50) NOT NULL,
                        price NUMERIC(20, 8) NOT NULL,
                        quantity NUMERIC(20, 8) NOT NULL,
                        side VARCHAR(10) NOT NULL,
                        timestamp_ms BIGINT NOT NULL,
                        recorded_at TIMESTAMP DEFAULT NOW(),
                        UNIQUE(symbol, trade_id)
                    )
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_raw_trades_symbol_time
                    ON raw_trades(symbol, timestamp_ms DESC)
                """)
            logger.info("Database schema ready")

        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    def insert_trade(self, trade: dict):
        """Записать trade в базу."""
        try:
            with self.db_conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO raw_trades (symbol, trade_id, price, quantity, side, timestamp_ms)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol, trade_id) DO NOTHING
                    """,
                    (
                        trade["symbol"],
                        trade["trade_id"],
                        trade["price"],
                        trade["quantity"],
                        trade["side"],
                        trade["timestamp_ms"],
                    ),
                )
        except Exception as e:
            logger.error(f"Failed to insert trade: {e}")

    def on_message(self, ws, message):
        """Обработать сообщение от WebSocket."""
        try:
            data = json.loads(message)

            # Bybit format: {"topic": "publicTrade.BTCUSDT", "data": [...]}
            if data.get("topic") and data.get("topic").startswith("publicTrade"):
                trades = data.get("data", [])

                for trade_data in trades:
                    trade = {
                        "symbol": trade_data.get("s"),
                        "trade_id": trade_data.get("i"),
                        "price": float(trade_data.get("p")),
                        "quantity": float(trade_data.get("v")),
                        "side": trade_data.get("S"),  # Buy/Sell
                        "timestamp_ms": int(trade_data.get("T")),
                    }

                    self.insert_trade(trade)

                if trades:
                    logger.info(f"Recorded {len(trades)} trades for {self.symbol}")

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def on_error(self, ws, error):
        """Обработать ошибку WebSocket."""
        logger.error(f"WebSocket error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        """Обработать закрытие WebSocket."""
        logger.warning(f"WebSocket closed: {close_status_code} - {close_msg}")

    def on_open(self, ws):
        """Обработать открытие WebSocket."""
        logger.info(f"WebSocket opened for {self.symbol}")

        # Subscribe to public trades
        subscribe_msg = {
            "op": "subscribe",
            "args": [f"publicTrade.{self.symbol}"],
        }
        ws.send(json.dumps(subscribe_msg))
        logger.info(f"Subscribed to publicTrade.{self.symbol}")

    def run(self):
        """Запустить worker."""
        logger.info(f"Starting recording worker for {self.symbol}")

        # Подключиться к базе
        self.connect_db()

        # Подключиться к Bybit WebSocket
        ws_url = "wss://stream.bybit.com/v5/public/linear"

        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    ws_url,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                    on_open=self.on_open,
                )

                logger.info(f"Connecting to {ws_url}")
                self.ws.run_forever()

                # Если вышли из цикла - переподключиться через 5 секунд
                if self.running:
                    logger.info("Reconnecting in 5 seconds...")
                    time.sleep(5)

            except KeyboardInterrupt:
                logger.info("Stopping worker...")
                self.running = False
                break

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                if self.running:
                    time.sleep(5)

        # Закрыть соединения
        if self.ws:
            self.ws.close()

        if self.db_conn:
            self.db_conn.close()

        logger.info(f"Recording worker stopped for {self.symbol}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python recording_worker.py SYMBOL")
        print("Example: python recording_worker.py BTCUSDT")
        sys.exit(1)

    symbol = sys.argv[1]
    worker = RecordingWorker(symbol)

    try:
        worker.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
