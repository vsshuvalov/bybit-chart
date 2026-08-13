"""Central PAPER assumptions for taker fees and fee-token discounts.

The prototype has no authenticated account data and never buys or debits a
fee token.  Discounts in this module are therefore a transparent what-if
model: an enabled row assumes that the account has enough of the named token
and that the exchange applies the standard API-compatible discount.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping

from packages.arbitrage.models import decimal_string, decimal_value


BPS = Decimal("10000")
ONE = Decimal("1")


DEFAULT_BASE_TAKER_FEES: dict[str, Decimal] = {
    "bybit": Decimal("0.001"),
    "binance": Decimal("0.001"),
    "okx": Decimal("0.001"),
    "bitget": Decimal("0.001"),
    "huobi": Decimal("0.002"),
    "kucoin": Decimal("0.001"),
    "mexc": Decimal("0.0005"),
    "bingx": Decimal("0.001"),
    "gate": Decimal("0.001"),
}


@dataclass(frozen=True, slots=True)
class FeeTokenDiscount:
    """One explicitly modelled standard fee-token discount."""

    token: str | None
    discount_rate: Decimal
    api_compatible: bool
    assumption: str
    source_category: str


DEFAULT_FEE_TOKEN_DISCOUNTS: dict[str, FeeTokenDiscount] = {
    "bybit": FeeTokenDiscount(
        token="MNT",
        discount_rate=Decimal("0"),
        api_compatible=False,
        assumption="MNT discount is excluded from the public/API PAPER model",
        source_category="api_compatibility_exclusion",
    ),
    "binance": FeeTokenDiscount(
        token="BNB",
        discount_rate=Decimal("0.25"),
        api_compatible=True,
        assumption="standard spot BNB fee-payment discount",
        source_category="standard_fee_token_discount",
    ),
    "okx": FeeTokenDiscount(
        token="OKB",
        discount_rate=Decimal("0"),
        api_compatible=False,
        assumption="no standard API fee-payment token discount is modelled",
        source_category="no_api_compatible_discount_modelled",
    ),
    "bitget": FeeTokenDiscount(
        token="BGB",
        discount_rate=Decimal("0.20"),
        api_compatible=True,
        assumption="standard spot BGB fee-payment discount",
        source_category="standard_fee_token_discount",
    ),
    "huobi": FeeTokenDiscount(
        token="HTX",
        discount_rate=Decimal("0.25"),
        api_compatible=True,
        assumption="standard spot HTX deduction discount",
        source_category="standard_fee_token_discount",
    ),
    "kucoin": FeeTokenDiscount(
        token="KCS",
        discount_rate=Decimal("0.20"),
        api_compatible=True,
        assumption="standard spot KCS Pay Fees discount",
        source_category="standard_fee_token_discount",
    ),
    "mexc": FeeTokenDiscount(
        token="MX",
        discount_rate=Decimal("0.20"),
        api_compatible=True,
        assumption="standard spot MX fee deduction discount",
        source_category="standard_fee_token_discount",
    ),
    "bingx": FeeTokenDiscount(
        token=None,
        discount_rate=Decimal("0"),
        api_compatible=False,
        assumption="no exchange-token fee discount is modelled",
        source_category="no_api_compatible_discount_modelled",
    ),
    "gate": FeeTokenDiscount(
        token="GT",
        discount_rate=Decimal("0.10"),
        api_compatible=True,
        assumption="VIP 0 GT fee-payment discount assumption",
        source_category="vip0_fee_token_discount_assumption",
    ),
}


def _venue(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("venue must be a string")
    result = value.strip().lower()
    if not result:
        raise ValueError("venue must not be empty")
    return result


def _base_fee(value: Decimal | str | int | float, *, venue: str) -> Decimal:
    fee = decimal_value(value, name=f"taker fee for {venue}")
    if fee < 0 or fee >= ONE:
        raise ValueError("taker fees must be in [0, 1)")
    return fee


def resolve_base_taker_fees(
    venues: Iterable[str],
    overrides: Mapping[str, Decimal | str | int | float] | None = None,
) -> dict[str, Decimal]:
    """Return validated BASE rates for every configured exchange.

    Constructor overrides remain base rates.  Missing custom rows fall back to
    the central exchange assumption (or 10 bps for an unknown test adapter).
    """

    normalized_overrides = {
        _venue(venue): _base_fee(raw_fee, venue=_venue(venue))
        for venue, raw_fee in (overrides or {}).items()
    }
    return {
        normalized: normalized_overrides.get(
            normalized,
            DEFAULT_BASE_TAKER_FEES.get(normalized, Decimal("0.001")),
        )
        for normalized in dict.fromkeys(_venue(venue) for venue in venues)
    }


def effective_taker_fees(
    base_fees: Mapping[str, Decimal | str | int | float],
    *,
    use_fee_token_discounts: bool,
) -> dict[str, Decimal]:
    """Apply eligible relative discounts to base rates, without token debits."""

    if not isinstance(use_fee_token_discounts, bool):
        raise TypeError("use_fee_token_discounts must be a boolean")
    effective: dict[str, Decimal] = {}
    for raw_venue, raw_fee in base_fees.items():
        venue = _venue(raw_venue)
        base_fee = _base_fee(raw_fee, venue=venue)
        policy = DEFAULT_FEE_TOKEN_DISCOUNTS.get(venue)
        discount = (
            policy.discount_rate
            if use_fee_token_discounts
            and policy is not None
            and policy.api_compatible
            else Decimal("0")
        )
        effective[venue] = base_fee * (ONE - discount)
    return effective


def fee_policy_status(
    base_fees: Mapping[str, Decimal | str | int | float],
    *,
    use_fee_token_discounts: bool,
) -> dict[str, dict[str, Any]]:
    """Serialize the exact per-exchange assumptions exposed by the API."""

    effective = effective_taker_fees(
        base_fees,
        use_fee_token_discounts=use_fee_token_discounts,
    )
    rows: dict[str, dict[str, Any]] = {}
    for raw_venue, raw_fee in sorted(base_fees.items()):
        venue = _venue(raw_venue)
        base_fee = _base_fee(raw_fee, venue=venue)
        policy = DEFAULT_FEE_TOKEN_DISCOUNTS.get(venue)
        discount = Decimal("0") if policy is None else policy.discount_rate
        applied = bool(
            use_fee_token_discounts
            and policy is not None
            and policy.api_compatible
            and discount > 0
        )
        rows[venue] = {
            "token": None if policy is None else policy.token,
            "base_taker_fee": decimal_string(base_fee),
            "base_taker_fee_bps": decimal_string(base_fee * BPS),
            "effective_taker_fee": decimal_string(effective[venue]),
            "effective_taker_fee_bps": decimal_string(effective[venue] * BPS),
            "discount_bps": decimal_string(discount * BPS),
            "enabled": applied,
            "api_compatible": bool(policy and policy.api_compatible),
            "assumption": (
                "no fee-token discount policy for this configured exchange"
                if policy is None
                else policy.assumption
            ),
            "source_category": (
                "custom_or_unknown_exchange_assumption"
                if policy is None
                else policy.source_category
            ),
        }
    return rows


__all__ = [
    "DEFAULT_BASE_TAKER_FEES",
    "DEFAULT_FEE_TOKEN_DISCOUNTS",
    "FeeTokenDiscount",
    "effective_taker_fees",
    "fee_policy_status",
    "resolve_base_taker_fees",
]
