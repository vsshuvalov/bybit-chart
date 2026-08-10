#!/usr/bin/env python3
"""
Analytics Worker — изолированный процесс для analytics (Roadmap §3).

Источник: Roadmap §3 (multi-process architecture) + §5-6 (analytics modules)

Responsibilities:
- Чтение Parquet сегментов (read-only)
- Вычисление индикаторов (Delta, CVD, VWAP, Volume Profile, etc.)
- IPC subscriber — события от collector
- IPC server — запросы от API
- Independent lifecycle (crash не влияет на collector)

Architecture:
Parquet (read-only) → Analytics → IPC response → API
     ↑
Collector IPC events

Roadmap требования:
- Crash isolation (падение analytics не влияет на collector)
- Independent restart
- Read-only доступ к Parquet
- IPC для queries и events
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from packages.analytics.delta import DeltaEngine
from packages.analytics.vwap import VWAPEngine
from packages.analytics.volume_profile import VolumeProfileEngine
from packages.ipc import IPCMessage, ProcessRegistry, UDSServer
from packages.storage.parquet_reader import ParquetReader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("analytics-worker")


class AnalyticsWorker:
    """Analytics Worker — изолированный процесс для analytics.

    Roadmap §3 + §5-6: isolated analytics с IPC.
    """

    def __init__(
        self,
        data_dir: Path,
        socket_path: Path,
        registry_dir: Path,
    ):
        """Initialize analytics worker.

        Args:
            data_dir: директория с Parquet данными (read-only)
            socket_path: путь к UDS socket
            registry_dir: директория process registry
        """
        self.data_dir = data_dir
        self.socket_path = socket_path
        self.registry_dir = registry_dir

        # IPC components
        self.uds_server: UDSServer | None = None
        self.registry: ProcessRegistry | None = None

        # Storage (read-only)
        self.reader: ParquetReader | None = None

        # Analytics engines (cached instances)
        self.delta_engines: dict[str, DeltaEngine] = {}
        self.vwap_engines: dict[str, VWAPEngine] = {}
        self.volume_profile_engines: dict[str, VolumeProfileEngine] = {}

        # State
        self.running = False
        self.health_status = "starting"

    async def start(self):
        """Запустить analytics worker."""
        logger.info("Starting analytics worker...")

        # Initialize storage (read-only)
        self.reader = ParquetReader(self.data_dir)

        # Initialize IPC
        self.uds_server = UDSServer(self.socket_path, "analytics-worker")
        self.registry = ProcessRegistry(self.registry_dir)

        # Register handlers
        self.uds_server.register_handler("health", self._handle_health_check)
        self.uds_server.register_handler("request", self._handle_request)
        self.uds_server.register_handler("event", self._handle_event)

        # Start UDS server
        asyncio.create_task(self.uds_server.start())

        # Register in process registry
        self.registry.register_process("analytics", self.socket_path)

        # Wait for UDS server to start
        await asyncio.sleep(0.5)

        self.running = True
        self.health_status = "healthy"

        logger.info("Analytics worker started successfully")

        # Keep running
        await self._run_loop()

    async def _run_loop(self):
        """Main event loop."""
        try:
            while self.running:
                # Periodic cleanup (remove stale engines)
                await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("Analytics worker stopping...")
        finally:
            await self.stop()

    async def stop(self):
        """Graceful shutdown."""
        logger.info("Stopping analytics worker...")

        self.running = False
        self.health_status = "stopping"

        # Clear cached engines
        self.delta_engines.clear()
        self.vwap_engines.clear()
        self.volume_profile_engines.clear()

        # Stop UDS server
        if self.uds_server:
            await self.uds_server.stop()

        self.health_status = "stopped"
        logger.info("Analytics worker stopped")

    def _handle_health_check(self, message: IPCMessage) -> dict:
        """Handle health check request.

        Args:
            message: health check message

        Returns:
            Health status dict
        """
        return {
            "status": self.health_status,
            "process": "analytics-worker",
            "cached_engines": {
                "delta": len(self.delta_engines),
                "vwap": len(self.vwap_engines),
                "volume_profile": len(self.volume_profile_engines),
            },
        }

    def _handle_request(self, message: IPCMessage) -> dict:
        """Handle data request from API.

        Args:
            message: request message

        Returns:
            Response dict
        """
        try:
            request_type = message.payload.get("type")

            if request_type == "get_delta":
                return self._get_delta(message.payload)

            elif request_type == "get_vwap":
                return self._get_vwap(message.payload)

            elif request_type == "get_volume_profile":
                return self._get_volume_profile(message.payload)

            elif request_type == "get_symbols":
                # Read available symbols from data directory
                symbols = []
                for symbol_dir in self.data_dir.iterdir():
                    if symbol_dir.is_dir():
                        symbols.append(symbol_dir.name)
                return {"symbols": symbols}

            else:
                return {"error": f"Unknown request type: {request_type}"}

        except Exception as exc:
            logger.error(f"Request handler error: {exc}", exc_info=True)
            return {"error": str(exc)}

    def _handle_event(self, message: IPCMessage):
        """Handle event from collector.

        Args:
            message: event message
        """
        # Process event (e.g., new trade notification)
        event_type = message.payload.get("event_type")

        if event_type == "new_segment":
            # New Parquet segment published
            symbol = message.payload.get("symbol")
            logger.debug(f"New segment published: {symbol}")

            # Invalidate cached engines for this symbol
            if symbol in self.delta_engines:
                del self.delta_engines[symbol]
            if symbol in self.vwap_engines:
                del self.vwap_engines[symbol]
            if symbol in self.volume_profile_engines:
                del self.volume_profile_engines[symbol]

    def _get_delta(self, params: dict) -> dict:
        """Calculate Delta.

        Args:
            params: query parameters (symbol, start_ts, end_ts, interval_us)

        Returns:
            Delta bars dict
        """
        symbol = params["symbol"]
        start_ts = params["start_ts"]
        end_ts = params["end_ts"]
        interval_us = params["interval_us"]

        # Get or create engine
        engine_key = f"{symbol}_{interval_us}"
        if engine_key not in self.delta_engines:
            self.delta_engines[engine_key] = DeltaEngine(interval_us)

        engine = self.delta_engines[engine_key]

        # Read events from Parquet
        events = self.reader.read_range(
            symbol=symbol,
            start_ts=start_ts,
            end_ts=end_ts,
            event_type="RawTrade",
        )

        # Build Delta
        for event in events:
            engine.add_trade(event)

        # Get Delta bars
        bars = engine.to_dict_list(start_ts, end_ts)

        return {"bars": bars, "count": len(bars)}

    def _get_vwap(self, params: dict) -> dict:
        """Calculate VWAP.

        Args:
            params: query parameters

        Returns:
            VWAP bars dict
        """
        symbol = params["symbol"]
        start_ts = params["start_ts"]
        end_ts = params["end_ts"]
        interval_us = params["interval_us"]

        engine_key = f"{symbol}_{interval_us}"
        if engine_key not in self.vwap_engines:
            self.vwap_engines[engine_key] = VWAPEngine(interval_us)

        engine = self.vwap_engines[engine_key]

        events = self.reader.read_range(
            symbol=symbol,
            start_ts=start_ts,
            end_ts=end_ts,
            event_type="RawTrade",
        )

        for event in events:
            engine.add_trade(event)

        bars = engine.to_dict_list(start_ts, end_ts)

        return {"bars": bars, "count": len(bars)}

    def _get_volume_profile(self, params: dict) -> dict:
        """Calculate Volume Profile.

        Args:
            params: query parameters

        Returns:
            Volume Profile dict
        """
        symbol = params["symbol"]
        start_ts = params["start_ts"]
        end_ts = params["end_ts"]
        price_tick = params["price_tick"]

        engine_key = f"{symbol}_{price_tick}"
        if engine_key not in self.volume_profile_engines:
            self.volume_profile_engines[engine_key] = VolumeProfileEngine(price_tick)

        engine = self.volume_profile_engines[engine_key]

        events = self.reader.read_range(
            symbol=symbol,
            start_ts=start_ts,
            end_ts=end_ts,
            event_type="RawTrade",
        )

        for event in events:
            engine.add_trade(event)

        profile = engine.to_dict()

        return profile


async def main():
    """Main entry point."""
    # Parse arguments
    data_dir = Path("data")
    socket_path = Path("/tmp/bybit-analytics.sock")
    registry_dir = Path("/tmp/bybit-registry")

    if len(sys.argv) > 1:
        data_dir = Path(sys.argv[1])

    # Create worker
    worker = AnalyticsWorker(
        data_dir=data_dir,
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
