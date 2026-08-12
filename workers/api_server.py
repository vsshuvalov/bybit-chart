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
    """API Server Worker — изолированный API процесс (Этап 4).

    Roadmap §3 + §7: isolated API с IPC к analytics + orderflow.
    Добавлены: все analytics endpoints, orderflow endpoints, /stream snapshot.
    """

    def __init__(
        self,
        socket_path: Path,
        registry_dir: Path,
        host: str = "0.0.0.0",
        port: int = 8000,
    ):
        self.socket_path = socket_path
        self.registry_dir = registry_dir
        self.host = host
        self.port = port

        self.uds_server: UDSServer | None = None
        self.registry: ProcessRegistry | None = None
        self.analytics_client: UDSClient | None = None
        self.orderflow_client: UDSClient | None = None

        self.app: FastAPI | None = None
        self.running = False
        self.health_status = "starting"
        self.metrics = get_metrics_collector()

    async def start(self):
        """Запустить API server worker."""
        logger.info(f"Starting API server worker on {self.host}:{self.port}...")

        self.uds_server = UDSServer(self.socket_path, "api-server")
        self.registry = ProcessRegistry(self.registry_dir)

        self.uds_server.register_handler("health", self._handle_health_check)

        asyncio.create_task(self.uds_server.start())
        self.registry.register_process("api", self.socket_path)

        # Реальная readiness: ждём аналитику
        for _ in range(300):
            await asyncio.sleep(0.1)
            if self.registry.discover_process("api"):
                break

        await self._connect_workers()

        self.app = self._create_app()
        self.running = True
        self.health_status = "healthy"

        logger.info("API server worker started successfully")

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def stop(self):
        logger.info("Stopping API server worker...")
        self.running = False
        self.health_status = "stopping"

        if self.analytics_client:
            await self.analytics_client.close()
        if self.orderflow_client:
            await self.orderflow_client.close()
        if self.uds_server:
            await self.uds_server.stop()

        self.health_status = "stopped"
        logger.info("API server worker stopped")

    async def _connect_workers(self):
        """Connect к analytics и orderflow workers через IPC."""
        for name, attr in [("analytics", "analytics_client"), ("orderflow", "orderflow_client")]:
            sock = self.registry.discover_process(name)
            if sock:
                try:
                    client = UDSClient(sock, "api-server")
                    await client.connect()
                    setattr(self, attr, client)
                    logger.info(f"Connected to {name}-worker at {sock}")
                except Exception as exc:
                    logger.warning(f"Failed to connect to {name}-worker: {exc}")
            else:
                logger.warning(f"{name}-worker not found in registry")

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

        # ----------------------------------------------------------------
        # VWAP endpoint
        # ----------------------------------------------------------------
        @app.get("/api/v1/vwap")
        async def get_vwap(
            symbol: str = Query(...),
            start_ts: int = Query(...),
            end_ts: int = Query(...),
            interval: str = Query("1m"),
        ):
            """Get VWAP via IPC to analytics worker."""
            if not self.analytics_client:
                raise HTTPException(status_code=503, detail="Analytics worker unavailable")
            interval_map = {"1m": 60_000_000, "5m": 300_000_000, "15m": 900_000_000, "1h": 3_600_000_000}
            interval_us = interval_map.get(interval, 60_000_000)
            try:
                request = IPCMessage(
                    message_type="request",
                    payload={"type": "get_vwap", "symbol": symbol,
                             "start_ts": start_ts, "end_ts": end_ts, "interval_us": interval_us},
                    source="api-server",
                )
                response = await asyncio.wait_for(
                    self.analytics_client.send_message(request), timeout=10.0
                )
                if response:
                    return response.payload
                raise HTTPException(status_code=500, detail="Invalid response")
            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="Request timeout")

        # ----------------------------------------------------------------
        # Volume Profile endpoint
        # ----------------------------------------------------------------
        @app.get("/api/v1/volume-profile")
        async def get_volume_profile(
            symbol: str = Query(...),
            start_ts: int = Query(...),
            end_ts: int = Query(...),
            price_tick: int = Query(10),
        ):
            """Get Volume Profile via IPC to analytics worker."""
            if not self.analytics_client:
                raise HTTPException(status_code=503, detail="Analytics worker unavailable")
            try:
                request = IPCMessage(
                    message_type="request",
                    payload={"type": "get_volume_profile", "symbol": symbol,
                             "start_ts": start_ts, "end_ts": end_ts, "price_tick": price_tick},
                    source="api-server",
                )
                response = await asyncio.wait_for(
                    self.analytics_client.send_message(request), timeout=10.0
                )
                if response:
                    return response.payload
                raise HTTPException(status_code=500, detail="Invalid response")
            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="Request timeout")

        # ----------------------------------------------------------------
        # Orderflow endpoints (proxy → orderflow-worker)
        # ----------------------------------------------------------------

        def _require_orderflow():
            if not self.orderflow_client:
                raise HTTPException(status_code=503, detail="Orderflow worker unavailable")

        async def _orderflow_request(payload: dict, timeout: float = 5.0):
            _require_orderflow()
            try:
                request = IPCMessage(message_type="request", payload=payload, source="api-server")
                response = await asyncio.wait_for(
                    self.orderflow_client.send_message(request), timeout=timeout
                )
                if response:
                    return JSONResponse(content=response.payload)
                raise HTTPException(status_code=500, detail="No response")
            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="Orderflow timeout")
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        @app.get("/api/v1/orderflow/features")
        async def get_orderflow_features(
            symbol: str = Query(...),
            active_only: bool = Query(False),
        ):
            """Orderflow features via IPC to orderflow-worker."""
            return await _orderflow_request({"type": "get_features", "symbol": symbol})

        @app.get("/api/v1/orderflow/regime")
        async def get_orderflow_regime(symbol: str = Query(...)):
            """Market regime via IPC to orderflow-worker."""
            return await _orderflow_request({"type": "get_regime", "symbol": symbol})

        @app.get("/api/v1/orderflow/sweeps")
        async def get_orderflow_sweeps(symbol: str = Query(...)):
            """Recent sweep events via IPC to orderflow-worker."""
            return await _orderflow_request({"type": "get_sweeps", "symbol": symbol})

        @app.get("/api/v1/orderflow/cascades")
        async def get_orderflow_cascades(symbol: str = Query(...)):
            """Recent liquidation cascades via IPC to orderflow-worker."""
            return await _orderflow_request({"type": "get_cascades", "symbol": symbol})

        @app.get("/api/v1/orderflow/walls")
        async def get_orderflow_walls(symbol: str = Query(...)):
            """Active orderbook walls via IPC to orderflow-worker."""
            return await _orderflow_request({"type": "get_walls", "symbol": symbol})

        @app.get("/api/v1/analytics/heatmap")
        async def get_heatmap(symbol: str = Query(...)):
            """Heatmap tiles via IPC to orderflow-worker."""
            return await _orderflow_request({"type": "get_heatmap", "symbol": symbol})

        # ----------------------------------------------------------------
        # snapshot/streamEpoch (Этап 4: derived checkpoints)
        # ----------------------------------------------------------------
        @app.get("/api/v1/stream/{symbol}/snapshot")
        async def get_stream_snapshot(symbol: str):
            """Полное состояние orderflow для символа (snapshot для WebSocket clients).

            Возвращает текущий epoch + полный снапшот всех features.
            Клиент использует это для начальной синхронизации, затем patch events.
            """
            return await _orderflow_request({"type": "get_features", "symbol": symbol})

        @app.get("/api/v1/stream/{symbol}/epoch")
        async def get_stream_epoch(symbol: str):
            """Текущий epoch для символа (для streamEpoch invalidation).

            Клиент сравнивает epoch с кешированным — если изменился, делает /snapshot.
            """
            result = await _orderflow_request({"type": "get_features", "symbol": symbol})
            content = result.body if hasattr(result, "body") else {}
            import json
            try:
                data = json.loads(result.body) if hasattr(result, "body") else {}
            except Exception:
                data = {}
            return JSONResponse(content={
                "symbol": symbol,
                "epoch": data.get("book", {}).get("update_id", 0),
                "book_status": data.get("book", {}).get("status", "unknown"),
            })

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
