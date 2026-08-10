#!/usr/bin/env python3
"""
Process Supervisor для multi-process architecture (Roadmap §3).

Источник: Roadmap §3 (process management, health checks, restart policies)

Responsibilities:
- Запуск и остановка worker процессов
- Health monitoring через IPC
- Automatic restart при crashes
- Graceful shutdown всех процессов
- Process status reporting

Workers:
- collector-worker: WebSocket → WAL
- analytics-worker: Parquet → индикаторы (TODO)
- api-server: REST + WebSocket (TODO)
- maintenance-worker: WAL → Parquet (TODO)

Roadmap требования:
- Independent process lifecycle
- Crash detection и restart
- Health checks через UDS
- Graceful shutdown cascade
"""

import asyncio
import logging
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from packages.ipc import IPCMessage, ProcessRegistry, UDSClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("supervisor")


@dataclass
class WorkerConfig:
    """Конфигурация worker процесса."""
    name: str
    command: list[str]
    restart_policy: str = "on-failure"  # "always", "on-failure", "never"
    max_restarts: int = 5
    restart_delay: float = 5.0
    health_check_interval: float = 30.0


@dataclass
class WorkerState:
    """Состояние worker процесса."""
    config: WorkerConfig
    process: subprocess.Popen | None = None
    restart_count: int = 0
    last_restart: float = 0.0
    status: str = "stopped"  # "stopped", "starting", "running", "crashed", "stopping"
    pid: int | None = None


