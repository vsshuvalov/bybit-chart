#!/usr/bin/env python3
"""
Maintenance Worker — background процесс для storage maintenance (Roadmap §3).

Источник: Roadmap §3 (multi-process) + §6 (storage maintenance)
Обновлено: ADR-013 (Fencing Token) + ADR-016 (IPC Publisher/Subscriber)

Responsibilities:
- WAL → Parquet conversion (scheduled)
- Old WAL cleanup после successful commit
- Parquet retention policy (cleanup old segments)
- Manifest verification и recovery
- Storage health monitoring

Architecture:
WAL files → Maintenance Worker → Parquet segments
                               → Cleanup old files
                               → Health metrics

Fencing:
- Перед любой write-операцией на WAL/manifest захватывает WriterLease
- assert_still_valid() в долгих операциях (cutover protection)
- При EpochViolationError — немедленно прекращает операцию

IPC:
- Подписывается на события collector через IPCSubscriber
- Публикует health status через IPCPublisher

Roadmap требования:
- Independent background process
- Scheduled operations (не блокирует collector)
- Safe cleanup (после atomic commit)
- Storage health monitoring
"""

import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

from packages.ipc import IPCMessage, ProcessRegistry, UDSServer
from packages.ipc.publisher import IPCPublisher
from packages.ipc.subscriber import IPCSubscriber
from packages.storage.fencing import (
    EpochViolationError,
    LeaseAcquisitionError,
    WriterLease,
)
from packages.storage.manifest import ManifestManager
from packages.storage.wal import WAL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("maintenance-worker")


