#!/usr/bin/env python3
"""
Prometheus Metrics Exporter для bybit-chart workers (Этап 5.1.2).

Проксирует UDS запросы в HTTP endpoints для Prometheus scraping.

Architecture:
    Prometheus → HTTP :9100-9103 → UDS sockets → Workers

Ports:
    9100 - collector-worker
    9101 - analytics-worker
    9102 - orderflow-worker
    9103 - maintenance-worker
    (8000 - api-server экспортирует напрямую через /metrics)
"""

import asyncio
import json
import logging
import socket
from pathlib import Path

from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("metrics-exporter")


class UDSMetricsProxy:
    """Proxy UDS metrics to HTTP для Prometheus."""

    def __init__(self, socket_path: Path, service_name: str):
        self.socket_path = socket_path
        self.service_name = service_name

    async def get_metrics(self) -> str:
        """Fetch metrics from UDS socket."""
        try:
            # Connect to UDS
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(str(self.socket_path))

            # Send request
            request = {
                "type": "request",
                "payload": {"type": "get_metrics"},
            }
            sock.sendall(json.dumps(request).encode() + b"\n")

            # Receive response
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in chunk:
                    break

            sock.close()

            # Parse response
            response = json.loads(data.decode())
            if "metrics" in response:
                return response["metrics"]
            else:
                logger.error(f"{self.service_name}: No metrics in response")
                return f"# ERROR: No metrics from {self.service_name}\n"

        except FileNotFoundError:
            logger.warning(f"{self.service_name}: Socket not found at {self.socket_path}")
            return f"# ERROR: {self.service_name} socket not found\n"
        except Exception as exc:
            logger.error(f"{self.service_name}: Error fetching metrics: {exc}")
            return f"# ERROR: {self.service_name} - {exc}\n"


async def handle_metrics(request, proxy: UDSMetricsProxy):
    """HTTP handler для /metrics endpoint."""
    metrics = await proxy.get_metrics()
    return web.Response(text=metrics, content_type="text/plain; version=0.0.4")


async def create_exporter(port: int, socket_path: Path, service_name: str):
    """Create HTTP server для одного worker."""
    app = web.Application()
    proxy = UDSMetricsProxy(socket_path, service_name)

    app.router.add_get("/metrics", lambda req: handle_metrics(req, proxy))
    app.router.add_get("/health", lambda req: web.Response(text="ok"))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info(f"Exporter for {service_name} started on port {port}")
    return runner


async def main():
    """Start all exporters."""
    exporters = [
        (9100, Path("/tmp/bybit-collector.sock"), "collector-worker"),
        (9101, Path("/tmp/bybit-analytics.sock"), "analytics-worker"),
        (9102, Path("/tmp/bybit-orderflow.sock"), "orderflow-worker"),
        (9103, Path("/tmp/bybit-maintenance.sock"), "maintenance-worker"),
    ]

    runners = []
    for port, socket_path, service_name in exporters:
        runner = await create_exporter(port, socket_path, service_name)
        runners.append(runner)

    logger.info("All metrics exporters started. Press Ctrl+C to stop.")

    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        for runner in runners:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
