"""
Тесты для OFI и Microprice analytics (Roadmap §9.1 Этап 6, пункт 2).
"""

import pytest
from contracts.schemas import BookCheckpoint, RawBookLevel
from contracts.ofi import OFISnapshot, MicropriceSnapshot
from packages.analytics.ofi import OFICalculator

pytestmark = pytest.mark.contract


def make_book(ts_ms: int, symbol: str, bids: list, asks: list) -> BookCheckpoint:
    """Helper для создания BookCheckpoint."""
    return BookCheckpoint(
        venue="BYBIT",
        category="linear",
        symbol=symbol,
        depth=200,
        connection_epoch="test",
        update_id=ts_ms,
        sequence=ts_ms,
        exchange_timestamp_ms=ts_ms,
        outer_timestamp_ms=ts_ms,
        receive_timestamp_ms=ts_ms,
        bids=[RawBookLevel(priceTicks=p, qtySteps=q) for p, q in bids],
        asks=[RawBookLevel(priceTicks=p, qtySteps=q) for p, q in asks],
        level_count=len(bids) + len(asks),
        coverage_boundary_ticks=0,
        coverage_bps="0.0000",
        is_feed_range_complete=True,
    )


class TestOFICalculator:
    def test_first_snapshot_returns_none(self):
        calc = OFICalculator(levels=5)
        book = make_book(1000, "BTCUSDT", [(64000, 100), (63990, 200)], [(64010, 150)])
        assert calc.process(book) is None

    def test_ofi_positive_on_bid_increase(self):
        """Bid вырос → положительный OFI."""
        calc = OFICalculator(levels=5)
        b1 = make_book(1000, "BTCUSDT", [(64000, 100)], [(64010, 100)])
        b2 = make_book(2000, "BTCUSDT", [(64000, 200)], [(64010, 100)])  # bid вырос
        calc.process(b1)
        ofi = calc.process(b2)
        assert ofi is not None
        assert ofi.ofi > 0
        assert ofi.bid_delta == 100

    def test_ofi_negative_on_ask_increase(self):
        """Ask вырос → отрицательный OFI."""
        calc = OFICalculator(levels=5)
        b1 = make_book(1000, "BTCUSDT", [(64000, 100)], [(64010, 100)])
        b2 = make_book(2000, "BTCUSDT", [(64000, 100)], [(64010, 300)])  # ask вырос
        calc.process(b1)
        ofi = calc.process(b2)
        assert ofi is not None
        assert ofi.ofi < 0

    def test_spread_calculated(self):
        calc = OFICalculator(levels=5)
        b1 = make_book(1000, "BTCUSDT", [(64000, 100)], [(64020, 100)])
        b2 = make_book(2000, "BTCUSDT", [(64000, 100)], [(64020, 100)])
        calc.process(b1)
        ofi = calc.process(b2)
        assert ofi.spread_ticks == 20

    def test_microprice_between_bid_ask(self):
        """Microprice должна быть между bid и ask."""
        calc = OFICalculator()
        book = make_book(1000, "BTCUSDT", [(64000, 100)], [(64020, 100)])
        micro = calc.microprice(book)
        assert micro is not None
        assert micro.best_bid_ticks < micro.microprice_ticks < micro.best_ask_ticks

    def test_microprice_equal_bid_qty_equal_ask_qty(self):
        """Равные объёмы → microprice = mid_price."""
        calc = OFICalculator()
        book = make_book(1000, "BTCUSDT", [(64000, 100)], [(64020, 100)])
        micro = calc.microprice(book)
        assert micro.microprice_ticks == micro.mid_price_ticks

    def test_microprice_shifts_toward_ask_when_bid_heavy(self):
        """Большой bid (покупательское давление) → microprice ближе к ask."""
        calc = OFICalculator()
        book = make_book(1000, "BTCUSDT", [(64000, 900)], [(64020, 100)])
        micro = calc.microprice(book)
        # Microprice = (100*64000 + 900*64020)/1000 = 64018 > mid=64010
        assert micro.microprice_ticks > micro.mid_price_ticks

    def test_imbalance_range(self):
        """Imbalance ∈ [0, 1]."""
        calc = OFICalculator()
        book = make_book(1000, "BTCUSDT", [(64000, 300)], [(64020, 100)])
        micro = calc.microprice(book)
        assert 0.0 <= micro.imbalance <= 1.0

    def test_ofi_history_accumulated(self):
        calc = OFICalculator(levels=5)
        books = [
            make_book(1000, "BTCUSDT", [(64000, 100)], [(64010, 100)]),
            make_book(2000, "BTCUSDT", [(64000, 150)], [(64010, 90)]),
            make_book(3000, "BTCUSDT", [(64000, 120)], [(64010, 110)]),
        ]
        for b in books:
            calc.process(b)

        assert len(calc.get_ofi()) == 2
