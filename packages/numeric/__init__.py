# packages/numeric — канонические числовые примитивы платформы
# Источник: Roadmap §6.6, all-modules-data-persistence-architecture.md §3
#
# Правило: для всего, что хранится и участвует в replay, binary float запрещён.
# price       → priceTicks: int (int64-совместимый)
# quantity    → qtySteps: int (int64-совместимый)
# turnover    → Decimal (scaled integer / Decimal128-совместимый)
# OI          → Decimal
# funding     → Decimal
# VWAP sums   → Decimal

from decimal import Decimal

from packages.numeric.primitives import (
    PriceTicks,
    QtySteps,
    Decimal128,
    price_ticks_from_str,
    qty_steps_from_str,
    decimal128_from_str,
    PRICE_TICKS_MAX,
    QTY_STEPS_MAX,
    validate_price_ticks,
    validate_qty_steps,
)

# Инструмент-специфичные константы (Bybit BTCUSDT Linear Perpetual)
# Источник: https://bybit-exchange.github.io/docs/v5/market/instrument
# priceFilter.tickSize = "0.10"
# lotSizeFilter.qtyStep = "0.001"
BTCUSDT_PRICE_TICK = Decimal("0.10")  # минимальный шаг цены
BTCUSDT_QTY_STEP = Decimal("0.001")   # минимальный шаг количества

__all__ = [
    "PriceTicks",
    "QtySteps",
    "Decimal128",
    "price_ticks_from_str",
    "qty_steps_from_str",
    "decimal128_from_str",
    "PRICE_TICKS_MAX",
    "QTY_STEPS_MAX",
    "validate_price_ticks",
    "validate_qty_steps",
    "BTCUSDT_PRICE_TICK",
    "BTCUSDT_QTY_STEP",
]
