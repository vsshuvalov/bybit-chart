"""
Тесты numeric constants (Этап 1 / P1-B3).

Проверяют: PRICE_TICK, QTY_STEP для BTCUSDT/ETHUSDT/XRPUSDT, конверсии.
"""

from decimal import Decimal

import pytest

from packages.numeric.constants import (
    BTCUSDT_PRICE_TICK,
    BTCUSDT_QTY_STEP,
    ETHUSDT_PRICE_TICK,
    ETHUSDT_QTY_STEP,
    XRPUSDT_PRICE_TICK,
    XRPUSDT_QTY_STEP,
    get_price_tick,
    get_qty_step,
    price_to_ticks,
    ticks_to_price,
    qty_to_steps,
    steps_to_qty,
)

pytestmark = pytest.mark.contract


class TestSymbolConstants:
    """Тесты numeric constants для каждого symbol."""

    def test_btcusdt_constants(self):
        """BTCUSDT constants корректны."""
        assert BTCUSDT_PRICE_TICK == Decimal("0.01")
        assert BTCUSDT_QTY_STEP == Decimal("0.001")

    def test_ethusdt_constants(self):
        """ETHUSDT constants корректны."""
        assert ETHUSDT_PRICE_TICK == Decimal("0.01")
        assert ETHUSDT_QTY_STEP == Decimal("0.01")

    def test_xrpusdt_constants(self):
        """XRPUSDT constants корректны."""
        assert XRPUSDT_PRICE_TICK == Decimal("0.0001")
        assert XRPUSDT_QTY_STEP == Decimal("0.1")

    def test_get_price_tick_btcusdt(self):
        """get_price_tick('BTCUSDT') возвращает правильное значение."""
        assert get_price_tick("BTCUSDT") == Decimal("0.01")

    def test_get_price_tick_ethusdt(self):
        """get_price_tick('ETHUSDT') возвращает правильное значение."""
        assert get_price_tick("ETHUSDT") == Decimal("0.01")

    def test_get_price_tick_xrpusdt(self):
        """get_price_tick('XRPUSDT') возвращает правильное значение."""
        assert get_price_tick("XRPUSDT") == Decimal("0.0001")

    def test_get_price_tick_unknown_symbol(self):
        """get_price_tick() с неизвестным symbol → ValueError."""
        with pytest.raises(ValueError, match="Неизвестный symbol"):
            get_price_tick("UNKNOWN")

    def test_get_qty_step_btcusdt(self):
        """get_qty_step('BTCUSDT') возвращает правильное значение."""
        assert get_qty_step("BTCUSDT") == Decimal("0.001")

    def test_get_qty_step_ethusdt(self):
        """get_qty_step('ETHUSDT') возвращает правильное значение."""
        assert get_qty_step("ETHUSDT") == Decimal("0.01")

    def test_get_qty_step_xrpusdt(self):
        """get_qty_step('XRPUSDT') возвращает правильное значение."""
        assert get_qty_step("XRPUSDT") == Decimal("0.1")


class TestPriceConversion:
    """Тесты price ↔ ticks конверсии."""

    def test_btcusdt_price_to_ticks(self):
        """BTCUSDT: price → ticks."""
        ticks = price_to_ticks("BTCUSDT", Decimal("64000.00"))
        assert ticks == 6400000  # 64000.00 / 0.01

    def test_btcusdt_ticks_to_price(self):
        """BTCUSDT: ticks → price."""
        price = ticks_to_price("BTCUSDT", 6400000)
        assert price == Decimal("64000.00")

    def test_ethusdt_price_to_ticks(self):
        """ETHUSDT: price → ticks."""
        ticks = price_to_ticks("ETHUSDT", Decimal("3200.50"))
        assert ticks == 320050  # 3200.50 / 0.01

    def test_ethusdt_ticks_to_price(self):
        """ETHUSDT: ticks → price."""
        price = ticks_to_price("ETHUSDT", 320050)
        assert price == Decimal("3200.50")

    def test_xrpusdt_price_to_ticks(self):
        """XRPUSDT: price → ticks."""
        ticks = price_to_ticks("XRPUSDT", Decimal("0.5000"))
        assert ticks == 5000  # 0.5000 / 0.0001

    def test_xrpusdt_ticks_to_price(self):
        """XRPUSDT: ticks → price."""
        price = ticks_to_price("XRPUSDT", 5000)
        assert price == Decimal("0.5000")

    def test_price_roundtrip_btcusdt(self):
        """BTCUSDT: price → ticks → price (roundtrip)."""
        original = Decimal("64123.45")
        ticks = price_to_ticks("BTCUSDT", original)
        restored = ticks_to_price("BTCUSDT", ticks)
        assert restored == original

    def test_price_roundtrip_xrpusdt(self):
        """XRPUSDT: price → ticks → price (roundtrip)."""
        original = Decimal("0.5234")
        ticks = price_to_ticks("XRPUSDT", original)
        restored = ticks_to_price("XRPUSDT", ticks)
        assert restored == original


class TestQtyConversion:
    """Тесты qty ↔ steps конверсии."""

    def test_btcusdt_qty_to_steps(self):
        """BTCUSDT: qty → steps."""
        steps = qty_to_steps("BTCUSDT", Decimal("1.234"))
        assert steps == 1234  # 1.234 / 0.001

    def test_btcusdt_steps_to_qty(self):
        """BTCUSDT: steps → qty."""
        qty = steps_to_qty("BTCUSDT", 1234)
        assert qty == Decimal("1.234")

    def test_ethusdt_qty_to_steps(self):
        """ETHUSDT: qty → steps."""
        steps = qty_to_steps("ETHUSDT", Decimal("12.50"))
        assert steps == 1250  # 12.50 / 0.01

    def test_ethusdt_steps_to_qty(self):
        """ETHUSDT: steps → qty."""
        qty = steps_to_qty("ETHUSDT", 1250)
        assert qty == Decimal("12.50")

    def test_xrpusdt_qty_to_steps(self):
        """XRPUSDT: qty → steps."""
        steps = qty_to_steps("XRPUSDT", Decimal("100.5"))
        assert steps == 1005  # 100.5 / 0.1

    def test_xrpusdt_steps_to_qty(self):
        """XRPUSDT: steps → qty."""
        qty = steps_to_qty("XRPUSDT", 1005)
        assert qty == Decimal("100.5")

    def test_qty_roundtrip_btcusdt(self):
        """BTCUSDT: qty → steps → qty (roundtrip)."""
        original = Decimal("0.123")
        steps = qty_to_steps("BTCUSDT", original)
        restored = steps_to_qty("BTCUSDT", steps)
        assert restored == original

    def test_qty_roundtrip_xrpusdt(self):
        """XRPUSDT: qty → steps → qty (roundtrip)."""
        original = Decimal("123.4")
        steps = qty_to_steps("XRPUSDT", original)
        restored = steps_to_qty("XRPUSDT", steps)
        assert restored == original
