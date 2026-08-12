#!/usr/bin/env python3
"""
Process Supervisor для bybit-chart 4-process architecture (Roadmap Этап 4.3).

Responsibilities:
- Start/stop/restart всех 4 workers
- Health monitoring с auto-restart при сбоях
- Graceful shutdown sequence (SIGTERM → wait → SIGKILL)
- Dependency ordering (collector first, API last)
- Status reporting и metrics
- Log aggregation

Architecture:
    Supervisor
    ├─ collector-worker (запускается первым)
    ├─ orderflow-worker (после collector готов)
    ├─ analytics-worker (после orderflow готов)
    └─ api-server (запускается последним)

Usage:
    python3 supervisor.py start
    python3 supervisor.py stop
    python3 supervisor.py restart
    python3 supervisor.py status
"""

import asyncio
import json
import logging
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("supervisor")


class ProcessState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    CRASHED = "crashed"


@dataclass
class ProcessConfig:
    """Configuration для одного worker process."""
    name: str
    command: list[str]
    socket_path: Path
    log_path: Path
    startup_timeout: int = 30  # seconds
    health_check_interval: int = 10  # seconds
    restart_on_failure: bool = True
    max_restarts: int = 5
    restart_window: int = 300  # 5 minutes


class ManagedProcess:
    """Managed worker process с health monitoring."""

    def __init__(self, config: ProcessConfig):
        self.config = config
        self.state = ProcessState.STOPPED
        self.process: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.restarts = 0
        self.restart_times: list[float] = []
        self.last_health_check = 0.0

    def start(self) -> bool:
        """Start the process."""
        if self.state in [ProcessState.STARTING, ProcessState.RUNNING]:
            logger.warning(f"{self.config.name}: already running")
            return False

        logger.info(f"{self.config.name}: starting...")
        self.state = ProcessState.STARTING

        try:
            log_file = open(self.config.log_path, "a")
            self.process = subprocess.Popen(
                self.config.command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                preexec_fn=lambda: signal.signal(signal.SIGTERM, signal.SIG_DFL),
            )
            self.pid = self.process.pid
            logger.info(f"{self.config.name}: started (PID {self.pid})")
            self.state = ProcessState.RUNNING
            return True
        except Exception as e:
            logger.error(f"{self.config.name}: failed to start: {e}")
            self.state = ProcessState.CRASHED
            return False

    def stop(self, force: bool = False) -> bool:
        """Stop the process."""
        if self.state == ProcessState.STOPPED:
            return True

        logger.info(f"{self.config.name}: stopping...")
        self.state = ProcessState.STOPPING

        if not self.process or not self.pid:
            self.state = ProcessState.STOPPED
            return True

        try:
            if force:
                self.process.kill()  # SIGKILL
            else:
                self.process.terminate()  # SIGTERM
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning(f"{self.config.name}: timeout, force killing")
                    self.process.kill()
                    self.process.wait(timeout=5)

            self.state = ProcessState.STOPPED
            self.process = None
            self.pid = None
            logger.info(f"{self.config.name}: stopped")
            return True
        except Exception as e:
            logger.error(f"{self.config.name}: failed to stop: {e}")
            return False

    def health_check(self) -> bool:
        """Check if process is healthy via UDS health check."""
        now = time.time()
        if now - self.last_health_check < self.config.health_check_interval:
            return self.state == ProcessState.RUNNING

        self.last_health_check = now

        # Check if process is alive
        if not self.process or self.process.poll() is not None:
            logger.warning(f"{self.config.name}: process died")
            self.state = ProcessState.CRASHED
            return False

        # Check UDS socket
        if not self.config.socket_path.exists():
            logger.warning(f"{self.config.name}: socket not found")
            self.state = ProcessState.UNHEALTHY
            return False

        # UDS health check
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect(str(self.config.socket_path))

            request = {"type": "health"}
            sock.sendall(json.dumps(request).encode() + b"\n")

            data = sock.recv(4096)
            sock.close()

            response = json.loads(data.decode())
            status = response.get("status", "unknown")

            if status in ["healthy", "ok"]:
                self.state = ProcessState.RUNNING
                return True
            else:
                logger.warning(f"{self.config.name}: unhealthy status: {status}")
                self.state = ProcessState.UNHEALTHY
                return False

        except Exception as e:
            logger.warning(f"{self.config.name}: health check failed: {e}")
            self.state = ProcessState.UNHEALTHY
            return False

    def should_restart(self) -> bool:
        """Check if process should be auto-restarted."""
        if not self.config.restart_on_failure:
            return False

        if self.state not in [ProcessState.CRASHED, ProcessState.UNHEALTHY]:
            return False

        # Check restart rate limit
        now = time.time()
        self.restart_times = [t for t in self.restart_times if now - t < self.config.restart_window]

        if len(self.restart_times) >= self.config.max_restarts:
            logger.error(
                f"{self.config.name}: restart rate limit exceeded "
                f"({self.config.max_restarts} restarts in {self.config.restart_window}s)"
            )
            return False

        return True

    def restart(self) -> bool:
        """Restart the process."""
        logger.info(f"{self.config.name}: restarting...")
        self.stop()
        time.sleep(2)
        success = self.start()
        if success:
            self.restarts += 1
            self.restart_times.append(time.time())
        return success


