"""Контрактные тесты межбиржевого PAPER dashboard."""

from pathlib import Path
import re

import pytest


pytestmark = pytest.mark.contract
HTML_PATH = Path(__file__).parents[2] / "frontend" / "arbitrage.html"


@pytest.fixture(scope="module")
def html() -> str:
    assert HTML_PATH.exists(), "frontend/arbitrage.html должен существовать"
    return HTML_PATH.read_text(encoding="utf-8")


def test_page_is_standalone_russian_paper_ui(html: str) -> None:
    assert '<html lang="ru">' in html
    assert "PAPER" in html
    assert "Публичные данные" in html
    assert "Без API-ключей" in html
    assert "Реальные ордера, переводы и приватные API здесь недоступны" in html
    assert "<script src=" not in html
    assert "<link rel=\"stylesheet\"" not in html


def test_scan_controls_cover_supported_contract(html: str) -> None:
    assert 'id="symbol"' not in html
    assert 'name="symbol"' not in html
    assert "symbol: 'AUTO'" in html
    for field in (
        "symbol",
        "notional",
        "min_net_edge_bps",
        "risk_buffer_bps",
        "interval_ms",
        "auto_execute",
        "max_symbols",
        "activation_observations",
        "evidence_window_minutes",
        "inventory_idle_timeout_minutes",
        "max_active_symbols",
        "allocation_per_symbol_venue_usdt",
        "min_24h_volume_usdt",
        "bbo_depth_multiplier",
    ):
        assert field in html
    assert "max_symbols: 50" in html
    assert "function syncAutoMode()" in html
    assert "oneSecond.disabled = true" in html
    assert 'id="notionalLabel">Лимит сделки, USDT</label>' in html
    assert 'id="notional" name="notional" type="number" min="10" max="500" step="5" value="25"' in html
    assert "function normalizeCandidateEvidence(data)" in html
    assert "устойчивость ${escapeHTML(observations)}/${escapeHTML(required)}" in html
    assert "strategy_pnl_usdt" in html
    assert "весь портфель по bid" in html
    assert "buy_fee_rate_bps" in html
    assert "sell_fee_rate_bps" in html
    assert "loading || state.running" in html
    assert "state.remoteScanning || state.running" in html
    assert "Запустить скан" in html
    assert "Старт монитора" in html
    assert "Стоп монитора" in html
    assert "Сбросить виртуальный портфель" in html


def test_auto_inventory_controls_have_defaults_payload_and_budget_guard(html: str) -> None:
    expected_controls = {
        "activationObservations": ('name="activation_observations"', 'value="5"'),
        "evidenceWindowMinutes": ('name="evidence_window_minutes"', 'value="60"'),
        "inventoryIdleTimeoutMinutes": (
            'name="inventory_idle_timeout_minutes"',
            'value="60"',
        ),
        "maxActiveSymbols": ('name="max_active_symbols"', 'value="2"'),
        "allocationPerSymbol": (
            'name="allocation_per_symbol_venue_usdt"',
            'value="50"',
        ),
        "min24hVolume": (
            'name="min_24h_volume_usdt"',
            'min="100000"',
            'max="100000000"',
            'value="1000000"',
        ),
        "bboDepthMultiplier": ('name="bbo_depth_multiplier"', 'value="2"'),
    }
    for control_id, fragments in expected_controls.items():
        assert f'id="{control_id}"' in html
        for fragment in fragments:
            assert fragment in html

    for payload_mapping in (
        "activation_observations: Math.trunc(finite($('activationObservations').value))",
        "evidence_window_minutes: Math.trunc(finite($('evidenceWindowMinutes').value))",
        "inventory_idle_timeout_minutes: Math.trunc(finite($('inventoryIdleTimeoutMinutes').value))",
        "max_active_symbols: Math.trunc(finite($('maxActiveSymbols').value))",
        "allocation_per_symbol_venue_usdt: finite($('allocationPerSymbol').value)",
        "min_24h_volume_usdt: finite($('min24hVolume').value)",
        "bbo_depth_multiplier: finite($('bboDepthMultiplier').value)",
    ):
        assert payload_mapping in html

    assert 'id="initialBalance" name="initial_balance_per_venue_usdt"' in html
    assert 'value="500"' in html
    assert "maxActive * allocation + notional" in html
    assert "allocation >= notional" in html
    assert "function validateAutoBudget" in html
    assert "AUTO-бюджет превышен" in html
    assert "доступно ${compact.format(initialBalance)} USDT на биржу" in html
    assert "allocationInput.setCustomValidity(message)" in html
    assert "свободный резерв" in html
    assert "не может быть меньше суммы одной сделки" in html
    assert "$('scanForm').reportValidity()" in html
    assert "function syncControlAvailability()" in html
    assert "const locked = state.running || state.monitorActionInFlight" in html
    assert "$(id).disabled = locked" in html
    assert "syncControlAvailability();" in html
    assert "Наблюдений устойчивости" in html
    assert "Окно устойчивости, мин" in html
    assert "Выход вне рейтинга, мин" in html
    assert "текущий прибыльный маршрут получает приоритет" in html
    assert "Мин. оборот 24ч, USDT" in html
    assert "Запас BBO-глубины, ×" in html
    assert "function syncSettingsFromStatus(data)" in html
    for settings_mapping in (
        "assign('inventoryIdleTimeoutMinutes', 'inventory_idle_timeout_minutes')",
        "assign('min24hVolume', 'min_24h_volume_usdt')",
        "assign('bboDepthMultiplier', 'bbo_depth_multiplier')",
    ):
        assert settings_mapping in html
    assert "settingsHydrated" in html


