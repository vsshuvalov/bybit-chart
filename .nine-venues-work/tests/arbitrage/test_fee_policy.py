from decimal import Decimal

import pytest

from packages.arbitrage.fee_policy import (
    DEFAULT_BASE_TAKER_FEES,
    effective_taker_fees,
    fee_policy_status,
    resolve_base_taker_fees,
)


pytestmark = pytest.mark.contract
D = Decimal


def test_central_base_rates_and_default_effective_discounts_are_exact() -> None:
    assert DEFAULT_BASE_TAKER_FEES == {
        "bybit": D("0.001"),
        "binance": D("0.001"),
        "okx": D("0.001"),
        "bitget": D("0.001"),
        "huobi": D("0.002"),
        "kucoin": D("0.001"),
        "mexc": D("0.0005"),
        "bingx": D("0.001"),
        "gate": D("0.001"),
    }
    assert effective_taker_fees(
        DEFAULT_BASE_TAKER_FEES,
        use_fee_token_discounts=True,
    ) == {
        "bybit": D("0.001"),
        "binance": D("0.00075"),
        "okx": D("0.001"),
        "bitget": D("0.00080"),
        "huobi": D("0.00150"),
        "kucoin": D("0.00080"),
        "mexc": D("0.000400"),
        "bingx": D("0.001"),
        "gate": D("0.00090"),
    }


def test_toggle_off_and_custom_base_rates_do_not_apply_hidden_discounts() -> None:
    base = resolve_base_taker_fees(
        ("binance", "alpha"),
        {"binance": "0.002", "alpha": "0.003"},
    )
    assert effective_taker_fees(
        base,
        use_fee_token_discounts=False,
    ) == {"binance": D("0.002"), "alpha": D("0.003")}
    assert effective_taker_fees(
        base,
        use_fee_token_discounts=True,
    ) == {"binance": D("0.00150"), "alpha": D("0.003")}


def test_status_exposes_auditable_what_if_policy_without_token_balances() -> None:
    status = fee_policy_status(
        {
            "binance": D("0.001"),
            "bybit": D("0.001"),
            "mexc": D("0.0005"),
            "gate": D("0.001"),
        },
        use_fee_token_discounts=True,
    )

    assert status["binance"] == {
        "token": "BNB",
        "base_taker_fee": "0.001",
        "base_taker_fee_bps": "10.000",
        "effective_taker_fee": "0.00075",
        "effective_taker_fee_bps": "7.50000",
        "discount_bps": "2500.00",
        "enabled": True,
        "api_compatible": True,
        "assumption": "standard spot BNB fee-payment discount",
        "source_category": "standard_fee_token_discount",
    }
    assert status["bybit"]["token"] == "MNT"
    assert status["bybit"]["discount_bps"] == "0"
    assert status["bybit"]["enabled"] is False
    assert status["bybit"]["api_compatible"] is False
    assert status["mexc"]["base_taker_fee_bps"] == "5.0000"
    assert status["mexc"]["effective_taker_fee_bps"] == "4.000000"
    assert status["gate"]["base_taker_fee_bps"] == "10.000"
    assert status["gate"]["effective_taker_fee_bps"] == "9.00000"
