"""
Тесты Time & Sales (Roadmap §9).

Проверяют: TimeAndSales, tape stats, large trade detection.
"""

import pytest

from packages.analytics.time_and_sales import TimeAndSales, TapeEntry, create_tape_from_trades

pytestmark = pytest.mark.contract


class TestTimeAndSales:
    """Тесты TimeAndSales tape engine."""

    def test_append_trade(self):
        """append_trade() добавляет запись в tape."""
        tape = TimeAndSales(max_entries=100)

        tape.append_trade(
            timestamp_us=1000,
            price_ticks=10000,
            qty_steps=100,
            aggressor_side="Buy",
            trade_id="trade_1",
        )

        assert len(tape.entries) == 1
        assert tape.entries[0].price_ticks == 10000
        assert tape.entries[0].aggressor_side == "Buy"

    def test_max_entries_trim(self):
        """Старые записи удаляются при превышении max_entries."""
        tape = TimeAndSales(max_entries=5)

        for i in range(10):
            tape.append_trade(
                timestamp_us=i * 1000,
                price_ticks=10000 + i,
                qty_steps=100,
                aggressor_side="Buy",
                trade_id=f"trade_{i}",
            )

        assert len(tape.entries) == 5
        # Должны остаться последние 5
        assert tape.entries[0].price_ticks == 10005

    def test_get_recent(self):
        """get_recent() возвращает последние N записей (newest first)."""
        tape = TimeAndSales(max_entries=100)

        for i in range(10):
            tape.append_trade(i * 1000, 10000 + i, 100, "Buy", f"trade_{i}")

        recent = tape.get_recent(count=3)

        assert len(recent) == 3
        assert recent[0].price_ticks == 10009  # newest first
        assert recent[1].price_ticks == 10008
        assert recent[2].price_ticks == 10007

    def test_get_range(self):
        """get_range() возвращает записи в диапазоне."""
        tape = TimeAndSales(max_entries=100)

        tape.append_trade(1000, 10000, 100, "Buy", "1")
        tape.append_trade(2000, 10001, 100, "Buy", "2")
        tape.append_trade(3000, 10002, 100, "Buy", "3")
        tape.append_trade(4000, 10003, 100, "Buy", "4")

        range_entries = tape.get_range(start_ts=2000, end_ts=4000)

        assert len(range_entries) == 2
        assert range_entries[0].timestamp_us == 2000
        assert range_entries[1].timestamp_us == 3000

    def test_calculate_tape_stats(self):
        """calculate_tape_stats() рассчитывает статистику."""
        tape = TimeAndSales(max_entries=100)

        tape.append_trade(1000, 10000, 100, "Buy", "1")
        tape.append_trade(2000, 10001, 50, "Sell", "2")
        tape.append_trade(3000, 10002, 200, "Buy", "3")

        stats = tape.calculate_tape_stats(window_entries=10)

        assert stats["total_volume"] == 350  # 100 + 50 + 200
        assert stats["buy_volume"] == 300
        assert stats["sell_volume"] == 50
        assert stats["buy_count"] == 2
        assert stats["sell_count"] == 1
        assert stats["avg_trade_size"] == pytest.approx(116.67, rel=0.01)
        assert stats["price_range_ticks"] == 2  # 10002 - 10000

    def test_detect_large_trades(self):
        """detect_large_trades() находит крупные сделки."""
        tape = TimeAndSales(max_entries=100)

        # Обычные сделки
        for i in range(10):
            tape.append_trade(i * 1000, 10000, 100, "Buy", f"trade_{i}")

        # Крупная сделка (3x от среднего)
        tape.append_trade(11000, 10000, 300, "Buy", "whale")

        large_trades = tape.detect_large_trades(threshold_multiplier=2.5)

        assert len(large_trades) >= 1
        assert large_trades[0].qty_steps == 300

    def test_create_tape_from_trades(self):
        """create_tape_from_trades() создаёт tape из RawTrade list."""
        trades = [
            {"timestampUs": 1000, "priceTicks": 10000, "qtySteps": 100, "takerSide": "Buy", "sequence": 1},
            {"timestampUs": 2000, "priceTicks": 10001, "qtySteps": 50, "takerSide": "Sell", "sequence": 2},
        ]

        tape = create_tape_from_trades(trades)

        assert len(tape.entries) == 2
        assert tape.entries[0].price_ticks == 10000
        assert tape.entries[1].price_ticks == 10001
