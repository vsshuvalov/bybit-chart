"""
Канонические числовые примитивы платформы.
Источник: Roadmap §6.6, all-modules-data-persistence-architecture.md §3

Правило: для persistent/replay данных binary float запрещён.
  price       → PriceTicks (int, int64-совместимый)
  quantity    → QtySteps (int, int64-совместимый)
  turnover/OI/funding/VWAP → Decimal128 (decimal.Decimal, Decimal128-совместимый)
"""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import TypeAlias

# ---------------------------------------------------------------------------
# Типы-алиасы
# ---------------------------------------------------------------------------

# priceTicks: int64-совместимый целочисленный тик.
# Не должен использоваться как ключ float-словаря.
PriceTicks: TypeAlias = int

# qtySteps: int64-совместимый целочисленный шаг количества.
QtySteps: TypeAlias = int

# Decimal128: decimal.Decimal — wire-format и хранение.
# float допустим только в UI и некритичных визуальных вычислениях.
Decimal128: TypeAlias = Decimal

# ---------------------------------------------------------------------------
# Границы (int64)
# ---------------------------------------------------------------------------

PRICE_TICKS_MAX: int = (1 << 63) - 1   # 9_223_372_036_854_775_807
QTY_STEPS_MAX: int = (1 << 63) - 1


# ---------------------------------------------------------------------------
# Фабричные функции
# ---------------------------------------------------------------------------

def price_ticks_from_str(value: str) -> PriceTicks:
    """Разобрать строковое целое в PriceTicks.

    Принимает только строки — защита от случайного передачи float.
    Используется при десериализации JSON (Bybit присылает числа в строках).
    """
    if not isinstance(value, str):
        raise TypeError(
            f"price_ticks_from_str требует str, получен {type(value).__name__!r}. "
            "JSON int64 должен передаваться как строка."
        )
    try:
        result = int(value)
    except ValueError as exc:
        raise ValueError(f"Некорректный priceTicks: {value!r}") from exc
    if result < 0:
        raise ValueError(f"priceTicks не может быть отрицательным: {result}")
    if result > PRICE_TICKS_MAX:
        raise ValueError(f"priceTicks превышает int64 max: {result}")
    return result


def qty_steps_from_str(value: str) -> QtySteps:
    """Разобрать строковое целое в QtySteps."""
    if not isinstance(value, str):
        raise TypeError(
            f"qty_steps_from_str требует str, получен {type(value).__name__!r}."
        )
    try:
        result = int(value)
    except ValueError as exc:
        raise ValueError(f"Некорректный qtySteps: {value!r}") from exc
    if result < 0:
        raise ValueError(f"qtySteps не может быть отрицательным: {result}")
    if result > QTY_STEPS_MAX:
        raise ValueError(f"qtySteps превышает int64 max: {result}")
    return result


def decimal128_from_str(value: str) -> Decimal128:
    """Разобрать строковое число в Decimal128.

    Принимает строки. Отклоняет float и специальные значения (NaN, Inf).
    """
    if not isinstance(value, str):
        raise TypeError(
            f"decimal128_from_str требует str, получен {type(value).__name__!r}."
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Некорректный Decimal128: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Decimal128 должен быть конечным, получен: {value!r}")
    return result


# ---------------------------------------------------------------------------
# Валидаторы
# ---------------------------------------------------------------------------

def validate_price_ticks(value: int) -> PriceTicks:
    """Проверить диапазон уже разобранного PriceTicks."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"priceTicks должен быть int, получен {type(value).__name__!r}")
    if value <= 0:
        raise ValueError(f"priceTicks должен быть > 0, получен {value}")
    if value > PRICE_TICKS_MAX:
        raise ValueError(f"priceTicks превышает int64 max: {value}")
    return value


def validate_qty_steps(value: int) -> QtySteps:
    """Проверить диапазон уже разобранного QtySteps."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"qtySteps должен быть int, получен {type(value).__name__!r}")
    if value <= 0:
        raise ValueError(f"qtySteps должен быть > 0, получен {value}")
    if value > QTY_STEPS_MAX:
        raise ValueError(f"qtySteps превышает int64 max: {value}")
    return value