class ProcessSupervisor:
    """Supervisor для управления всеми 4 workers."""

    def __init__(self, data_dir: Path, registry_dir: Path):
        self.data_dir = data_dir
        self.registry_dir = registry_dir
        self.running = False

        # Define all processes in dependency order
        self.processes = {
            "collector": ManagedProcess(ProcessConfig(
                name="collector",
                command=["python3", "workers/collector_worker.py"],
                socket_path=Path("/tmp/bybit-collector.sock"),
                log_path=Path("/tmp/bybit-collector.log"),
            )),
            "orderflow": ManagedProcess(ProcessConfig(
                name="orderflow",
                command=["python3", "workers/orderflow_worker.py"],
                socket_path=Path("/tmp/bybit-orderflow.sock"),
                log_path=Path("/tmp/bybit-orderflow.log"),
            )),
            "analytics": ManagedProcess(ProcessConfig(
                name="analytics",
                command=["python3", "workers/analytics_worker.py"],
                socket_path=Path("/tmp/bybit-analytics.sock"),
                log_path=Path("/tmp/bybit-analytics.log"),
            )),
            "api": ManagedProcess(ProcessConfig(
                name="api",
                command=["python3", "-m", "uvicorn", "packages.api.app:app", "--host", "0.0.0.0", "--port", "8000"],
                socket_path=Path("/tmp/bybit-api.sock"),
                log_path=Path("/tmp/bybit-api.log"),
            )),
        }

        # Dependency order для startup
        self.startup_order = ["collector", "orderflow", "analytics", "api"]

        # Shutdown order (reverse)
        self.shutdown_order = list(reversed(self.startup_order))

    def start_all(self) -> bool:
        """Start all processes in dependency order."""
        logger.info("Starting all processes...")

        for name in self.startup_order:
            proc = self.processes[name]
            if not proc.start():
                logger.error(f"Failed to start {name}, aborting startup")
                self.stop_all()
                return False

            # Wait for readiness
            logger.info(f"Waiting for {name} to be ready...")
            for _ in range(proc.config.startup_timeout):
                time.sleep(1)
                if proc.config.socket_path.exists():
                    if proc.health_check():
                        break
            else:
                logger.error(f"{name} failed to become ready, aborting startup")
                self.stop_all()
                return False

        logger.info("All processes started successfully")
        self.running = True
        return True

    def stop_all(self, force: bool = False) -> bool:
        """Stop all processes in reverse dependency order."""
        logger.info("Stopping all processes...")

        success = True
        for name in self.shutdown_order:
            proc = self.processes[name]
            if not proc.stop(force=force):
                success = False

        self.running = False
        logger.info("All processes stopped")
        return success

    def restart_all(self) -> bool:
        """Restart all processes."""
        logger.info("Restarting all processes...")
        self.stop_all()
        time.sleep(2)
        return self.start_all()

    def get_status(self) -> dict:
        """Get status of all processes."""
        return {
            name: {
                "state": proc.state.value,
                "pid": proc.pid,
                "restarts": proc.restarts,
            }
            for name, proc in self.processes.items()
        }

    async def monitor_loop(self):
        """Main monitoring loop."""
        logger.info("Starting monitor loop...")

        while self.running:
            await asyncio.sleep(5)

            for name, proc in self.processes.items():
                # Health check
                healthy = proc.health_check()

                if not healthy and proc.should_restart():
                    logger.warning(f"{name}: auto-restarting...")
                    proc.restart()

    def signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
        self.stop_all()
        sys.exit(0)


async def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: supervisor.py {start|stop|restart|status}")
        sys.exit(1)

    command = sys.argv[1]

    data_dir = Path("data")
    registry_dir = Path("/tmp/bybit-registry")
    registry_dir.mkdir(exist_ok=True)

    supervisor = ProcessSupervisor(data_dir, registry_dir)

    # Setup signal handlers
    signal.signal(signal.SIGTERM, supervisor.signal_handler)
    signal.signal(signal.SIGINT, supervisor.signal_handler)

    if command == "start":
        if supervisor.start_all():
            await supervisor.monitor_loop()
        else:
            sys.exit(1)

    elif command == "stop":
        supervisor.stop_all()

    elif command == "restart":
        if supervisor.restart_all():
            await supervisor.monitor_loop()
        else:
            sys.exit(1)

    elif command == "status":
        status = supervisor.get_status()
        print(json.dumps(status, indent=2))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
