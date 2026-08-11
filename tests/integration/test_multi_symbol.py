"""
Integration tests для multi-symbol collector.

Проверяет изоляцию WAL partitions при одновременной работе
нескольких символов (Roadmap §19 Этап 3).
"""

import tempfile
from pathlib import Path

import pytest

from contracts.schemas import RawTrade, TakerSide
from packages.bybit.collector import EventCollector

pytestmark = pytest.mark.integration


def make_trade(symbol: str, trade_id: str, price_ticks: int, qty_steps: int, timestamp_ms: int) -> RawTrade:
    """Helper для создания RawTrade."""
    return RawTrade(
        symbol=symbol,
        tradeId=trade_id,
        sequence=int(trade_id),
        exchangeTimestampMs=timestamp_ms,
        outerTimestampMs=timestamp_ms,
        receiveTimestampMs=timestamp_ms + 100,
        priceTicks=price_ticks,
        qtySteps=qty_steps,
        takerSide=TakerSide.BUY,
    )


def read_wal_bytes(partition_dir: Path) -> bytes:
    """Прочитать все WAL сегменты партиции."""
    data = b""
    for wal_file in sorted(partition_dir.glob("*.wal")):
        data += wal_file.read_bytes()
    return data


def test_multi_symbol_partition_isolation():
    """Каждый символ пишет в свою партицию, без пересечения."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]

        collectors = {s: EventCollector(base / s, s) for s in symbols}

        # Разные ценовые уровни для каждого символа
        prices = {"BTCUSDT": 640000, "ETHUSDT": 32000, "XRPUSDT": 5000}

        for i, symbol in enumerate(symbols):
            for j in range(3):
                collectors[symbol].append_trade(
                    make_trade(symbol, str(i * 10 + j), prices[symbol] + j, 1000, 1672324800000 + j * 1000)
                )

        for c in collectors.values():
            c.flush()
            c.close()

        # Каждая партиция существует и содержит данные
        for symbol in symbols:
            partition_dir = base / symbol
            assert partition_dir.exists(), f"{symbol} partition missing"
            wal_data = read_wal_bytes(partition_dir)
            assert len(wal_data) > 0, f"{symbol} WAL empty"

        # Изоляция: symbol A не появляется в WAL symbol B
        for symbol in symbols:
            wal_data = read_wal_bytes(base / symbol)
            assert symbol.encode() in wal_data, f"{symbol} not in own WAL"
            for other in symbols:
                if other != symbol:
                    assert other.encode() not in wal_data, f"{other} leaked into {symbol} WAL"


def test_multi_symbol_interleaved_writes():
    """Чередующиеся записи в разные партиции не смешиваются."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
        collectors = {s: EventCollector(base / s, s) for s in symbols}

        # Round-robin запись
        trades = [
            ("BTCUSDT", "1", 640000),
            ("ETHUSDT", "2", 32000),
            ("XRPUSDT", "3", 5000),
            ("BTCUSDT", "4", 640010),
            ("ETHUSDT", "5", 32010),
            ("XRPUSDT", "6", 5010),
        ]

        for symbol, tid, price in trades:
            collectors[symbol].append_trade(
                make_trade(symbol, tid, price, 1000, 1672324800000 + int(tid) * 1000)
            )

        for c in collectors.values():
            c.flush()
            c.close()

        # Проверить trade IDs в правильных партициях
        expected = {"BTCUSDT": ["1", "4"], "ETHUSDT": ["2", "5"], "XRPUSDT": ["3", "6"]}
        for symbol, tids in expected.items():
            wal_data = read_wal_bytes(base / symbol).decode("utf-8", errors="ignore")
            for tid in tids:
                assert f'"trade_id":"{tid}"' in wal_data, \
                    f"trade {tid} missing from {symbol}"


def test_multi_symbol_recovery_independent():
    """Восстановление партиции не зависит от других символов."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)

        # Session 1
        btc1 = EventCollector(base / "BTCUSDT", "BTCUSDT")
        eth1 = EventCollector(base / "ETHUSDT", "ETHUSDT")

        btc1.append_trade(make_trade("BTCUSDT", "1", 640000, 1000, 1672324800000))
        eth1.append_trade(make_trade("ETHUSDT", "2", 32000, 5000, 1672324800000))

        btc1.flush(); btc1.close()
        eth1.flush(); eth1.close()

        btc_size_1 = len(read_wal_bytes(base / "BTCUSDT"))
        eth_size_1 = len(read_wal_bytes(base / "ETHUSDT"))

        # Session 2: restart, добавить ещё
        btc2 = EventCollector(base / "BTCUSDT", "BTCUSDT")
        eth2 = EventCollector(base / "ETHUSDT", "ETHUSDT")

        btc2.append_trade(make_trade("BTCUSDT", "3", 640010, 2000, 1672324810000))
        eth2.append_trade(make_trade("ETHUSDT", "4", 32010, 3000, 1672324810000))

        btc2.flush(); btc2.close()
        eth2.flush(); eth2.close()

        # WAL вырос, старые данные сохранены
        btc_data = read_wal_bytes(base / "BTCUSDT")
        eth_data = read_wal_bytes(base / "ETHUSDT")

        assert len(btc_data) > btc_size_1, "BTC WAL did not grow after recovery"
        assert len(eth_data) > eth_size_1, "ETH WAL did not grow after recovery"

        # Оба trade ID присутствуют
        btc_text = btc_data.decode("utf-8", errors="ignore")
        assert '"trade_id":"1"' in btc_text
        assert '"trade_id":"3"' in btc_text


def test_multi_symbol_no_shared_state():
    """Коллекторы не разделяют внутреннее состояние."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)

        btc = EventCollector(base / "BTCUSDT", "BTCUSDT")
        eth = EventCollector(base / "ETHUSDT", "ETHUSDT")

        assert btc.partition_id != eth.partition_id
        assert btc.partition_dir != eth.partition_dir
        assert btc.wal is not eth.wal

        # Асимметричная нагрузка: 10 vs 2
        for i in range(10):
            btc.append_trade(make_trade("BTCUSDT", str(i), 640000 + i, 1000, 1672324800000 + i * 1000))
        for i in range(2):
            eth.append_trade(make_trade("ETHUSDT", str(100 + i), 32000 + i, 5000, 1672324800000 + i * 1000))

        btc.flush(); btc.close()
        eth.flush(); eth.close()

        btc_size = len(read_wal_bytes(base / "BTCUSDT"))
        eth_size = len(read_wal_bytes(base / "ETHUSDT"))

        assert btc_size > eth_size, "asymmetric load not reflected in WAL sizes"
