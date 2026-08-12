"""
Tests для BookState machine (Roadmap §8.2 — orderbook delta reconstruction).

Проверяется:
- Snapshot инициализирует state
- Delta применяется: add/update/delete levels
- Sequence validation: gap detection при skip
- Epoch validation: gap при смене connectionEpoch
- Resnapshot после gap восстанавливает state
- best_bid/best_ask/mid_price
"""

import pytest

from contracts.schemas import RawBookEvent, RawBookLevel
from packages.bybit.book_state import BookState, BookStateStatus, BookStateGap

pytestmark = pytest.mark.contract


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def make_event(
    event_type: str,
    update_id: int,
    bids: list[tuple[int, int]] | None = None,
    asks: list[tuple[int, int]] | None = None,
    connection_epoch: str = "epoch-1",
    timestamp_ms: int = 1000,
) -> RawBookEvent:
    return RawBookEvent(
        venue="BYBIT",
        symbol="BTCUSDT",
        type=event_type,
        depth=200,
        bids=[RawBookLevel(price_ticks=p, qty_steps=q) for p, q in (bids or [])],
        asks=[RawBookLevel(price_ticks=p, qty_steps=q) for p, q in (asks or [])],
        exchange_timestamp_ms=timestamp_ms,
        local_timestamp_ms=timestamp_ms,
        connectionEpoch=connection_epoch,
        updateId=update_id,
        sequence=update_id,
        outerTimestampMs=timestamp_ms,
        receiveTimestampMs=timestamp_ms,
    )


# ------------------------------------------------------------------
# Snapshot
# ------------------------------------------------------------------

class TestBookStateSnapshot:

    def test_empty_state_after_init(self):
        state = BookState("BTCUSDT", depth=200)
        assert state.status == BookStateStatus.EMPTY
        assert not state.is_ready
        assert state.get_bids() == []
        assert state.get_asks() == []

    def test_snapshot_sets_ready(self):
        state = BookState("BTCUSDT", depth=200)
        snap = make_event("snapshot", update_id=100,
                          bids=[(500000, 1000)], asks=[(500010, 2000)])
        state.apply_snapshot(snap)
        assert state.status == BookStateStatus.READY
        assert state.is_ready
        assert state.update_id == 100

    def test_snapshot_loads_bids_and_asks(self):
        state = BookState("BTCUSDT", depth=200)
        snap = make_event("snapshot", update_id=100,
                          bids=[(500000, 1000), (499990, 500)],
                          asks=[(500010, 2000), (500020, 800)])
        state.apply_snapshot(snap)

        bids = state.get_bids()
        asks = state.get_asks()

        assert len(bids) == 2
        assert len(asks) == 2
        assert bids[0].price_ticks == 500000  # sorted desc
        assert bids[1].price_ticks == 499990
        assert asks[0].price_ticks == 500010  # sorted asc
        assert asks[1].price_ticks == 500020

    def test_snapshot_replaces_existing_state(self):
        state = BookState("BTCUSDT", depth=200)
        snap1 = make_event("snapshot", update_id=100,
                           bids=[(500000, 1000)], asks=[(500010, 2000)])
        snap2 = make_event("snapshot", update_id=200,
                           bids=[(499000, 3000)], asks=[])
        state.apply_snapshot(snap1)
        state.apply_snapshot(snap2)

        assert state.update_id == 200
        bids = state.get_bids()
        assert len(bids) == 1
        assert bids[0].price_ticks == 499000

    def test_snapshot_filters_zero_qty(self):
        state = BookState("BTCUSDT", depth=200)
        snap = make_event("snapshot", update_id=100,
                          bids=[(500000, 0), (499990, 500)], asks=[])
        state.apply_snapshot(snap)
        bids = state.get_bids()
        assert len(bids) == 1
        assert bids[0].price_ticks == 499990

    def test_apply_snapshot_raises_on_delta(self):
        state = BookState("BTCUSDT", depth=200)
        delta = make_event("delta", update_id=100, bids=[(500000, 1000)])
        with pytest.raises(ValueError, match="type='snapshot'"):
            state.apply_snapshot(delta)


# ------------------------------------------------------------------
# Delta apply
# ------------------------------------------------------------------

class TestBookStateDelta:

    def _init_state(self) -> BookState:
        state = BookState("BTCUSDT", depth=200)
        snap = make_event("snapshot", update_id=100,
                          bids=[(500000, 1000), (499990, 500)],
                          asks=[(500010, 2000), (500020, 800)])
        state.apply_snapshot(snap)
        return state

    def test_delta_adds_new_level(self):
        state = self._init_state()
        delta = make_event("delta", update_id=101,
                           bids=[(499980, 300)], asks=[])
        gap = state.apply_delta(delta)
        assert gap is None
        bid_prices = [b.price_ticks for b in state.get_bids()]
        assert 499980 in bid_prices
        assert state.delta_count == 1

    def test_delta_updates_existing_level(self):
        state = self._init_state()
        delta = make_event("delta", update_id=101,
                           bids=[(500000, 9999)], asks=[])
        state.apply_delta(delta)
        bids = state.get_bids()
        top_bid = next(b for b in bids if b.price_ticks == 500000)
        assert top_bid.qty_steps == 9999

    def test_delta_deletes_level_on_zero_qty(self):
        state = self._init_state()
        delta = make_event("delta", update_id=101,
                           bids=[(500000, 0)], asks=[])
        state.apply_delta(delta)
        bid_prices = [b.price_ticks for b in state.get_bids()]
        assert 500000 not in bid_prices
        assert 499990 in bid_prices

    def test_delta_updates_ask_side(self):
        state = self._init_state()
        delta = make_event("delta", update_id=101,
                           bids=[], asks=[(500010, 0), (500030, 700)])
        state.apply_delta(delta)
        ask_prices = [a.price_ticks for a in state.get_asks()]
        assert 500010 not in ask_prices   # удалён
        assert 500020 in ask_prices       # остался
        assert 500030 in ask_prices       # добавлен

    def test_delta_ignored_when_state_empty(self):
        state = BookState("BTCUSDT", depth=200)
        delta = make_event("delta", update_id=101, bids=[(500000, 1000)])
        gap = state.apply_delta(delta)
        assert gap is None  # не gap, просто игнорируем
        assert state.get_bids() == []

    def test_sequential_deltas(self):
        state = self._init_state()
        for i in range(1, 6):
            delta = make_event("delta", update_id=100 + i,
                               bids=[(500000 + i, 100 * i)])
            gap = state.apply_delta(delta)
            assert gap is None
        assert state.delta_count == 5
        assert state.update_id == 105


