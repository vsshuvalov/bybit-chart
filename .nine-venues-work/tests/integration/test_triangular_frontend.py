"""Контрактные тесты standalone dashboard треугольного PAPER-арбитража."""

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
    for venue in (
        "all",
        "bybit",
        "binance",
        "okx",
        "bitget",
        "huobi",
        "kucoin",
        "mexc",
        "bingx",
        "gate",
    ):
        assert f'value="{venue}"' in html
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
        "max_tickers",
    ):
        assert field in html
    assert 'id="maxTickers"' in html
    assert 'min="50" max="50"' in html
    assert "max_tickers: 50" in html
    assert "Запустить скан" in html
    assert "Старт монитора" in html
    assert "Стоп монитора" in html


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
        "Здоровье venue",
        "Universe ликвидных тикеров",
        "Виртуальные балансы",
        "Журнал PAPER-циклов",
        "Ошибки и предупреждения",
    ):
        assert text in html
    assert "Нога ${index + 1}" in html
    assert "Array.from({ length: 3 }" in html


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
