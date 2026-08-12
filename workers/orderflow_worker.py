#!/usr/bin/env python3
"""
Orderflow Worker — 5-й изолированный процесс (Roadmap §3, Этап 4).

Responsibilities:
- IPCSubscriber: live RawTrade + RawBookEvent от collector
- BookState machine: snapshot + delta reconstruction
- Engines: OBI, OFI, Sweep, Tape, Absorption, Regime, Walls, Footprint, Heatmap
- UDSServer: отвечает на запросы от API
- WAL catch-up: читает published WAL tail при рестарте

Architecture:
    Collector ──IPC(DGRAM)──► OrderflowWorker ──UDS(STREAM)──► API
                                    │
                              BookState(per symbol)
                              DetectorEngines(per symbol)
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from contracts.schemas import RawBookEvent, RawTrade
from packages.analytics.absorption import AbsorptionDetector
from packages.analytics.heatmap import HeatmapAggregator
from packages.analytics.liquidation_cascades import LiquidationCascadeDetector
from packages.analytics.ofi import OFICalculator
from packages.analytics.obi import OBIEngine
from packages.analytics.pulling_stacking import PullingStackingDetector
from packages.analytics.regime import RegimeDetector
from packages.analytics.sweep import SweepDetector
from packages.analytics.tape import TapeFilter, BubbleAggregator
from packages.analytics.walls import WallDetector
from packages.bybit.book_state import BookState
from packages.bybit.collector import deserialize_event_from_payload
from packages.ipc import IPCMessage, ProcessRegistry, UDSServer
from packages.ipc.subscriber import IPCSubscriber
from packages.monitoring.worker_metrics import OrderflowMetrics
from packages.storage.manifest import Manifest
from packages.storage.wal import WalPartition

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("orderflow-worker")


class SymbolState:
    """Per-symbol state: BookState + все детекторы."""

    def __init__(self, symbol: str, depth: int = 200):
        self.symbol = symbol

        # Orderbook state machine
        self.book = BookState(symbol, depth=depth)

        # Trade-based detectors
        self.sweep = SweepDetector(min_levels=3, window_ms=500)
        self.tape = TapeFilter(min_qty_steps=1000)
        self.bubbles = BubbleAggregator(cluster_window_ms=5000)
        self.absorption = AbsorptionDetector(min_absorbed_qty=500, window_ms=2000)
        self.liquidation = LiquidationCascadeDetector(
            min_trade_qty=5000, window_ms=3000, min_cascade_count=3
        )

        # Book-based detectors
        self.obi = OBIEngine(near_levels=5)
        self.ofi = OFICalculator()
        self.walls = WallDetector(min_qty_steps=5000, max_depth=50)
        self.pulling_stacking = PullingStackingDetector()
        self.regime = RegimeDetector(symbol=symbol, window_ms=300_000)

        # Heatmap aggregator (1-minute bins, 10-tick bins)
        self.heatmap = HeatmapAggregator(
            venue="BYBIT",
            symbol=symbol,
            time_interval_ms=60_000,
            price_bin_size_ticks=10,
        )

        # Recent results (rolling buffer)
        self.recent_sweeps: list[dict] = []
        self.recent_cascades: list[dict] = []
        self.latest_ofi: dict | None = None
        self.latest_obi: dict | None = None

    def on_trade(self, trade: RawTrade) -> None:
        """Обработать RawTrade."""
        sweep = self.sweep.process(trade)
        if sweep:
            self.recent_sweeps.append(sweep.model_dump())
            if len(self.recent_sweeps) > 100:
                self.recent_sweeps = self.recent_sweeps[-100:]

        self.tape.process(trade)
        self.bubbles.process(trade)
        self.absorption.process(trade)

        cascade = self.liquidation.process(trade)
        if cascade:
            self.recent_cascades.append(cascade)
            if len(self.recent_cascades) > 50:
                self.recent_cascades = self.recent_cascades[-50:]

    def on_book_event(self, event: RawBookEvent) -> None:
        """Обработать RawBookEvent (snapshot или delta)."""
        # BookState machine
        if event.type == "snapshot":
            self.book.apply_snapshot(event)
        else:
            gap = self.book.apply_delta(event)
            if gap:
                logger.warning(
                    f"{self.symbol}: gap detected expected={gap.expected_update_id} "
                    f"received={gap.received_update_id}"
                )
                return  # не обновляем детекторы при gap

        # Book-based detectors (только если state готов)
        if not self.book.is_ready:
            return

        ofi_result = self.ofi.process(event)
        if ofi_result:
            self.latest_ofi = {
                "ofi": ofi_result.ofi,
                "microprice": ofi_result.microprice,
                "imbalance": ofi_result.imbalance,
                "spread": ofi_result.spread,
            }

        self.walls.process(event)
        self.pulling_stacking.process(event)
        self.heatmap.add_snapshot(event)

        # OBI на основе текущего book state
        bids = self.book.get_bids()
        asks = self.book.get_asks()
        if bids and asks:
            bid_vol = sum(b.qty_steps for b in bids[:5])
            ask_vol = sum(a.qty_steps for a in asks[:5])
            total = bid_vol + ask_vol
            if total > 0:
                imbalance = (bid_vol - ask_vol) / total
                self.latest_obi = {"imbalance": imbalance, "bid_vol": bid_vol, "ask_vol": ask_vol}

        # Обновить regime features
        if self.latest_ofi:
            self.regime.add_feature(
                "ofi", active=True,
                value=self.latest_ofi.get("imbalance", 0),
                confidence=0.8,
                timestamp_ms=event.exchange_timestamp_ms,
            )
        if self.latest_obi:
            self.regime.add_feature(
                "obi", active=True,
                value=self.latest_obi.get("imbalance", 0),
                confidence=0.75,
                timestamp_ms=event.exchange_timestamp_ms,
            )

    def get_features_snapshot(self) -> dict:
        """Получить текущий снапшот всех features."""
        regime_state = self.regime.compute_regime()
        return {
            "symbol": self.symbol,
            "book": {
                "status": self.book.status.value,
                "update_id": self.book.update_id,
                "best_bid": self.book.best_bid(),
                "best_ask": self.book.best_ask(),
                "mid_price": self.book.mid_price_ticks(),
                "bid_levels": self.book.level_count()[0],
                "ask_levels": self.book.level_count()[1],
            },
            "ofi": self.latest_ofi,
            "obi": self.latest_obi,
            "regime": regime_state.regime,
            "regime_confidence": regime_state.regime_confidence,
            "active_walls": len(self.walls.get_active_walls()),
            "recent_sweeps": len(self.recent_sweeps),
            "recent_cascades": len(self.recent_cascades),
        }


class OrderflowWorker:
    """Orderflow Worker — 5-й изолированный процесс.

    Получает live events от collector через IPCSubscriber,
    обрабатывает детекторами, отвечает на запросы API через UDSServer.
    """

    def __init__(
        self,
        data_dir: Path,
        socket_path: Path,
        registry_dir: Path,
        collector_socket: Path | None = None,
    ):
        self.data_dir = data_dir
        self.socket_path = socket_path
        self.registry_dir = registry_dir
        self.collector_socket = collector_socket

        self.uds_server: UDSServer | None = None
        self.registry: ProcessRegistry | None = None
        self._ipc_subscriber: IPCSubscriber | None = None

        # Per-symbol state
        self._symbols: dict[str, SymbolState] = {}

        self.running = False
        self.health_status = "starting"
        self.stats = {
            "trades_processed": 0,
            "book_events_processed": 0,
            "gaps_detected": 0,
        }

        # Metrics
        self.metrics = OrderflowMetrics()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        logger.info("Starting orderflow worker...")

        # Warm-up: WAL catch-up для каждого символа
        for symbol_dir in self.data_dir.iterdir():
            if symbol_dir.is_dir() and not symbol_dir.name.endswith("-rpi"):
                symbol = symbol_dir.name
                self._ensure_symbol(symbol)
                self._wal_catchup(symbol)

        # UDS server для ответов на запросы API
        self.uds_server = UDSServer(self.socket_path, "orderflow-worker")
        self.registry = ProcessRegistry(self.registry_dir)

        self.uds_server.register_handler("health", self._handle_health)
        self.uds_server.register_handler("request", self._handle_request)

        asyncio.create_task(self.uds_server.start())

        # IPC subscriber: получаем live events от collector
        rx_sock = self.socket_path.parent / "bybit-orderflow-rx.sock"
        self._ipc_subscriber = IPCSubscriber(rx_sock)
        self._ipc_subscriber.register_handler("RawTrade", self._on_raw_trade)
        self._ipc_subscriber.register_handler("RawBookEvent", self._on_raw_book_event)
        self._ipc_subscriber.run_in_thread(daemon=True)

        self.registry.register_process("orderflow", self.socket_path)

        # Readiness: ждём пока registry подтвердит регистрацию
        for _ in range(300):
            await asyncio.sleep(0.1)
            if self.registry.discover_process("orderflow"):
                break

        self.running = True
        self.health_status = "healthy"
        logger.info("Orderflow worker started successfully")

        await self._run_loop()

    async def _run_loop(self):
        try:
            while self.running:
                await asyncio.sleep(30)
                logger.debug(
                    f"Stats: trades={self.stats['trades_processed']} "
                    f"book={self.stats['book_events_processed']} "
                    f"gaps={self.stats['gaps_detected']}"
                )
        except asyncio.CancelledError:
            logger.info("Orderflow worker stopping...")
        finally:
            await self.stop()

    async def stop(self):
        logger.info("Stopping orderflow worker...")
        self.running = False
        self.health_status = "stopping"

        if self._ipc_subscriber:
            self._ipc_subscriber.stop()

        if self.uds_server:
            await self.uds_server.stop()

        self.health_status = "stopped"
        logger.info("Orderflow worker stopped")

    # ------------------------------------------------------------------
    # IPC event handlers
    # ------------------------------------------------------------------

    def _on_raw_trade(self, payload: dict) -> None:
        """Handle RawTrade от collector."""
        try:
            self.metrics.ipc_events_received_total.inc()
            symbol = payload.get("symbol", "")
            state = self._ensure_symbol(symbol)
            trade = RawTrade(**payload)
            state.on_trade(trade)
            self.stats["trades_processed"] += 1
        except Exception as exc:
            self.metrics.ipc_events_dropped_total.inc()
            logger.debug(f"on_raw_trade error: {exc}")

    def _on_raw_book_event(self, payload: dict) -> None:
        """Handle RawBookEvent от collector."""
        try:
            self.metrics.ipc_events_received_total.inc()
            symbol = payload.get("symbol", "")
            state = self._ensure_symbol(symbol)
            event = RawBookEvent(**payload)

            if event.type == "snapshot":
                self.metrics.book_snapshots_processed.inc()
            else:
                self.metrics.book_deltas_processed.inc()

            prev_gaps = state.book.gap_count
            state.on_book_event(event)
            if state.book.gap_count > prev_gaps:
                self.metrics.book_gaps_detected_total.inc()
                self.stats["gaps_detected"] += 1

            # Update book_state_status gauge
            status_map = {"not_ready": 0, "syncing": 1, "ready": 2, "gap": 3}
            self.metrics.book_state_status.set(status_map.get(state.book.status, 0))

            self.stats["book_events_processed"] += 1
        except Exception as exc:
            self.metrics.ipc_events_dropped_total.inc()
            logger.debug(f"on_raw_book_event error: {exc}")

    def _handle_health(self, message: IPCMessage) -> dict:
        return {
            "status": self.health_status,
            "process": "orderflow-worker",
            "symbols": list(self._symbols.keys()),
            "stats": self.stats,
        }

    def _handle_request(self, message: IPCMessage) -> dict:
        try:
            req_type = message.payload.get("type")
            symbol = message.payload.get("symbol", "")

            if req_type == "get_metrics":
                return {"metrics": self.metrics.to_prometheus()}

            elif req_type == "get_features":
                state = self._symbols.get(symbol)
                if not state:
                    return {"error": f"Unknown symbol: {symbol}"}
                return state.get_features_snapshot()

            elif req_type == "get_sweeps":
                state = self._symbols.get(symbol)
                if not state:
                    return {"error": f"Unknown symbol: {symbol}"}
                return {"sweeps": state.recent_sweeps, "count": len(state.recent_sweeps)}

            elif req_type == "get_cascades":
                state = self._symbols.get(symbol)
                if not state:
                    return {"error": f"Unknown symbol: {symbol}"}
                return {"cascades": state.recent_cascades, "count": len(state.recent_cascades)}

            elif req_type == "get_heatmap":
                state = self._symbols.get(symbol)
                if not state:
                    return {"error": f"Unknown symbol: {symbol}"}
                tiles = state.heatmap.build()
                return {"tiles": [t.model_dump() for t in tiles], "count": len(tiles)}

            elif req_type == "get_walls":
                state = self._symbols.get(symbol)
                if not state:
                    return {"error": f"Unknown symbol: {symbol}"}
                walls = state.walls.get_active_walls()
                return {"walls": [w.model_dump() for w in walls], "count": len(walls)}

            elif req_type == "get_regime":
                state = self._symbols.get(symbol)
                if not state:
                    return {"error": f"Unknown symbol: {symbol}"}
                analysis = state.regime.analyze()
                return {
                    "regime": analysis.state.regime,
                    "confidence": analysis.state.regime_confidence,
                    "features": [f.model_dump() for f in analysis.state.features],
                    "importance": [fi.model_dump() for fi in analysis.feature_importance],
                }

            elif req_type == "get_symbols":
                return {"symbols": list(self._symbols.keys())}

            else:
                return {"error": f"Unknown request: {req_type}"}
        except Exception as exc:
            logger.error(f"request handler error: {exc}", exc_info=True)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_symbol(self, symbol: str) -> SymbolState:
        if symbol not in self._symbols:
            self._symbols[symbol] = SymbolState(symbol)
            logger.info(f"Registered new symbol: {symbol}")
        return self._symbols[symbol]

    def _wal_catchup(self, symbol: str) -> None:
        """WAL catch-up при старте: replay events из live WAL tail."""
        state = self._symbols.get(symbol)
        if not state:
            return

        symbol_dir = self.data_dir / symbol
        manifest_path = symbol_dir / "manifest.json"
        if not manifest_path.exists():
            return

        try:
            manifest = Manifest(manifest_path)
            manifest.load()
            published = manifest.published_offset()
        except Exception:
            return

        wal_candidates = [symbol_dir / "wal" / "p0", symbol_dir / "p0", symbol_dir]
        wal_partition = None
        for candidate in wal_candidates:
            if candidate.exists() and any(candidate.glob("*.wal")):
                wal_partition = candidate
                break

        if not wal_partition:
            return

        try:
            wal = WalPartition(wal_partition, partition_id=symbol)
            wal.recover()
            if wal.durable_offset <= published:
                return

            frames = wal.read_range(published, wal.durable_offset)
            trade_count = 0
            book_count = 0
            for frame in frames:
                try:
                    event = deserialize_event_from_payload(frame.payload)
                    if isinstance(event, RawTrade):
                        state.on_trade(event)
                        trade_count += 1
                    elif isinstance(event, RawBookEvent):
                        state.on_book_event(event)
                        book_count += 1
                except Exception:
                    pass

            if trade_count or book_count:
                logger.info(
                    f"WAL catch-up {symbol}: {trade_count} trades, {book_count} book events"
                )
        except Exception as exc:
            logger.debug(f"WAL catch-up failed for {symbol}: {exc}")


async def main():
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/bybit-chart/data")
    socket_path = Path("/tmp/bybit-orderflow.sock")
    registry_dir = Path("/tmp/bybit-registry")

    worker = OrderflowWorker(
        data_dir=data_dir,
        socket_path=socket_path,
        registry_dir=registry_dir,
    )

    loop = asyncio.get_running_loop()

    def signal_handler(sig):
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(worker.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as exc:
        logger.error(f"Worker error: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
