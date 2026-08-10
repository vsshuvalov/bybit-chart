#!/usr/bin/env python3
"""
Collector Worker — изолированный процесс для сбора данных (Roadmap §2-3).

Источник: Roadmap §2 (изолированный collector) + §3 (multi-process)

Responsibilities:
- WebSocket subscription к Bybit
- Сбор trades + L50 book snapshots
- Запись в WAL
- Publish событий через IPC для других процессов
- Independent lifecycle (crash isolation)

Architecture:
WebSocket → Collector → WAL → Parquet
                    ↓
                  IPC pub/sub → analytics/api

Roadmap требования:
- Crash isolation (падение analytics не влияет на collector)
- Independent restart
- Health checks через UDS
- Graceful shutdown
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from packages.bybit.collector import EventCollector
from packages.ipc import IPCMessage, ProcessRegistry, UDSServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("collector-worker")


class CollectorWorker:
    """Collector Worker — изолированный процесс для сбора данных.

    Roadmap §2-3: изолированный collector с IPC.
    """

    def __init__(
        self,
        data_dir: Path,
        symbols: list[str],
        socket_path: Path,
        registry_dir: Path,
    ):
        """Initialize collector worker.

        Args:
            data_dir: директория для хранения данных
            symbols: список символов для сбора
            socket_path: путь к UDS socket
            registry_dir: директория process registry
        """
        self.data_dir = data_dir
        self.symbols = symbols
        self.socket_path = socket_path
        self.registry_dir = registry_dir

        # IPC components
        self.uds_server: UDSServer | None = None
        self.registry: ProcessRegistry | None = None

        # Collectors
        self.collectors: dict[str, EventCollector] = {}

        # State
        self.running = False
        self.health_status = "starting"

    async def start(self):
        """Запустить collector worker."""
        logger.info(f"Starting collector worker: symbols={self.symbols}")

        # Initialize IPC
        self.uds_server = UDSServer(self.socket_path, "collector-worker")
        self.registry = ProcessRegistry(self.registry_dir)

        # Register handlers
        self.uds_server.register_handler("health", self._handle_health_check)
        self.uds_server.register_handler("request", self._handle_request)

        # Start UDS server
        asyncio.create_task(self.uds_server.start())

        # Register in process registry
        self.registry.register_process("collector", self.socket_path)

        # Wait for UDS server to start
        await asyncio.sleep(0.5)

        # Initialize collectors
        for symbol in self.symbols:
            symbol_dir = self.data_dir / symbol
            symbol_dir.mkdir(parents=True, exist_ok=True)

            collector = EventCollector(symbol_dir, symbol)
            self.collectors[symbol] = collector

            logger.info(f"Initialized collector for {symbol}")

        self.running = True
        self.health_status = "healthy"

        logger.info("Collector worker started successfully")

        # Keep running
        await self._run_loop()

    async def _run_loop(self):
        """Main event loop."""
        try:
            while self.running:
                # Health check heartbeat
                if self.health_status == "healthy":
                    # Publish heartbeat via IPC (if needed)
                    pass

                await asyncio.sleep(10)

        except asyncio.CancelledError:
            logger.info("Collector worker stopping...")
        finally:
            await self.stop()

    async def stop(self):
        """Graceful shutdown."""
        logger.info("Stopping collector worker...")

        self.running = False
        self.health_status = "stopping"

        # Close collectors
        for symbol, collector in self.collectors.items():
            logger.info(f"Closing collector for {symbol}")
            collector.close()

        # Stop UDS server
        if self.uds_server:
            await self.uds_server.stop()

        self.health_status = "stopped"
        logger.info("Collector worker stopped")

    def _handle_health_check(self, message: IPCMessage) -> dict:
        """Handle health check request.

        Args:
            message: health check message

        Returns:
            Health status dict
        """
        return {
            "status": self.health_status,
            "process": "collector-worker",
            "symbols": list(self.collectors.keys()),
            "collectors_active": len([c for c in self.collectors.values() if c]),
        }

    def _handle_request(self, message: IPCMessage) -> dict:
        """Handle generic request.

        Args:
            message: request message

        Returns:
            Response dict
        """
        request_type = message.payload.get("type")

        if request_type == "get_symbols":
            return {
                "symbols": list(self.collectors.keys()),
            }

        elif request_type == "get_stats":
            stats = {}
            for symbol, collector in self.collectors.items():
                # Get collector stats (if available)
                stats[symbol] = {
                    "active": True,
                    # Add more stats if needed
                }
            return {"stats": stats}

        else:
            return {"error": "Unknown request type"}


async def main():
    """Main entry point."""
    # Parse arguments (simple version)
    data_dir = Path("data")
    symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
    socket_path = Path("/tmp/bybit-collector.sock")
    registry_dir = Path("/tmp/bybit-registry")

    # Check command line args
    if len(sys.argv) > 1:
        data_dir = Path(sys.argv[1])
    if len(sys.argv) > 2:
        symbols = sys.argv[2].split(",")

    # Create worker
    worker = CollectorWorker(
        data_dir=data_dir,
        symbols=symbols,
        socket_path=socket_path,
        registry_dir=registry_dir,
    )

    # Setup signal handlers
    loop = asyncio.get_running_loop()

    def signal_handler(sig):
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(worker.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    # Start worker
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as exc:
        logger.error(f"Worker error: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
