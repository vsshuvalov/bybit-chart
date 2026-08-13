"""Контрактные тесты standalone dashboard треугольного PAPER-арбитража."""

import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract
HTML_PATH = Path(__file__).parents[2] / "frontend" / "triangular.html"


@pytest.fixture(scope="module")
def html() -> str:
    assert HTML_PATH.exists(), "frontend/triangular.html должен существовать"
    return HTML_PATH.read_text(encoding="utf-8")


def test_page_is_standalone_russian_paper_dashboard(html: str) -> None:
    assert '<html lang="ru">' in html
    assert "Треугольный арбитраж · Lab" in html
    assert "PAPER" in html
    assert "Публичные данные · без API-ключей" in html
    assert "Реальных ордеров и приватных API нет" in html
    assert '<a class="back-link" href="/">' in html
    assert "<script src=" not in html
    assert '<link rel="stylesheet"' not in html


def test_controls_match_triangular_request_contract(html: str) -> None:
    for venue, label in (
        ("all", "Все биржи"),
        ("bybit", "Bybit"),
        ("binance", "Binance"),
        ("okx", "OKX"),
        ("bitget", "Bitget"),
        ("huobi", "Huobi"),
        ("kucoin", "KuCoin"),
        ("mexc", "MEXC"),
        ("bingx", "BingX"),
        ("gate", "Gate"),
    ):
        assert f'<option value="{venue}">{label}</option>' in html
    for asset in ("USDT", "BTC", "ETH", "BNB", "BRL"):
        assert f'value="{asset}"' in html
    for field in (
        "venue",
        "start_asset",
        "start_amount",
        "min_net_edge_bps",
        "risk_buffer_bps",
        "interval_ms",
        "auto_execute",
        "use_fee_token_discounts",
        "max_tickers",
    ):
        assert field in html
    assert 'id="maxTickers"' in html
    assert 'min="50" max="50"' in html
    assert "max_tickers: 50" in html
    assert "Запустить скан" in html
    assert "Старт монитора" in html
    assert "Стоп монитора" in html


def test_fee_token_discount_what_if_is_explicit_and_synced(html: str) -> None:
    assert 'id="useFeeTokenDiscounts" name="use_fee_token_discounts" type="checkbox"' in html
    assert 'aria-describedby="tip-fee-token-discounts" checked' in html
    assert "use_fee_token_discounts: $('useFeeTokenDiscounts').checked" in html
    assert "first(settings, ['use_fee_token_discounts'], null)" in html
    assert "'useFeeTokenDiscounts'" in html.split("function syncControlAvailability()", 1)[1]
    assert "PAPER what-if" in html
    assert "токена достаточно" in html
    assert "Цена токена и его курсовой риск не моделируются" in html
    assert "для Bybit, OKX и BingX скидка равна 0" in html
    for contract_key in (
        "fee_policy",
        "fee_token_balance_mode",
        "fee_token_balance_assumption",
        "fee_token_balance_explanation",
        "token",
        "base_taker_fee_bps",
        "effective_taker_fee_bps",
        "discount_bps",
        "enabled",
        "api_compatible",
        "assumption",
    ):
        assert contract_key in html
    assert 'id="feePolicyPanel"' in html
    assert 'id="feePolicySummary"' in html
    assert 'id="feePolicyList"' in html
    assert "Ставки комиссий по биржам" in html
    assert "function normalizeFeePolicy(raw)" in html
    assert "function renderFeePolicy(data)" in html
    assert "renderFeePolicy(data)" in html


def test_triangular_journal_shows_effective_fee_rates(html: str) -> None:
    assert "<th>Комиссии</th>" in html
    assert 'colspan="9" class="journal-empty"' in html
    assert "fee_rate_bps" in html
    assert "effective_taker_fee_bps" in html
    assert "const feeText =" in html


def test_api_contract_and_status_polling(html: str) -> None:
    for path in ("status", "scan", "start", "stop", "reset"):
        assert f"'/api/v1/triangular/{path}'" in html
    assert "method: 'POST'" in html
    assert "const POLL_INTERVAL_MS = 2000" in html
    assert "window.setInterval" in html


