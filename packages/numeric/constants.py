"""
Numeric constants для Bybit instruments (Roadmap §4).

Источник: Bybit V5 API, category=linear
Инструменты: BTCUSDT, ETHUSDT, XRPUSDT

Формат:
- PRICE_TICK: минимальный шаг цены (Decimal)
- QTY_STEP: минимальный шаг количества (Decimal)

Roadmap §4: price/qty храним как scaled integers (priceTicks, qtySteps).
Конверсия: price = priceTicks * PRICE_TICK, qty = qtySteps * QTY_STEP.
"""

from decimal import Decimal

# ===========================================================================
# BTCUSDT
# ===========================================================================

BTCUSDT_PRICE_TICK = Decimal("0.01")  # $0.01 tick size
BTCUSDT_QTY_STEP = Decimal("0.001")  # 0.001 BTC step size


# ===========================================================================
# ETHUSDT
# ===========================================================================

ETHUSDT_PRICE_TICK = Decimal("0.01")  # $0.01 tick size
ETHUSDT_QTY_STEP = Decimal("0.01")  # 0.01 ETH step size


# ===========================================================================
# XRPUSDT
# ===========================================================================

XRPUSDT_PRICE_TICK = Decimal("0.0001")  # $0.0001 tick size
XRPUSDT_QTY_STEP = Decimal("0.1")  # 0.1 XRP step size


# ===========================================================================
# Symbol Registry
# ===========================================================================

SYMBOL_CONSTANTS = {
    "BTCUSDT": {
        "price_tick": BTCUSDT_PRICE_TICK,
        "qty_step": BTCUSDT_QTY_STEP,
    },
    "ETHUSDT": {
        "price_tick": ETHUSDT_PRICE_TICK,
        "qty_step": ETHUSDT_QTY_STEP,
    },
    "XRPUSDT": {
        "price_tick": XRPUSDT_PRICE_TICK,
        "qty_step": XRPUSDT_QTY_STEP,
    },
}


def get_price_tick(symbol: str) -> Decimal:
    """Получить PRICE_TICK для символа.

    Args:
        symbol: идентификатор инструмента (BTCUSDT, ETHUSDT, XRPUSDT)

    Returns:
        Минимальный шаг цены

    Raises:
        ValueError: неизвестный symbol
    """
    if symbol not in SYMBOL_CONSTANTS:
        raise ValueError(f"Неизвестный symbol: {symbol}")
    return SYMBOL_CONSTANTS[symbol]["price_tick"]


def get_qty_step(symbol: str) -> Decimal:
    """Получить QTY_STEP для символа.

    Args:
        symbol: идентификатор инструмента (BTCUSDT, ETHUSDT, XRPUSDT)

    Returns:
        Минимальный шаг количества

    Raises:
        ValueError: неизвестный symbol
    """
    if symbol not in SYMBOL_CONSTANTS:
        raise ValueError(f"Неизвестный symbol: {symbol}")
    return SYMBOL_CONSTANTS[symbol]["qty_step"]


def price_to_ticks(symbol: str, price: Decimal) -> int:
    """Конвертировать price → priceTicks.

    Args:
        symbol: идентификатор инструмента
        price: цена в USDT

    Returns:
        Scaled integer (priceTicks)
    """
    tick = get_price_tick(symbol)
    return int(price / tick)


def ticks_to_price(symbol: str, ticks: int) -> Decimal:
    """Конвертировать priceTicks → price.

    Args:
        symbol: идентификатор инструмента
        ticks: scaled integer

    Returns:
        Цена в USDT
    """
    tick = get_price_tick(symbol)
    return Decimal(ticks) * tick


def qty_to_steps(symbol: str, qty: Decimal) -> int:
    """Конвертировать qty → qtySteps.

    Args:
        symbol: идентификатор инструмента
        qty: количество (BTC, ETH, XRP)

    Returns:
        Scaled integer (qtySteps)
    """
    step = get_qty_step(symbol)
    return int(qty / step)


def steps_to_qty(symbol: str, steps: int) -> Decimal:
    """Конвертировать qtySteps → qty.

    Args:
        symbol: идентификатор инструмента
        steps: scaled integer

    Returns:
        Количество (BTC, ETH, XRP)
    """
    step = get_qty_step(symbol)
    return Decimal(steps) * step