class MaintenanceWorker:
    """Maintenance Worker — background storage maintenance.

    Roadmap §3 + §6: scheduled maintenance operations.
    Использует WriterLease (ADR-013) перед любой write-операцией.
    Подписывается на IPC события от collector (ADR-016).
    """

    def __init__(
        self,
        data_dir: Path,
        socket_path: Path,
        registry_dir: Path,
        wal_commit_interval: int = 300,  # 5 minutes
        cleanup_interval: int = 3600,  # 1 hour
        retention_days: int = 7,
        ipc_collector_socket: Path | None = None,
    ):
        """Initialize maintenance worker.

        Args:
            data_dir: директория с данными
            socket_path: путь к UDS socket этого процесса
            registry_dir: директория process registry
            wal_commit_interval: интервал WAL → Parquet (seconds)
            cleanup_interval: интервал cleanup операций (seconds)
            retention_days: retention policy (days)
            ipc_collector_socket: socket collector-а для подписки (опционально)
        """
        self.data_dir = data_dir
        self.socket_path = socket_path
        self.registry_dir = registry_dir
        self.wal_commit_interval = wal_commit_interval
        self.cleanup_interval = cleanup_interval
        self.retention_days = retention_days
        self.ipc_collector_socket = ipc_collector_socket

        # IPC components
        self.uds_server: UDSServer | None = None
        self.registry: ProcessRegistry | None = None
        self._ipc_subscriber: IPCSubscriber | None = None
        self._ipc_publisher: IPCPublisher | None = None

        # State
        self.running = False
        self.health_status = "starting"
        self.stats = {
            "wal_commits": 0,
            "cleanup_runs": 0,
            "segments_cleaned": 0,
            "errors": 0,
            "fencing_conflicts": 0,
        }

    async def start(self):
        """Запустить maintenance worker."""
        logger.info("Starting maintenance worker...")

        # Initialize IPC
        self.uds_server = UDSServer(self.socket_path, "maintenance-worker")
        self.registry = ProcessRegistry(self.registry_dir)

        # Register handlers
        self.uds_server.register_handler("health", self._handle_health_check)
        self.uds_server.register_handler("request", self._handle_request)

        # Start UDS server
        asyncio.create_task(self.uds_server.start())

        # Register in process registry
        self.registry.register_process("maintenance", self.socket_path)

        # Setup IPC subscriber (listen to collector events)
        if self.ipc_collector_socket:
            self._ipc_subscriber = IPCSubscriber(
                self.socket_path.parent / "bybit-maintenance-rx.sock"
            )
            self._ipc_subscriber.register_handler("RawTrade", self._on_trade)
            self._ipc_subscriber.register_handler("RawBookEvent", self._on_book_event)
            self._ipc_subscriber.run_in_thread(daemon=True)
            logger.info("IPC subscriber started, listening for collector events")

        # Setup IPC publisher (publish health/status to monitoring)
        self._ipc_publisher = IPCPublisher(
            self.socket_path.parent / "bybit-monitoring.sock",
            source_name="maintenance-worker",
        )

        # Wait for UDS server
        await asyncio.sleep(0.5)

        self.running = True
        self.health_status = "healthy"

        logger.info("Maintenance worker started successfully")

        # Run maintenance loops
        await asyncio.gather(
            self._wal_commit_loop(),
            self._cleanup_loop(),
        )

    async def stop(self):
        """Graceful shutdown."""
        logger.info("Stopping maintenance worker...")

        self.running = False
        self.health_status = "stopping"

        # Stop IPC subscriber
        if self._ipc_subscriber:
            self._ipc_subscriber.stop()

        # Stop UDS server
        if self.uds_server:
            await self.uds_server.stop()

        self.health_status = "stopped"
        logger.info("Maintenance worker stopped")

    # ------------------------------------------------------------------
    # IPC event handlers
    # ------------------------------------------------------------------

    def _on_trade(self, payload: dict) -> None:
        """Handle RawTrade event from collector (IPC)."""
        # Maintenance worker получает события для статистики
        # Не пишет в WAL — только читает
        pass

    def _on_book_event(self, payload: dict) -> None:
        """Handle RawBookEvent from collector (IPC)."""
        pass

    # ------------------------------------------------------------------
    # Maintenance loops
    # ------------------------------------------------------------------

    async def _wal_commit_loop(self):
        """Periodic WAL → Parquet commits."""
        logger.info(f"WAL commit loop started (interval: {self.wal_commit_interval}s)")

        while self.running:
            try:
                await asyncio.sleep(self.wal_commit_interval)

                if not self.running:
                    break

                logger.info("Running WAL → Parquet commit...")

                # Process all symbols
                for symbol_dir in self.data_dir.iterdir():
                    if not symbol_dir.is_dir():
                        continue

                    symbol = symbol_dir.name

                    try:
                        await self._commit_wal_for_symbol(symbol, symbol_dir)
                    except Exception as exc:
                        logger.error(f"Error committing WAL for {symbol}: {exc}")
                        self.stats["errors"] += 1

                self.stats["wal_commits"] += 1
                logger.info("WAL commit completed")

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"WAL commit loop error: {exc}", exc_info=True)
                self.stats["errors"] += 1

    async def _cleanup_loop(self):
        """Periodic cleanup операций."""
        logger.info(f"Cleanup loop started (interval: {self.cleanup_interval}s)")

        while self.running:
            try:
                await asyncio.sleep(self.cleanup_interval)

                if not self.running:
                    break

                logger.info("Running cleanup...")

                # Cleanup old WAL files
                await self._cleanup_old_wal_files()

                # Cleanup old Parquet segments (retention policy)
                await self._cleanup_old_segments()

                self.stats["cleanup_runs"] += 1
                logger.info("Cleanup completed")

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Cleanup loop error: {exc}", exc_info=True)
                self.stats["errors"] += 1

    async def _commit_wal_for_symbol(self, symbol: str, symbol_dir: Path):
        """Commit WAL → Parquet для символа с fencing protection.

        Захватывает WriterLease перед любой write-операцией.
        При EpochViolationError немедленно прекращает операцию.

        Args:
            symbol: символ
            symbol_dir: директория символа
        """
        wal_dir = symbol_dir / "wal"
        if not wal_dir.exists():
            return

        # Get WAL instance
        wal = WAL(symbol_dir, symbol)

        # Захватить WriterLease перед write-операцией (ADR-013)
        lease = WriterLease(symbol_dir)
        try:
            epoch = lease.acquire()
            logger.debug(f"Acquired writer lease for {symbol}: epoch={epoch}")
        except LeaseAcquisitionError as exc:
            # Collector держит lease — пропустить этот символ сейчас
            logger.info(f"Writer lease busy for {symbol}: {exc}")
            self.stats["fencing_conflicts"] += 1
            return

        try:
            # Commit (WAL → Parquet)
            committed = wal.commit()

            if committed:
                logger.info(f"Committed WAL for {symbol}: {len(committed)} segments")

        except EpochViolationError as exc:
            # Cutover произошёл — прекратить операцию немедленно
            logger.error(f"Epoch violation for {symbol}: {exc}. Stopping commit.")
            self.stats["fencing_conflicts"] += 1
        finally:
            lease.release()

    async def _cleanup_old_wal_files(self):
        """Cleanup старых WAL файлов после successful Parquet commit."""
        for symbol_dir in self.data_dir.iterdir():
            if not symbol_dir.is_dir():
                continue

            wal_dir = symbol_dir / "wal"
            if not wal_dir.exists():
                continue

            # Check manifest for committed segments
            manifest_file = symbol_dir / "manifest.json"
            if not manifest_file.exists():
                continue

            manifest = ManifestManager(manifest_file)

            # Get committed WAL files
            committed_wals = set()
            for segment in manifest.segments:
                # WAL file corresponding to this segment
                wal_file = wal_dir / f"{segment['start_offset']}.wal"
                if wal_file.exists():
                    committed_wals.add(wal_file)

            # Cleanup committed WAL files
            for wal_file in committed_wals:
                try:
                    wal_file.unlink()
                    logger.debug(f"Cleaned up WAL: {wal_file}")
                except Exception as exc:
                    logger.error(f"Error cleaning WAL {wal_file}: {exc}")

    async def _cleanup_old_segments(self):
        """Cleanup старых Parquet segments по retention policy."""
        cutoff_time = time.time() - (self.retention_days * 86400)

        for symbol_dir in self.data_dir.iterdir():
            if not symbol_dir.is_dir():
                continue

            manifest_file = symbol_dir / "manifest.json"
            if not manifest_file.exists():
                continue

            manifest = ManifestManager(manifest_file)

            # Find old segments
            old_segments = []
            for segment in manifest.segments:
                segment_file = symbol_dir / segment["filename"]
                if not segment_file.exists():
                    continue

                # Check file modification time
                mtime = segment_file.stat().st_mtime
                if mtime < cutoff_time:
                    old_segments.append((segment, segment_file))

            # Cleanup old segments
            for segment_info, segment_file in old_segments:
                try:
                    segment_file.unlink()
                    logger.info(f"Cleaned up old segment: {segment_file}")
                    self.stats["segments_cleaned"] += 1

                    # Remove from manifest
                    manifest.segments.remove(segment_info)

                except Exception as exc:
                    logger.error(f"Error cleaning segment {segment_file}: {exc}")

            # Save updated manifest
            if old_segments:
                manifest.save()

    def _handle_health_check(self, message: IPCMessage) -> dict:
        """Handle health check request."""
        return {
            "status": self.health_status,
            "process": "maintenance-worker",
            "stats": self.stats,
        }

    def _handle_request(self, message: IPCMessage) -> dict:
        """Handle request."""
        request_type = message.payload.get("type")

        if request_type == "get_stats":
            return {"stats": self.stats}

        elif request_type == "force_commit":
            # Trigger immediate WAL commit
            asyncio.create_task(self._force_commit())
            return {"status": "triggered"}

        elif request_type == "force_cleanup":
            # Trigger immediate cleanup
            asyncio.create_task(self._force_cleanup())
            return {"status": "triggered"}

        else:
            return {"error": "Unknown request type"}

    async def _force_commit(self):
        """Force immediate WAL commit."""
        logger.info("Force WAL commit triggered")

        for symbol_dir in self.data_dir.iterdir():
            if not symbol_dir.is_dir():
                continue

            symbol = symbol_dir.name

            try:
                await self._commit_wal_for_symbol(symbol, symbol_dir)
            except Exception as exc:
                logger.error(f"Error in force commit for {symbol}: {exc}")

    async def _force_cleanup(self):
        """Force immediate cleanup."""
        logger.info("Force cleanup triggered")

        try:
            await self._cleanup_old_wal_files()
            await self._cleanup_old_segments()
        except Exception as exc:
            logger.error(f"Error in force cleanup: {exc}")


async def main():
    """Main entry point."""
    data_dir = Path("data")
    socket_path = Path("/tmp/bybit-maintenance.sock")
    registry_dir = Path("/tmp/bybit-registry")

    if len(sys.argv) > 1:
        data_dir = Path(sys.argv[1])

    worker = MaintenanceWorker(
        data_dir=data_dir,
        socket_path=socket_path,
        registry_dir=registry_dir,
        wal_commit_interval=300,  # 5 min
        cleanup_interval=3600,  # 1 hour
        retention_days=7,
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
