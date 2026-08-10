"""
Тесты GapDetector (Этап 1 / P1-B2).

Проверяют: обнаружение gaps, state transitions, serialization.
"""

import pytest

from packages.storage.gap_detector import GapDetector, Gap

pytestmark = pytest.mark.contract


class TestGapDetector:
    """Тесты GapDetector для RawTrade и BookCheckpoint."""

    def test_initial_state_bootstrap(self):
        """Начальное состояние = BOOTSTRAP."""
        detector = GapDetector()
        assert detector.state == "BOOTSTRAP"
        assert len(detector.gaps) == 0

    def test_first_trade_transitions_to_live_ready(self):
        """Первый trade → BOOTSTRAP → LIVE_READY."""
        detector = GapDetector()

        gap = detector.check_trade(trade_sequence=1, wal_offset=0)

        assert gap is None
        assert detector.state == "LIVE_READY"

    def test_continuous_sequence_no_gap(self):
        """Непрерывная последовательность → нет gaps."""
        detector = GapDetector()

        for seq in range(1, 11):
            gap = detector.check_trade(trade_sequence=seq, wal_offset=seq * 100)
            assert gap is None

        assert detector.state == "LIVE_READY"
        assert len(detector.gaps) == 0

    def test_detect_trade_gap(self):
        """Пропуск в sequence → gap обнаружен."""
        detector = GapDetector()

        detector.check_trade(trade_sequence=1, wal_offset=0)
        detector.check_trade(trade_sequence=2, wal_offset=100)

        # Пропуск: 3, 4 отсутствуют
        gap = detector.check_trade(trade_sequence=5, wal_offset=200)

        assert gap is not None
        assert gap.event_type == "RawTrade"
        assert gap.field_name == "sequence"
        assert gap.expected == 3
        assert gap.actual == 5
        assert gap.gap_size == 2
        assert gap.first_offset == 200

        assert detector.state == "GAP"
        assert len(detector.gaps) == 1

    def test_gap_recovery_after_threshold(self):
        """GAP → LIVE_READY после 100 событий без gaps."""
        detector = GapDetector()

        detector.check_trade(trade_sequence=1, wal_offset=0)
        detector.check_trade(trade_sequence=10, wal_offset=100)  # gap
        assert detector.state == "GAP"

        # 100 событий без gaps
        for seq in range(11, 111):
            detector.check_trade(trade_sequence=seq, wal_offset=seq * 100)

        assert detector.state == "LIVE_READY"

    def test_multiple_gaps_tracked(self):
        """Несколько gaps сохраняются в списке."""
        detector = GapDetector()

        detector.check_trade(trade_sequence=1, wal_offset=0)
        gap1 = detector.check_trade(trade_sequence=5, wal_offset=100)  # gap: expected=2, actual=5, gap_size=3
        assert gap1 is not None

        # Восстановление
        for seq in range(6, 106):
            detector.check_trade(trade_sequence=seq, wal_offset=seq * 100)

        assert detector.state == "LIVE_READY"

        # Второй gap
        gap2 = detector.check_trade(trade_sequence=110, wal_offset=11000)  # gap: expected=106, actual=110, gap_size=4
        assert gap2 is not None

        assert len(detector.gaps) == 2
        assert detector.gaps[0].gap_size == 3  # 5 - 2 = 3
        assert detector.gaps[1].gap_size == 4  # 110 - 106 = 4

    def test_out_of_order_not_gap(self):
        """Out-of-order события не создают gap (но логируются)."""
        detector = GapDetector()

        detector.check_trade(trade_sequence=1, wal_offset=0)
        detector.check_trade(trade_sequence=3, wal_offset=100)  # gap
        gap = detector.check_trade(trade_sequence=2, wal_offset=200)  # out-of-order

        # Out-of-order не создаёт новый gap
        assert gap is None
        assert len(detector.gaps) == 1  # только первый gap (1→3)

    def test_book_checkpoint_gap_detection(self):
        """Gap в BookCheckpoint.updateId обнаруживается."""
        detector = GapDetector()

        detector.check_book_checkpoint(update_id=100, wal_offset=0)
        detector.check_book_checkpoint(update_id=101, wal_offset=100)

        # Пропуск: 102-104 отсутствуют
        gap = detector.check_book_checkpoint(update_id=105, wal_offset=200)

        assert gap is not None
        assert gap.event_type == "BookCheckpoint"
        assert gap.field_name == "updateId"
        assert gap.expected == 102
        assert gap.actual == 105
        assert gap.gap_size == 3
        assert detector.state == "GAP"

    def test_independent_trade_and_book_tracking(self):
        """Trade и Book sequence отслеживаются независимо."""
        detector = GapDetector()

        # Trade sequence
        detector.check_trade(trade_sequence=1, wal_offset=0)
        trade_gap = detector.check_trade(trade_sequence=10, wal_offset=100)
        assert trade_gap is not None

        # Book updateId (независимый)
        detector.check_book_checkpoint(update_id=100, wal_offset=200)
        book_gap = detector.check_book_checkpoint(update_id=200, wal_offset=300)
        assert book_gap is not None

        assert len(detector.gaps) == 2
        assert detector.gaps[0].event_type == "RawTrade"
        assert detector.gaps[1].event_type == "BookCheckpoint"

    def test_reset_clears_state(self):
        """reset() очищает все состояние."""
        detector = GapDetector()

        detector.check_trade(trade_sequence=1, wal_offset=0)
        detector.check_trade(trade_sequence=10, wal_offset=100)  # gap

        assert detector.state == "GAP"
        assert len(detector.gaps) == 1

        detector.reset()

        assert detector.state == "BOOTSTRAP"
        assert len(detector.gaps) == 0

    def test_to_dict_serialization(self):
        """to_dict() сериализует состояние для manifest.json."""
        detector = GapDetector()

        detector.check_trade(trade_sequence=1, wal_offset=0)
        gap = detector.check_trade(trade_sequence=5, wal_offset=100)

        data = detector.to_dict()

        assert data["state"] == "GAP"
        assert data["last_trade_sequence"] == 5
        assert data["last_book_update_id"] is None
        assert len(data["gaps"]) == 1

        gap_data = data["gaps"][0]
        assert gap_data["event_type"] == "RawTrade"
        assert gap_data["field_name"] == "sequence"
        assert gap_data["expected"] == 2
        assert gap_data["actual"] == 5
        assert gap_data["gap_size"] == 3
        assert gap_data["first_offset"] == 100
        assert "detected_at_ms" in gap_data

    def test_gap_repr(self):
        """Gap.__repr__() возвращает читаемое представление."""
        gap = Gap(
            event_type="RawTrade",
            field_name="sequence",
            expected=10,
            actual=15,
            gap_size=5,
            first_offset=1000,
            detected_at_ms=1234567890,
        )

        repr_str = repr(gap)

        assert "RawTrade.sequence" in repr_str
        assert "expected=10" in repr_str
        assert "actual=15" in repr_str
        assert "gap_size=5" in repr_str
        assert "offset=1000" in repr_str