class ProcessSupervisor:
    """Supervisor для управления worker процессами.

    Roadmap §3: process management, health checks, restart policies.
    """

    def __init__(self, registry_dir: Path):
        """Initialize supervisor.

        Args:
            registry_dir: директория process registry
        """
        self.registry_dir = registry_dir
        self.registry = ProcessRegistry(registry_dir)
        self.workers: dict[str, WorkerState] = {}
        self.running = False

    def add_worker(self, config: WorkerConfig):
        """Добавить worker для управления.

        Args:
            config: конфигурация worker
        """
        self.workers[config.name] = WorkerState(config=config)
        logger.info(f"Added worker: {config.name}")

    async def start(self):
        """Запустить supervisor и все workers."""
        logger.info("Starting supervisor...")

        self.running = True

        # Start all workers
        for name, state in self.workers.items():
            await self._start_worker(state)

        # Start monitoring loop
        await self._monitoring_loop()

    async def stop(self):
        """Graceful shutdown всех workers."""
        logger.info("Stopping supervisor...")

        self.running = False

        # Stop all workers
        for name, state in self.workers.items():
            await self._stop_worker(state)

        logger.info("Supervisor stopped")

    async def _start_worker(self, state: WorkerState):
        """Запустить worker процесс.

        Args:
            state: состояние worker
        """
        config = state.config

        logger.info(f"Starting worker: {config.name}")

        try:
            state.status = "starting"

            # Start process
            process = subprocess.Popen(
                config.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            state.process = process
            state.pid = process.pid
            state.status = "running"

            logger.info(f"Worker started: {config.name} (PID: {process.pid})")

        except Exception as exc:
            logger.error(f"Failed to start worker {config.name}: {exc}")
            state.status = "crashed"

    async def _stop_worker(self, state: WorkerState):
        """Остановить worker процесс.

        Args:
            state: состояние worker
        """
        config = state.config

        if not state.process or state.status == "stopped":
            return

        logger.info(f"Stopping worker: {config.name} (PID: {state.pid})")

        state.status = "stopping"

        try:
            # Send SIGTERM
            state.process.terminate()

            # Wait for graceful shutdown (max 10 seconds)
            try:
                state.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning(f"Worker {config.name} did not stop gracefully, killing...")
                state.process.kill()
                state.process.wait()

            state.status = "stopped"
            state.process = None
            state.pid = None

            logger.info(f"Worker stopped: {config.name}")

        except Exception as exc:
            logger.error(f"Error stopping worker {config.name}: {exc}")

    async def _monitoring_loop(self):
        """Мониторинг health workers."""
        logger.info("Starting monitoring loop...")

        while self.running:
            for name, state in self.workers.items():
                await self._check_worker_health(state)

            await asyncio.sleep(5)

    async def _check_worker_health(self, state: WorkerState):
        """Проверить health worker.

        Args:
            state: состояние worker
        """
        config = state.config

        # Check if process is alive
        if state.process and state.process.poll() is not None:
            # Process terminated
            logger.warning(f"Worker {config.name} terminated unexpectedly (exit code: {state.process.returncode})")
            state.status = "crashed"

            # Check restart policy
            if await self._should_restart(state):
                logger.info(f"Restarting worker {config.name}...")
                state.restart_count += 1
                state.last_restart = time.time()
                await asyncio.sleep(config.restart_delay)
                await self._start_worker(state)

        # Try health check via IPC
        elif state.status == "running":
            try:
                socket_path = self.registry.discover_process(config.name.replace("-worker", ""))
                if socket_path:
                    client = UDSClient(socket_path, "supervisor")
                    await client.connect()

                    health_msg = IPCMessage(
                        message_type="health",
                        payload={},
                        source="supervisor",
                    )

                    response = await asyncio.wait_for(
                        client.send_message(health_msg),
                        timeout=5.0,
                    )

                    await client.close()

                    if response:
                        logger.debug(f"Health check OK: {config.name} → {response.payload.get('status')}")

            except asyncio.TimeoutError:
                logger.warning(f"Health check timeout: {config.name}")
            except Exception as exc:
                logger.debug(f"Health check failed: {config.name} → {exc}")

    async def _should_restart(self, state: WorkerState) -> bool:
        """Определить нужно ли перезапускать worker.

        Args:
            state: состояние worker

        Returns:
            True если нужно перезапустить
        """
        config = state.config

        if config.restart_policy == "never":
            return False

        if config.restart_policy == "always":
            return state.restart_count < config.max_restarts

        if config.restart_policy == "on-failure":
            # Restart only if process exited with non-zero code
            if state.process and state.process.returncode != 0:
                return state.restart_count < config.max_restarts

        return False

    def get_status(self) -> dict:
        """Получить статус всех workers.

        Returns:
            Dict с статусом
        """
        return {
            "supervisor": "running" if self.running else "stopped",
            "workers": {
                name: {
                    "status": state.status,
                    "pid": state.pid,
                    "restart_count": state.restart_count,
                }
                for name, state in self.workers.items()
            },
        }


async def main():
    """Main entry point."""
    registry_dir = Path("/tmp/bybit-registry")
    registry_dir.mkdir(parents=True, exist_ok=True)

    supervisor = ProcessSupervisor(registry_dir)

    # Add collector worker
    supervisor.add_worker(WorkerConfig(
        name="collector-worker",
        command=[
            sys.executable,
            "workers/collector_worker.py",
            "data",
            "BTCUSDT,ETHUSDT,XRPUSDT",
        ],
        restart_policy="on-failure",
        max_restarts=5,
    ))

    # Add analytics worker
    supervisor.add_worker(WorkerConfig(
        name="analytics-worker",
        command=[
            sys.executable,
            "workers/analytics_worker.py",
            "data",
        ],
        restart_policy="on-failure",
        max_restarts=5,
    ))

    # Add API server
    supervisor.add_worker(WorkerConfig(
        name="api-server",
        command=[
            sys.executable,
            "workers/api_server.py",
        ],
        restart_policy="on-failure",
        max_restarts=5,
    ))

    # Setup signal handlers
    loop = asyncio.get_running_loop()

    def signal_handler(sig):
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(supervisor.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    # Start supervisor
    try:
        await supervisor.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as exc:
        logger.error(f"Supervisor error: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
