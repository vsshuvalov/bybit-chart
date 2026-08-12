#!/usr/bin/env python3
"""
Analytics Worker — изолированный процесс для analytics (Roadmap §3, Этап 4).

Источник: Roadmap §3 (multi-process architecture) + §5-6 (analytics modules)

Responsibilities:
- Чтение Parquet сегментов (read-only)
- WAL catch-up: live tail [published_offset → durable_offset]
- Вычисление индикаторов (Delta, CVD, VWAP, Volume Profile, etc.)
- IPC subscriber — события от collector (новые сегменты)
- IPC server — запросы от API
- Independent lifecycle (crash не влияет на collector)

WAL catch-up (Этап 4):
    Parquet покрывает [0 → published_offset].
    WAL покрывает [published_offset → durable_offset].
    analytics читает оба источника для каждого запроса.

Roadmap требования:
- Crash isolation (падение analytics не влияет на collector)
- Independent restart
- Read-only доступ к Parquet + WAL
- IPC для queries и events
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from packages.analytics.delta import aggregate_delta_by_interval
from packages.analytics.vwap import aggregate_vwap_by_interval
from packages.analytics.volume_profile import calculate_volume_profile
from packages.bybit.collector import deserialize_event_from_payload
from packages.ipc import IPCMessage, ProcessRegistry, UDSServer
from packages.ipc.subscriber import IPCSubscriber
from packages.storage.manifest import Manifest
from packages.storage.parquet_reader import ParquetReader
from packages.storage.wal import WalPartition

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("analytics-worker")


class AnalyticsWorker:
    """Analytics Worker — изолированный процесс для analytics.

    Roadmap §3 + §5-6: isolated analytics с IPC.
    WAL catch-up (Этап 4): читает Parquet + live WAL tail.
    """

    def __init__(
        self,
        data_dir: Path,
        socket_path: Path,
        registry_dir: Path,
    ):
        self.data_dir = data_dir
        self.socket_path = socket_path
        self.registry_dir = registry_dir

        # IPC components
        self.uds_server: UDSServer | None = None
        self.registry: ProcessRegistry | None = None
        self._ipc_subscriber: IPCSubscriber | None = None

        # Storage (read-only)
        self.reader: ParquetReader | None = None

        # State
        self.running = False
        self.health_status = "starting"
        self._invalidated_symbols: set[str] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Запустить analytics worker."""
        logger.info("Starting analytics worker...")

        self.reader = ParquetReader(self.data_dir)

        self.uds_server = UDSServer(self.socket_path, "analytics-worker")
        self.registry = ProcessRegistry(self.registry_dir)

        self.uds_server.register_handler("health", self._handle_health_check)
        self.uds_server.register_handler("request", self._handle_request)
        self.uds_server.register_handler("event", self._handle_event)

        asyncio.create_task(self.uds_server.start())

        # IPC subscriber — слушаем события от collector
        rx_sock = self.socket_path.parent / "bybit-analytics-rx.sock"
        self._ipc_subscriber = IPCSubscriber(rx_sock)
        self._ipc_subscriber.register_handler("new_segment", self._on_new_segment)
        self._ipc_subscriber.run_in_thread(daemon=True)

        self.registry.register_process("analytics", self.socket_path)

        # Реальная readiness: ждём пока socket появится в registry
        deadline = 30
        for _ in range(deadline * 10):
            await asyncio.sleep(0.1)
            if self.registry.discover_process("analytics"):
                break

        self.running = True
        self.health_status = "healthy"
        logger.info("Analytics worker started successfully")

        await self._run_loop()

    async def _run_loop(self):
        """Periodic maintenance: сброс stalе engine кешей."""
        try:
            while self.running:
                await asyncio.sleep(60)
                # Сбросить кеши для символов, получивших новые сегменты
                for sym in list(self._invalidated_symbols):
                    self._invalidated_symbols.discard(sym)
                    logger.debug(f"Cache invalidated for {sym}")
        except asyncio.CancelledError:
            logger.info("Analytics worker stopping...")
        finally:
            await self.stop()

    async def stop(self):
        """Graceful shutdown."""
        logger.info("Stopping analytics worker...")
        self.running = False
        self.health_status = "stopping"

        if self._ipc_subscriber:
            self._ipc_subscriber.stop()

        if self.uds_server:
            await self.uds_server.stop()

        self.health_status = "stopped"
        logger.info("Analytics worker stopped")

    # ------------------------------------------------------------------
    # IPC event handlers
    # ------------------------------------------------------------------

    def _on_new_segment(self, payload: dict) -> None:
        """IPC: collector опубликовал новый Parquet сегмент."""
        sym = payload.get("symbol", "")
        if sym:
            self._invalidated_symbols.add(sym)

    def _handle_health_check(self, message: IPCMessage) -> dict:
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
        try:
            request_type = message.payload.get("type")
            if request_type == "get_delta":
                return self._get_delta(message.payload)
            elif request_type == "get_vwap":
                return self._get_vwap(message.payload)
            elif request_type == "get_volume_profile":
                return self._get_volume_profile(message.payload)
            elif request_type == "get_symbols":
                symbols = [d.name for d in self.data_dir.iterdir() if d.is_dir()]
                return {"symbols": symbols}
            else:
                return {"error": f"Unknown request type: {request_type}"}
        except Exception as exc:
            logger.error(f"Request handler error: {exc}", exc_info=True)
            return {"error": str(exc)}

    def _handle_event(self, message: IPCMessage):
        """IPC: обработать нотификацию нового сегмента (legacy handler)."""
        if message.payload.get("event_type") == "new_segment":
            sym = message.payload.get("symbol", "")
            if sym:
                self._invalidated_symbols.add(sym)

    # ------------------------------------------------------------------
    # WAL catch-up helper (Этап 4)
    # ------------------------------------------------------------------

    def _read_wal_tail(self, symbol: str) -> list:
        """Прочитать live WAL tail после published_offset.

        Возвращает список десериализованных событий от published_offset
        до durable_offset. Эти события ещё не в Parquet.

        Args:
            symbol: торговая пара

        Returns:
            список RawTrade | BookCheckpoint из WAL tail
        """
        symbol_dir = self.data_dir / symbol
        manifest_path = symbol_dir / "manifest.json"
        wal_dir = symbol_dir

        if not manifest_path.exists():
            return []

        try:
            manifest = Manifest(manifest_path)
            manifest.load()
            published = manifest.published_offset()
        except Exception as exc:
            logger.debug(f"Cannot load manifest for {symbol}: {exc}")
            return []

        # Попробовать несколько путей к WAL partition
        wal_candidates = [
            wal_dir / "wal" / "p0",
            wal_dir / "p0",
            wal_dir,
        ]
        wal_partition = None
        for candidate in wal_candidates:
            if candidate.exists() and any(candidate.glob("*.wal")):
                wal_partition = candidate
                break

        if wal_partition is None:
            return []

        try:
            wal = WalPartition(wal_partition, partition_id=symbol)
            wal.recover()

            if wal.durable_offset <= published:
                return []  # WAL tail пуст — всё уже в Parquet

            frames = wal.read_range(published, wal.durable_offset)
            events = []
            for frame in frames:
                try:
                    events.append(deserialize_event_from_payload(frame.payload))
                except Exception:
                    pass  # skip corrupted frames
            return events

        except Exception as exc:
            logger.debug(f"WAL tail read error for {symbol}: {exc}")
            return []

    # ------------------------------------------------------------------
    # Analytics computations
    # ------------------------------------------------------------------

    def _get_delta(self, params: dict) -> dict:
        symbol = params["symbol"]
        start_ts = params["start_ts"]
        end_ts = params["end_ts"]
    def _get_delta(self, params: dict) -> dict:
        symbol = params["symbol"]
        start_ts = params["start_ts"]
        end_ts = params["end_ts"]
        interval_us = params["interval_us"]

        # Parquet part
        events = self.reader.read_range(
            symbol=symbol, start_ts=start_ts, end_ts=end_ts, event_type="RawTrade",
        )

        # WAL catch-up: добавить live tail
        from contracts.schemas import RawTrade
        wal_events = self._read_wal_tail(symbol)
        for event in wal_events:
            if isinstance(event, RawTrade):
                ts = event.exchange_timestamp_ms * 1000
                if start_ts <= ts < end_ts:
                    events.append(event.model_dump(mode="json"))

        bars = aggregate_delta_by_interval(events, interval_us)
        return {"bars": bars, "count": len(bars)}

    def _get_vwap(self, params: dict) -> dict:
        symbol = params["symbol"]
        start_ts = params["start_ts"]
        end_ts = params["end_ts"]
        interval_us = params["interval_us"]

        events = self.reader.read_range(
            symbol=symbol, start_ts=start_ts, end_ts=end_ts, event_type="RawTrade",
        )

        from contracts.schemas import RawTrade
        for event in self._read_wal_tail(symbol):
            if isinstance(event, RawTrade):
                ts = event.exchange_timestamp_ms * 1000
                if start_ts <= ts < end_ts:
                    events.append(event.model_dump(mode="json"))

        bars = aggregate_vwap_by_interval(events, interval_us)
        return {"bars": bars, "count": len(bars)}

    def _get_volume_profile(self, params: dict) -> dict:
        symbol = params["symbol"]
        start_ts = params["start_ts"]
        end_ts = params["end_ts"]
        price_tick = params["price_tick"]

        events = self.reader.read_range(
            symbol=symbol, start_ts=start_ts, end_ts=end_ts, event_type="RawTrade",
        )

        from contracts.schemas import RawTrade
        for event in self._read_wal_tail(symbol):
            if isinstance(event, RawTrade):
                ts = event.exchange_timestamp_ms * 1000
                if start_ts <= ts < end_ts:
                    events.append(event.model_dump(mode="json"))

        return calculate_volume_profile(events, price_tick)


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