def test_initial_balance_requires_explicit_session_reset(html: str) -> None:
    assert "Применить и сбросить" in html
    assert "пересоздаёт PAPER-сессию" in html
    assert "$('applyBalanceButton').addEventListener" in html
    assert "resetPaperPortfolio({ applyBalance: true })" in html
    assert "JSON.stringify({ initial_balance_per_venue_usdt: initialBalance })" in html
    payload_source = html.split("function currentPayload()", 1)[1].split(
        "$('scanForm').addEventListener", 1
    )[0]
    assert "initial_balance_per_venue_usdt: finite($('initialBalance').value)" in payload_source
    assert "state.initialBalanceDirty = true" in html
    assert "if (state.initialBalanceDirty)" in html
    assert "Сначала нажмите «Применить и сбросить»" in html
    assert "state.initialBalanceDirty = false" in html
    assert 'min="100" max="1000000"' in html
    assert "Стартовый баланс должен быть не меньше 100 USDT" in html
    assert "Стартовый баланс не может превышать 1 000 000 USDT" in html


def test_signal_visibility_renders_stale_near_miss_and_diagnostics(html: str) -> None:
    for status_field in (
        "best_near_miss",
        "last_profitable_signal",
        "diagnostics",
        "funnel",
        "rejection_counts",
        "rejection_reasons",
        "threshold_gap_bps",
        "observed_at_ms",
        "age_ms",
        "execution_blockers",
    ):
        assert status_field in html

    assert "function normalizeOpportunityView(data)" in html
    assert "function opportunityAgeMs(opportunity)" in html
    assert "function readableRejectionReason(value)" in html
    assert "function renderDiagnostics(diagnostics)" in html
    assert "function currentExecutionBlockers(data, opportunity)" in html
    assert "Текущая исполнимая сделка" in html
    assert "Текущий сигнал — заблокирован" in html
    assert "Исторический сигнал" in html
    assert "Это не текущая возможность" in html
    assert "Наблюдение — не сделка" in html
    assert "Почему нет сделки" in html
    assert "Воронка сканирования" in html
    assert "недостаточная BBO-глубина" in html
    assert "оборот за 24 часа ниже фильтра" in html
    assert "нет токена для продажи" in html
    assert "комиссии и risk buffer делают net edge неположительным" in html
    assert "котировки бирж получены в слишком разное время" in html
    assert "missing_sell_inventory" in html
    assert "на бирже продажи закончился нужный токен" in html
    assert "insufficient_sell_inventory" in html
    assert "inventory_not_active" in html
    assert "inventory_pending_liquidation" in html
    assert "rebalance_snapshot_consumed" in html
    assert "duplicate_execution_snapshot" in html
    assert "kind: blockers.length ? 'blocked' : 'executable'" in html
    assert "renderOpportunity(normalizeOpportunityView(data), scanCount)" in html
    assert html.index("const nearMiss = unwrapOpportunity") < html.index(
        "const lastSignal = unwrapOpportunity"
    )
    assert "renderDiagnostics(first(data, ['diagnostics'], {}))" in html
    assert "gapValue === null || gapValue >= 0" in html
    assert "BBO не покрывает активационную покупку и будущий выход" in html
    assert "Выход вне рейтинга, мин" in html


def test_empty_state_acknowledges_completed_scans(html: str) -> None:
    assert "if (scans > 0)" in html
    assert "Нет подходящего сигнала после ${compact.format(scans)} сканирований" in html
    assert "Монитор работает: текущие маршруты не прошли фильтры" in html
    assert "Причины последнего отбора показаны ниже" in html


def test_api_contract_and_polling(html: str) -> None:
    assert "'/api/v1/arbitrage/status'" in html
    assert "'/api/v1/arbitrage/scan'" in html
    assert "'/api/v1/arbitrage/start'" in html
    assert "'/api/v1/arbitrage/stop'" in html
    assert "'/api/v1/arbitrage/reset'" in html
    assert "method: 'POST'" in html
    assert "const POLL_INTERVAL_MS = 2000" in html
    assert "window.setInterval" in html


def test_required_sections_are_present(html: str) -> None:
    for title in (
        "Состояние бирж",
        "Лучшая возможность",
        "Исполнимая цена",
        "Gross edge",
        "Net edge",
        "Ожидаемый P&amp;L",
        "Виртуальные балансы",
        "Волатильные ликвидные пары",
        "Волатильность 24ч",
        "Ликвидность",
        "Доступность",
        "Журнал PAPER-сделок",
        "Ошибки и предупреждения",
    ):
        assert title in html