# ------------------------------------------------------------------
# Gap detection
# ------------------------------------------------------------------

class TestBookStateGapDetection:

    def _init_state(self, update_id: int = 100) -> BookState:
        state = BookState("BTCUSDT", depth=200)
        snap = make_event("snapshot", update_id=update_id,
                          bids=[(500000, 1000)], asks=[(500010, 2000)])
        state.apply_snapshot(snap)
        return state

    def test_gap_on_skipped_update_id(self):
        state = self._init_state(update_id=100)
        delta = make_event("delta", update_id=102)  # пропущен 101
        gap = state.apply_delta(delta)
        assert gap is not None
        assert isinstance(gap, BookStateGap)
        assert gap.expected_update_id == 101
        assert gap.received_update_id == 102
        assert state.status == BookStateStatus.GAP_DETECTED
        assert state.gap_count == 1

    def test_gap_on_epoch_change(self):
        state = self._init_state(update_id=100)
        delta = make_event("delta", update_id=101, connection_epoch="epoch-2")
        gap = state.apply_delta(delta)
        assert gap is not None
        assert state.status == BookStateStatus.GAP_DETECTED

    def test_delta_ignored_after_gap(self):
        state = self._init_state(update_id=100)
        state.apply_delta(make_event("delta", update_id=102))  # gap
        assert state.status == BookStateStatus.GAP_DETECTED

        # Следующая delta игнорируется
        result = state.apply_delta(make_event("delta", update_id=103))
        assert result is None  # не бросает, но и не применяет
        assert state.update_id == 100  # state не изменился

    def test_resnapshot_after_gap_restores_state(self):
        state = self._init_state(update_id=100)
        state.apply_delta(make_event("delta", update_id=102))  # gap
        assert state.status == BookStateStatus.GAP_DETECTED

        # Resnapshot восстанавливает state
        snap = make_event("snapshot", update_id=200,
                          bids=[(501000, 5000)], asks=[(501010, 3000)],
                          connection_epoch="epoch-2")
        state.apply_snapshot(snap)
        assert state.status == BookStateStatus.READY
        assert state.update_id == 200
        bids = state.get_bids()
        assert len(bids) == 1
        assert bids[0].price_ticks == 501000

    def test_correct_sequence_no_gap(self):
        state = self._init_state(update_id=100)
        for uid in [101, 102, 103]:
            gap = state.apply_delta(make_event("delta", update_id=uid))
            assert gap is None
        assert state.gap_count == 0


# ------------------------------------------------------------------
# Price helpers
# ------------------------------------------------------------------

class TestBookStatePriceHelpers:

    def test_best_bid_ask(self):
        state = BookState("BTCUSDT", depth=200)
        snap = make_event("snapshot", update_id=100,
                          bids=[(500000, 1000), (499990, 500)],
                          asks=[(500010, 2000), (500020, 800)])
        state.apply_snapshot(snap)
        assert state.best_bid() == 500000
        assert state.best_ask() == 500010

    def test_mid_price(self):
        state = BookState("BTCUSDT", depth=200)
        snap = make_event("snapshot", update_id=100,
                          bids=[(500000, 1000)], asks=[(500020, 2000)])
        state.apply_snapshot(snap)
        assert state.mid_price_ticks() == 500010  # (500000+500020)//2

    def test_best_bid_ask_none_when_empty(self):
        state = BookState("BTCUSDT", depth=200)
        assert state.best_bid() is None
        assert state.best_ask() is None
        assert state.mid_price_ticks() is None

    def test_level_count(self):
        state = BookState("BTCUSDT", depth=200)
        snap = make_event("snapshot", update_id=100,
                          bids=[(500000, 1000), (499990, 500)],
                          asks=[(500010, 2000)])
        state.apply_snapshot(snap)
        bid_count, ask_count = state.level_count()
        assert bid_count == 2
        assert ask_count == 1

    def test_reset_clears_state(self):
        state = BookState("BTCUSDT", depth=200)
        snap = make_event("snapshot", update_id=100,
                          bids=[(500000, 1000)], asks=[(500010, 2000)])
        state.apply_snapshot(snap)
        state.reset()
        assert state.status == BookStateStatus.EMPTY
        assert state.get_bids() == []
        assert state.get_asks() == []
        assert state.update_id == 0
