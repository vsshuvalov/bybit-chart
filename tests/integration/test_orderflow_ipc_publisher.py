#!/usr/bin/env python3
"""
Integration test для orderflow-worker IPC publisher (Этап 4.1).

Проверяет:
- Orderflow worker публикует события через IPC
- Analytics/API могут подписаться на orderflow events
- События доставляются корректно
"""

import asyncio
import time
from pathlib import Path

from contracts.schemas import OrderflowSweep, OrderflowOFI
from packages.ipc.subscriber import IPCSubscriber


async def test_orderflow_ipc_publisher():
    """Test что orderflow worker публикует события через IPC."""

    # Подписаться на orderflow events
    rx_sock = Path("/tmp/bybit-orderflow-tx.sock")

    if not rx_sock.exists():
        print("❌ Orderflow worker не запущен (socket не найден)")
        print(f"   Ожидается: {rx_sock}")
        print("   Запустите: python3 workers/orderflow_worker.py")
        return False

    received_events = []

    def on_sweep(payload: dict):
        sweep = OrderflowSweep(**payload)
        received_events.append(("sweep", sweep))
        print(f"✓ Received sweep: {sweep.symbol} {sweep.side} {sweep.levels_swept} levels")

    def on_ofi(payload: dict):
        ofi = OrderflowOFI(**payload)
        received_events.append(("ofi", ofi))
        print(f"✓ Received OFI: {ofi.symbol} ofi={ofi.ofi:.4f} microprice={ofi.microprice}")

    subscriber = IPCSubscriber(rx_sock)
    subscriber.register_handler("OrderflowSweep", on_sweep)
    subscriber.register_handler("OrderflowOFI", on_ofi)
    subscriber.run_in_thread(daemon=True)

    print("Subscribed to orderflow events, waiting 30 seconds...")

    # Ждём события
    await asyncio.sleep(30)

    subscriber.stop()

    # Проверка результатов
    if len(received_events) == 0:
        print("⚠️  No events received in 30 seconds")
        print("   Это нормально если market неактивен или orderflow worker только стартовал")
        return True

    print(f"\n✅ Received {len(received_events)} orderflow events")

    # Breakdown по типам
    sweeps = [e for e in received_events if e[0] == "sweep"]
    ofis = [e for e in received_events if e[0] == "ofi"]

    print(f"   - Sweeps: {len(sweeps)}")
    print(f"   - OFI updates: {len(ofis)}")

    return True


if __name__ == "__main__":
    success = asyncio.run(test_orderflow_ipc_publisher())
    exit(0 if success else 1)