def test_beginner_tooltips_are_accessible_on_panels_and_controls(html: str) -> None:
    assert html.count('class="info-button"') >= 20
    assert html.count('role="tooltip"') == html.count('class="info-button"')
    described = re.findall(
        r'class="info-button"[^>]*aria-describedby="([^"]+)"', html
    )
    tooltip_ids = set(re.findall(r'class="info-tooltip" id="([^"]+)"', html))
    assert described
    assert set(described) <= tooltip_ids
    assert ".info-tip:focus-within .info-tooltip" in html
    for control_id in (
        "notional",
        "minEdge",
        "riskBuffer",
        "intervalMs",
        "autoExecute",
        "activationObservations",
        "evidenceWindowMinutes",
        "inventoryIdleTimeoutMinutes",
        "maxActiveSymbols",
        "allocationPerSymbol",
        "min24hVolume",
        "bboDepthMultiplier",
        "initialBalance",
    ):
        assert f'for="{control_id}"' in html


def test_scanner_panel_is_compact_and_responsive(html: str) -> None:
    assert ".control-panel { width: min(1280px, 100%);" in html
    assert "grid-template-columns: repeat(5, minmax(145px, 1fr))" in html
    assert "@media (max-width: 1120px)" in html
    assert ".control-grid { grid-template-columns: repeat(3, 1fr); }" in html
    assert "@media (max-width: 440px)" in html
    assert ".control-grid { grid-template-columns: 1fr; }" in html


def test_user_facing_copy_uses_exchange_instead_of_venue(html: str) -> None:
    visible = re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.DOTALL)
    visible_text = re.sub(r"<[^>]+>", " ", visible)
    assert re.search(r"\bvenue(?:s)?\b", visible_text, flags=re.IGNORECASE) is None
    assert "Биржа" in visible_text or "биржа" in visible_text
    for key, name in (
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
        assert f"{key}: '{name}'" in html


def test_pnl_and_inventory_costs_are_explained_separately(html: str) -> None:
    for label, element_id in (
        ("Арбитражный realized P&amp;L", "arbitragePnl"),
        ("Инвентарь и перенос", "inventoryCarryPnl"),
        ("Общий PAPER P&amp;L", "totalPnl"),
    ):
        assert label in html
        assert f'id="{element_id}"' in html
    for contract_key in (
        "arbitrage_realized_pnl",
        "inventory_carry_pnl_usdt",
        "strategy_pnl_usdt",
        "inventory_journal",
        "rebalance_journal",
    ):
        assert contract_key in html
    assert "function renderInventoryJournal(entries)" in html
    assert "Расходы инвентаря и ребалансировки" in html
    assert "inventory_activation: 'Предварительная закупка'" in html
    assert "inventory_liquidation: 'Выход из инвентаря'" in html


def test_auto_universe_status_contract_is_rendered(html: str) -> None:
    for field in (
        "universe",
        "symbol_count",
        "scanned_symbol_count",
        "evaluated_symbol_count",
        "volatility_24h_pct",
        "liquidity_usdt",
        "venue_count",
        "opportunities",
    ):
        assert field in html
    assert 'id="symbolCount"' in html
    assert 'id="symbolCoverage"' in html
    assert 'id="universeBody"' in html
    assert "сканировано ${compact.format(scanned)} · оценено ${compact.format(evaluated)}" in html
    assert "entries.slice(0, 50)" in html


def test_auto_universe_is_collapsed_to_five_and_accessible(html: str) -> None:
    assert 'id="universeToggle"' in html
    assert 'aria-expanded="false"' in html
    assert 'aria-controls="universeTableWrap"' in html
    assert 'id="universeTableWrap"' in html
    assert "universeExpanded: false" in html
    assert "universe.slice(0, 5)" in html
    assert "state.universeExpanded = !state.universeExpanded" in html
    assert "renderUniverse(state.universe)" in html
    assert "Свернуть до 5" in html
    assert "Показать все" in html


def test_paper_journal_renders_each_venue_fee_and_total(html: str) -> None:
    assert "<th>Комиссии</th>" in html
    assert 'colspan="8" class="journal-empty"' in html
    for field in (
        "buy_fee_usdt",
        "sell_fee_usdt",
        "total_fee_usdt",
        "fee_usdt",
        "fee",
    ):
        assert field in html
    assert "const computedTotalFee" in html
    assert 'class="fee-leg"' in html
    assert 'class="fee-total"' in html
    assert "Итого" in html


def test_dynamic_html_is_escaped(html: str) -> None:
    assert "function escapeHTML(value)" in html
    assert "'&': '&amp;'" in html
    assert "'<': '&lt;'" in html
    assert "'>': '&gt;'" in html
    assert "escapeHTML(name)" in html
    assert "escapeHTML(message)" in html


def test_decimal_domain_model_is_mapped_to_ui(html: str) -> None:
    """Engine ratios and nested paper legs are supported without float JSON."""
    assert "finite(ratio) * 10000" in html
    for field in (
        "gross_edge",
        "net_edge",
        "net_profit",
        "buy_notional",
        "buy_leg",
        "sell_leg",
        "realized_pnl",
        "timestamp_ms",
    ):
        assert field in html