def test_required_triangular_sections_are_present(html: str) -> None:
    for text in (
        "Лучший путь A → B → C → A",
        "Gross edge",
        "Net edge",
        "Expected P&amp;L",
        "Состояние бирж",
        "Отбор ликвидных тикеров",
        "Виртуальные балансы",
        "Журнал PAPER-циклов",
        "Ошибки и предупреждения",
    ):
        assert text in html
    assert "Нога ${index + 1}" in html
    assert "Array.from({ length: 3 }" in html


def test_help_tooltips_are_accessible_on_every_control_and_panel(html: str) -> None:
    assert html.count('class="info-button"') >= 23
    assert html.count('role="tooltip"') == html.count('class="info-button"')
    described = re.findall(
        r'class="info-button"[^>]*aria-describedby="([^"]+)"', html
    )
    tooltip_ids = re.findall(r'class="info-tooltip" id="([^"]+)"', html)
    assert described
    assert len(tooltip_ids) == len(set(tooltip_ids))
    assert set(described) == set(tooltip_ids)
    assert ".info-tip:hover .info-tooltip" in html
    assert ".info-tip:focus-within .info-tooltip" in html
    assert ".info-button:focus-visible" in html

    for control_id in (
        "venue",
        "startAsset",
        "startAmount",
        "maxTickers",
        "minEdge",
        "riskBuffer",
        "intervalMs",
        "autoExecute",
        "scanButton",
        "startButton",
        "stopButton",
        "resetButton",
    ):
        control = re.search(rf'<(?:input|select|button)\b[^>]*id="{control_id}"[^>]*>', html)
        assert control, f"control {control_id} должен существовать"
        assert 'aria-describedby="tip-' in control.group(0)

    for panel_tip in (
        "tip-controls",
        "tip-best-edge",
        "tip-best-pnl",
        "tip-ticker-count",
        "tip-cycle-count",
        "tip-opportunity",
        "tip-universe",
        "tip-journal",
        "tip-venues",
        "tip-balances",
        "tip-errors",
    ):
        assert panel_tip in tooltip_ids


def test_execution_copy_is_minimal_and_no_fake_initial_balance_control(html: str) -> None:
    assert '<span class="switch-copy"><strong>Auto-paper</strong></span>' in html
    assert "Атомарно, только виртуально" not in html
    assert ".switch-copy small" not in html
    assert "initialBalance" not in html
    assert "initial_balance_per_venue_usdt" not in html


def test_user_facing_copy_uses_russian_exchange_terminology(html: str) -> None:
    visible = re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.DOTALL)
    visible_text = re.sub(r"<[^>]+>", " ", visible)
    assert re.search(r"бирж", visible_text, flags=re.IGNORECASE)
    assert re.search(r"\bvenue\b", visible_text, flags=re.IGNORECASE) is None


def test_control_panel_is_compact(html: str) -> None:
    assert ".control-panel .panel-head { min-height: 50px; padding: 10px 16px; }" in html
    assert "grid-template-columns: repeat(4, minmax(138px, 1fr))" in html
    assert "padding: 12px 16px 10px" in html
    assert "height: 38px" in html


def test_status_contract_fields_are_rendered(html: str) -> None:
    for field in (
        "venues",
        "ticker_count",
        "selected_ticker_count",
        "ticker_universe",
        "best_opportunity",
        "opportunities",
        "route",
        "path",
        "legs",
        "start_amount",
        "final_amount",
        "gross_edge_bps",
        "net_edge_bps",
        "expected_pnl",
        "balances",
        "journal",
        "errors",
    ):
        assert field in html


def test_decimal_strings_empty_state_and_dynamic_html_are_safe(html: str) -> None:
    assert "function finite(value, fallback = 0)" in html
    assert "const parsed = Number(value)" in html
    assert "if (!opportunity || typeof opportunity !== 'object')" in html
    assert "function escapeHTML(value)" in html
    assert "'&': '&amp;'" in html
    assert "'<': '&lt;'" in html
    assert "'>': '&gt;'" in html
    assert "escapeHTML(venue ? `${venue}: ${message}` : message)" in html
    assert "escapeHTML(symbol)" in html


def test_layout_is_adaptive(html: str) -> None:
    assert "@media (max-width: 1120px)" in html
    assert "@media (max-width: 820px)" in html
    assert "@media (max-width: 600px)" in html
    assert "@media (prefers-reduced-motion: reduce)" in html
