#!/usr/bin/env python3
"""
Collector Worker — изолированный процесс для сбора данных (Roadmap §2-3, Этап 4).

Источник: Roadmap §2 (изолированный collector) + §3 (multi-process)

Responsibilities:
- WebSocket subscription к Bybit (publicTrade + orderbook)
- Запись в WAL через EventCollector (с WriterLease fencing)
- Publish событий через IPCPublisher (fire-and-forget к analytics/orderflow)
- UDSServer: health checks от supervisor
- Independent lifecycle (crash isolation)

Architecture:
WebSocket → Deserializer → EventCollector (WAL + fencing)
                               ↓
                          IPCPublisher ──DGRAM──► analytics-worker
                                               ► orderflow-worker
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from packages.bybit.collector import EventCollector
from packages.bybit.deserializer import deserialize_trade
from packages.bybit.deserializer_book import deserialize_book_snapshot
from packages.bybit.ws_client import BybitWebSocketClient
from packages.ipc import IPCMessage, ProcessRegistry, UDSServer
from packages.ipc.publisher import IPCPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("collector-worker")

# Сокеты подписчиков
ANALYTICS_SOCKET = Path("/tmp/bybit-analytics-rx.sock")
ORDERFLOW_SOCKET = Path("/tmp/bybit-orderflow-rx.sock")


class CollectorWorker:
    """Collector Worker — изолированный процесс для сбора данных.

    Roadmap §2-3 + Этап 4: реальный WebSocket loop с IPC publish.
    """

    def __init__(
        self,
        data_dir: Path,
        symbols: list[str],
        socket_path: Path,
        registry_dir: Path,
    ):
        self.data_dir = data_dir
        self.symbols = symbols
        self.socket_path = socket_path
        self.registry_dir = registry_dir

        # IPC
        self.uds_server: UDSServer | None = None
        self.registry: ProcessRegistry | None = None
        self._publishers: dict[str, IPCPublisher] = {}

        # EventCollectors (per symbol)
        self.collectors: dict[str, EventCollector] = {}

        # WebSocket clients (per symbol)
        self._ws_tasks: list[asyncio.Task] = []

        self.running = False
        self.health_status = "starting"
        self.stats = {s: {"trades": 0, "book_events": 0, "ipc_drops": 0} for s in symbols}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        logger.info(f"Starting collector worker: symbols={self.symbols}")

        # UDS server для health checks от supervisor
        self.uds_server = UDSServer(self.socket_path, "collector-worker")
        self.registry = ProcessRegistry(self.registry_dir)

        self.uds_server.register_handler("health", self._handle_health_check)
        self.uds_server.register_handler("request", self._handle_request)

        asyncio.create_task(self.uds_server.start())

        self.registry.register_process("collector", self.socket_path)

        # Readiness
        for _ in range(300):
            await asyncio.sleep(0.1)
            if self.registry.discover_process("collector"):
                break

        # IPC publishers (fire-and-forget к подписчикам)
        self._publishers = {
            "analytics": IPCPublisher(ANALYTICS_SOCKET, source_name="collector"),
            "orderflow": IPCPublisher(ORDERFLOW_SOCKET, source_name="collector"),
        }

        # EventCollectors (с WriterLease fencing)
        for symbol in self.symbols:
            symbol_dir = self.data_dir / symbol
            symbol_dir.mkdir(parents=True, exist_ok=True)
            self.collectors[symbol] = EventCollector(symbol_dir, symbol, use_fencing=True)
            logger.info(f"Initialized collector for {symbol}")

        self.running = True
        self.health_status = "healthy"
        logger.info("Collector worker started successfully")

        await self._run_loop()

    async def _run_loop(self):
        """Запуск WebSocket loop для каждого символа."""
        tasks = []
        for symbol in self.symbols:
            tasks.append(asyncio.create_task(self._collect_symbol(symbol)))

        self._ws_tasks = tasks
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            logger.info("Collector worker stopping...")
        finally:
            await self.stop()

    async def _collect_symbol(self, symbol: str):
        """Подключиться к Bybit WebSocket и собирать данные для одного символа."""
        collector = self.collectors[symbol]
        client = BybitWebSocketClient()

        while self.running:
            try:
                await client.connect()
                await client.subscribe("publicTrade", symbol)
                await client.subscribe("orderbook.200", symbol)

                logger.info(f"WebSocket connected for {symbol}")

                async def handle(msg: dict):
                    if not self.running:
                        return
                    topic = msg.get("topic", "")
                    if topic.startswith("publicTrade"):
                        await self._handle_trade_msg(symbol, msg, collector)
                    elif topic.startswith("orderbook"):
                        await self._handle_book_msg(symbol, msg, collector)

                await client.run(
                    channels=[f"publicTrade.{symbol}", f"orderbook.200.{symbol}"],
                    callback=handle,
                )

            except Exception as exc:
                if not self.running:
                    break
                logger.warning(f"WebSocket error for {symbol}: {exc}, reconnecting in 5s")
                await asyncio.sleep(5)
            finally:
                await client.close()

    async def _handle_trade_msg(self, symbol: str, msg: dict, collector: EventCollector):
        """Десериализовать и записать trade."""
        try:
            data_list = msg.get("data", [])
            if not isinstance(data_list, list):
                data_list = [data_list]
            for item in data_list:
                # Собираем envelope для deserializer
                trade_msg = {
                    "topic": msg.get("topic", f"publicTrade.{symbol}"),
                    "type": "snapshot",
                    "ts": msg.get("ts", 0),
                    "data": [item],
                }
                from packages.bybit.deserializer import deserialize_public_trade
                trade = deserialize_public_trade(trade_msg)
                if trade:
                    collector.append_trade(trade)
                    self.stats[symbol]["trades"] += 1
                    # IPC publish (best-effort)
                    payload = trade.model_dump(mode="json")
                    for pub in self._publishers.values():
                        ok = pub.publish_raw("RawTrade", payload)
                        if not ok:
                            self.stats[symbol]["ipc_drops"] += 1
        except Exception as exc:
            logger.debug(f"Trade msg error {symbol}: {exc}")

    async def _handle_book_msg(self, symbol: str, msg: dict, collector: EventCollector):
        """Десериализовать и записать book snapshot/delta."""
        try:
            msg_type = msg.get("type", "")
            if msg_type == "snapshot":
                checkpoint = deserialize_book_snapshot(
                    msg, connection_epoch="live"
                )
                collector.append_book_checkpoint(checkpoint)
                self.stats[symbol]["book_events"] += 1
                payload = checkpoint.model_dump(mode="json")
                for pub in self._publishers.values():
                    ok = pub.publish_raw("RawBookEvent", payload)
                    if not ok:
                        self.stats[symbol]["ipc_drops"] += 1
            # delta events: publisher publishes raw, orderflow-worker handles BookState
            elif msg_type == "delta":
                from contracts.schemas import RawBookEvent, RawBookLevel
                # construct minimal RawBookEvent for orderflow-worker
                data = msg.get("data", {})
                bids = [RawBookLevel(priceTicks=int(float(b[0])/0.1), qtySteps=int(float(b[1])/0.001))
                        for b in data.get("b", []) if len(b) == 2]
                asks = [RawBookLevel(priceTicks=int(float(a[0])/0.1), qtySteps=int(float(a[1])/0.001))
                        for a in data.get("a", []) if len(a) == 2]
                book_event = RawBookEvent(
                    symbol=symbol,
                    depth=200,
                    type="delta",
                    bids=bids,
                    asks=asks,
                    updateId=int(data.get("u", 0)),
                    sequence=int(data.get("seq", 0)),
                    exchangeTimestampMs=msg.get("ts", 0),
                    outerTimestampMs=msg.get("ts", 0),
                    receiveTimestampMs=msg.get("ts", 0),
                    connectionEpoch="live",
                )
                for pub in self._publishers.values():
                    pub.publish_raw("RawBookEvent", book_event.model_dump(mode="json"))
        except Exception as exc:
            logger.debug(f"Book msg error {symbol}: {exc}")

    async def stop(self):
        logger.info("Stopping collector worker...")
        self.running = False
        self.health_status = "stopping"

        for task in self._ws_tasks:
            task.cancel()

        for symbol, collector in self.collectors.items():
            logger.info(f"Closing collector for {symbol}")
            collector.close()

        if self.uds_server:
            await self.uds_server.stop()

        self.health_status = "stopped"
        logger.info("Collector worker stopped")

    def _handle_health_check(self, message: IPCMessage) -> dict:
        return {
            "status": self.health_status,
            "process": "collector-worker",
            "symbols": list(self.collectors.keys()),
            "stats": self.stats,
        }

    def _handle_request(self, message: IPCMessage) -> dict:
        req_type = message.payload.get("type")
        if req_type == "get_symbols":
            return {"symbols": list(self.collectors.keys())}
        elif req_type == "get_stats":
            return {"stats": self.stats}
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
