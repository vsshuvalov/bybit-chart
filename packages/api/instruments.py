"""
Instrument metadata models and constants.

Provides tick_size, qty_step, and other instrument-specific parameters
for accurate price/volume conversion.
"""

from typing import Literal
from pydantic import BaseModel

Symbol = Literal["BTCUSDT", "ETHUSDT", "XRPUSDT"]


class InstrumentInfo(BaseModel):
    """Instrument metadata for price/volume conversion."""

    symbol: str
    tick_size: float  # Price tick size (e.g., 0.1 for BTCUSDT)
    qty_step: float  # Quantity step (e.g., 0.001 for BTCUSDT)
    min_qty: float  # Minimum order quantity
    max_qty: float  # Maximum order quantity
    base_asset: str  # Base currency (BTC, ETH, XRP)
    quote_asset: str  # Quote currency (USDT)


# Bybit linear perpetual instrument specs (as of 2026-08)
INSTRUMENT_SPECS: dict[str, InstrumentInfo] = {
    "BTCUSDT": InstrumentInfo(
        symbol="BTCUSDT",
        tick_size=0.1,
        qty_step=0.001,
        min_qty=0.001,
        max_qty=100.0,
        base_asset="BTC",
        quote_asset="USDT",
    ),
    "ETHUSDT": InstrumentInfo(
        symbol="ETHUSDT",
        tick_size=0.01,
        qty_step=0.01,
        min_qty=0.01,
        max_qty=1000.0,
        base_asset="ETH",
        quote_asset="USDT",
    ),
    "XRPUSDT": InstrumentInfo(
        symbol="XRPUSDT",
        tick_size=0.0001,
        qty_step=0.1,
        min_qty=0.1,
        max_qty=10000.0,
        base_asset="XRP",
        quote_asset="USDT",
    ),
}


def get_instrument_info(symbol: str) -> InstrumentInfo:
    """Get instrument metadata.

    Args:
        symbol: Symbol identifier (BTCUSDT, ETHUSDT, XRPUSDT)

    Returns:
        InstrumentInfo with tick_size, qty_step, etc.

    Raises:
        KeyError: if symbol not found
    """
    if symbol not in INSTRUMENT_SPECS:
        raise KeyError(f"Unknown symbol: {symbol}")
    return INSTRUMENT_SPECS[symbol]


def ticks_to_price(ticks: int, symbol: str) -> float:
    """Convert price ticks to float price.

    Args:
        ticks: Price in ticks
        symbol: Instrument symbol

    Returns:
        Price as float
    """
    info = get_instrument_info(symbol)
    return ticks * info.tick_size


def steps_to_qty(steps: int, symbol: str) -> float:
    """Convert quantity steps to float quantity.

    Args:
        steps: Quantity in steps
        symbol: Instrument symbol

    Returns:
        Quantity as float
    """
    info = get_instrument_info(symbol)
    return steps * info.qty_step
