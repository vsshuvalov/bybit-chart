#!/usr/bin/env python3
"""
API Server Worker — изолированный процесс для REST API + WebSocket (Roadmap §3).

Источник: Roadmap §3 (multi-process architecture) + §7 (Query API)

Responsibilities:
- REST API endpoints (trades, OHLC, analytics)
- WebSocket real-time updates
- IPC requests к analytics worker для данных
- Independent lifecycle (restart без потери analytics)

Architecture:
HTTP Client → API Server → IPC request → Analytics Worker
                                      ← IPC response

WebSocket Client ← API Server ← IPC events ← Collector/Analytics

Roadmap требования:
- API отделён от analytics calculation
- IPC для data queries
- Independent restart capability
- WebSocket real-time через IPC
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
import uvicorn

from packages.ipc import IPCMessage, ProcessRegistry, UDSClient, UDSServer
from packages.monitoring import get_metrics_collector, Timer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("api-server")


class APIServerWorker:
    """API Server Worker — изолированный API процесс.

    Roadmap §3 + §7: isolated API с IPC к analytics.
    """

    def __init__(
        self,
        socket_path: Path,
        registry_dir: Path,
        host: str = "127.0.0.1",
        port: int = 8000,
    ):
        """Initialize API server worker.

        Args:
            socket_path: путь к UDS socket для IPC
            registry_dir: директория process registry
            host: API server host
            port: API server port
        """
        self.socket_path = socket_path
        self.registry_dir = registry_dir
        self.host = host
        self.port = port

        # IPC components
        self.uds_server: UDSServer | None = None
        self.registry: ProcessRegistry | None = None
        self.analytics_client: UDSClient | None = None

        # FastAPI app
        self.app: FastAPI | None = None

        # State
        self.running = False
        self.health_status = "starting"

        # Metrics
        self.metrics = get_metrics_collector()

    async def start(self):
        """Запустить API server worker."""
        logger.info(f"Starting API server worker on {self.host}:{self.port}...")

        # Initialize IPC
        self.uds_server = UDSServer(self.socket_path, "api-server")
        self.registry = ProcessRegistry(self.registry_dir)

        # Register handlers
        self.uds_server.register_handler("health", self._handle_health_check)

        # Start UDS server (for health checks)
        asyncio.create_task(self.uds_server.start())

        # Register in process registry
        self.registry.register_process("api", self.socket_path)

        # Wait for UDS server
        await asyncio.sleep(0.5)

        # Connect to analytics worker
        await self._connect_analytics()

        # Create FastAPI app
        self.app = self._create_app()

        self.running = True
        self.health_status = "healthy"

        logger.info("API server worker started successfully")

        # Run FastAPI server
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def stop(self):
        """Graceful shutdown."""
        logger.info("Stopping API server worker...")

        self.running = False
        self.health_status = "stopping"

        # Close analytics client
        if self.analytics_client:
            await self.analytics_client.close()

        # Stop UDS server
        if self.uds_server:
            await self.uds_server.stop()

        self.health_status = "stopped"
        logger.info("API server worker stopped")

    async def _connect_analytics(self):
        """Connect to analytics worker via IPC."""
        analytics_socket = self.registry.discover_process("analytics")

        if not analytics_socket:
            logger.warning("Analytics worker not found in registry")
            return

        try:
            self.analytics_client = UDSClient(analytics_socket, "api-server")
            await self.analytics_client.connect()
            logger.info(f"Connected to analytics worker at {analytics_socket}")
        except Exception as exc:
            logger.error(f"Failed to connect to analytics worker: {exc}")

    def _handle_health_check(self, message: IPCMessage) -> dict:
        """Handle health check request."""
        return {
            "status": self.health_status,
            "process": "api-server",
            "analytics_connected": self.analytics_client is not None,
        }

    def _create_app(self) -> FastAPI:
        """Create FastAPI application."""
        app = FastAPI(
            title="Bybit Chart Query API",
            description="REST API для Order Flow данных (Multi-process)",
            version="2.0.0",
        )

        # CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Metrics middleware
        @app.middleware("http")
        async def metrics_middleware(request, call_next):
            self.metrics.http_requests_total.inc()

            with Timer(self.metrics.http_request_duration_seconds):
                try:
                    response = await call_next(request)
                    if response.status_code >= 400:
                        self.metrics.http_errors_total.inc()
                    return response
                except Exception:
                    self.metrics.http_errors_total.inc()
                    raise

        # Health check endpoint
        @app.get("/health")
        async def health_check():
            """Health check endpoint."""
            analytics_status = "disconnected"

            if self.analytics_client:
                try:
                    health_msg = IPCMessage(
                        message_type="health",
                        payload={},
                        source="api-server",
                    )
                    response = await asyncio.wait_for(
                        self.analytics_client.send_message(health_msg),
                        timeout=2.0,
                    )
                    if response:
                        analytics_status = response.payload.get("status", "unknown")
                except:
                    analytics_status = "timeout"

            return {
                "status": self.health_status,
                "service": "bybit-chart-api-server",
                "version": "2.0.0",
                "analytics": analytics_status,
            }

        # Metrics endpoint
        @app.get("/metrics", response_class=PlainTextResponse)
        async def prometheus_metrics():
            """Prometheus metrics endpoint."""
            return self.metrics.export_prometheus()

        # Symbols endpoint
        @app.get("/api/v1/symbols")
        async def get_symbols():
            """Get available symbols via IPC."""
            if not self.analytics_client:
                raise HTTPException(status_code=503, detail="Analytics worker unavailable")

            try:
                request = IPCMessage(
                    message_type="request",
                    payload={"type": "get_symbols"},
                    source="api-server",
                    correlation_id="symbols_req",
                )

                response = await asyncio.wait_for(
                    self.analytics_client.send_message(request),
                    timeout=5.0,
                )

                if response and "symbols" in response.payload:
                    return {"symbols": response.payload["symbols"]}
                else:
                    raise HTTPException(status_code=500, detail="Invalid response from analytics")

            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="Analytics request timeout")
            except Exception as exc:
                logger.error(f"Error querying analytics: {exc}")
                raise HTTPException(status_code=500, detail=str(exc))

        # Delta endpoint (via IPC)
        @app.get("/api/v1/delta")
        async def get_delta(
            symbol: str = Query(...),
            start_ts: int = Query(...),
            end_ts: int = Query(...),
            interval: str = Query("1m"),
        ):
            """Get Delta via IPC to analytics worker."""
            if not self.analytics_client:
                raise HTTPException(status_code=503, detail="Analytics worker unavailable")

            # Parse interval
            interval_map = {"1m": 60_000_000, "5m": 300_000_000, "15m": 900_000_000, "1h": 3_600_000_000}
            interval_us = interval_map.get(interval, 60_000_000)

            try:
                request = IPCMessage(
                    message_type="request",
                    payload={
                        "type": "get_delta",
                        "symbol": symbol,
                        "start_ts": start_ts,
                        "end_ts": end_ts,
                        "interval_us": interval_us,
                    },
                    source="api-server",
                )

                response = await asyncio.wait_for(
                    self.analytics_client.send_message(request),
                    timeout=10.0,
                )

                if response and "bars" in response.payload:
                    return response.payload
                else:
                    raise HTTPException(status_code=500, detail="Invalid response")

            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="Request timeout")
            except Exception as exc:
                logger.error(f"Error: {exc}")
                raise HTTPException(status_code=500, detail=str(exc))

        return app


async def main():
    """Main entry point."""
    socket_path = Path("/tmp/bybit-api.sock")
    registry_dir = Path("/tmp/bybit-registry")

    worker = APIServerWorker(
        socket_path=socket_path,
        registry_dir=registry_dir,
        host="127.0.0.1",
        port=8000,
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
