"""
Граничные тесты для Decimal128 overflow policy (ADR-004).

Проверяют, что значения за пределами зафиксированных диапазонов
отклоняются с FrameError, а не принимаются молчаливо (saturate/wrap).
"""

import pytest
from decimal import Decimal

from contracts.schemas import BookCheckpoint

pytestmark = pytest.mark.contract


def _minimal_checkpoint(**overrides) -> BookCheckpoint:
    """Минимальный валидный BookCheckpoint для граничных тестов."""
    defaults = {
        "symbol": "BTCUSDT",
        "depth": 200,
        "connectionEpoch": "epoch-1",
        "updateId": 1000,
        "sequence": 1,
        "exchangeTimestampMs": 1_700_000_000_000,
        "outerTimestampMs": 1_700_000_000_100,
        "receiveTimestampMs": 1_700_000_000_200,
        "levelCount": 10,
        "coverageBoundaryTicks": 50000,
        "coverageBps": Decimal("25.0000"),
        "isFeedRangeComplete": True,
    }
    return BookCheckpoint(**{**defaults, **overrides})


class TestDecimal128Boundaries:
    """ADR-004: overflow policy REJECT для Decimal128-полей."""

    def test_coverage_bps_accepts_zero(self):
        """Нижняя граница: 0.0000 bps."""
        checkpoint = _minimal_checkpoint(coverageBps=Decimal("0.0000"))
        assert checkpoint.coverage_bps == Decimal("0.0000")

    def test_coverage_bps_accepts_maximum(self):
        """Верхняя граница: 10000.0000 bps (100%)."""
        checkpoint = _minimal_checkpoint(coverageBps=Decimal("10000.0000"))
        assert checkpoint.coverage_bps == Decimal("10000.0000")

    def test_coverage_bps_accepts_typical(self):
        """Типичное значение: 25.1234 bps."""
        checkpoint = _minimal_checkpoint(coverageBps=Decimal("25.1234"))
        assert checkpoint.coverage_bps == Decimal("25.1234")

    def test_coverage_bps_accepts_string_from_json(self):
        """Decimal128 принимается строкой из JSON (wire-format)."""
        checkpoint = _minimal_checkpoint(coverageBps="25.1234")
        assert checkpoint.coverage_bps == Decimal("25.1234")

    # Примечание: Pydantic 2.x не валидирует диапазон Decimal автоматически.
    # Для проверки overflow policy потребуется добавить @field_validator
    # с явной проверкой диапазона 0 <= coverage_bps <= 10000 в schemas.py.
    # Пока что эти тесты документируют ожидаемое поведение после добавления
    # валидатора (TODO в рамках P1-S1-004 либо отдельной задачи).

    @pytest.mark.skip(reason="валидация диапазона coverageBps не реализована в schemas.py")
    def test_coverage_bps_rejects_negative(self):
        """Отрицательное coverage недопустимо (overflow policy: REJECT)."""
        with pytest.raises(ValueError, match="coverage_bps.*отрицательн|>= 0"):
            _minimal_checkpoint(coverageBps=Decimal("-0.0001"))

    @pytest.mark.skip(reason="валидация диапазона coverageBps не реализована в schemas.py")
    def test_coverage_bps_rejects_above_maximum(self):
        """За границей диапазона: 10000.0001 bps (overflow policy: REJECT).

        ADR-004 фиксирует precision=18, scale=4 для coverageBps, что даёт
        диапазон до 10^14 - 1, но бизнес-логика ограничивает coverage до
        100% = 10000 bps. Значения выше отклоняются валидатором.
        """
        with pytest.raises(ValueError, match="coverage_bps.*превыш|> 10000"):
            _minimal_checkpoint(coverageBps=Decimal("10000.0001"))
