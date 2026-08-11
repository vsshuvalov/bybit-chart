"""
OFI и Microprice analytics (Roadmap §9.1 Этап 6, пункт 2).
"""

from contracts.schemas import BookCheckpoint, RawBookLevel
from contracts.ofi import OFISnapshot, MicropriceSnapshot


class OFICalculator:
    """Вычисляет OFI и Microprice из последовательных book snapshots.

    Usage:
        calc = OFICalculator(levels=5)
        for checkpoint in book_snapshots:
            ofi = calc.process(checkpoint)
            micro = calc.microprice(checkpoint)
    """

    def __init__(self, levels: int = 5):
        self.levels = levels
        self._prev: BookCheckpoint | None = None
        self.ofi_history: list[OFISnapshot] = []
        self.micro_history: list[MicropriceSnapshot] = []

    def process(self, book: BookCheckpoint) -> OFISnapshot | None:
        """Вычислить OFI между prev и current snapshot."""
        if self._prev is None:
            self._prev = book
            return None

        prev = self._prev
        curr = book

        # Взять топ-N уровней bid/ask
        prev_bids = {l.price_ticks: l.qty_steps for l in (prev.bids or [])[:self.levels]}
        curr_bids = {l.price_ticks: l.qty_steps for l in (curr.bids or [])[:self.levels]}
        prev_asks = {l.price_ticks: l.qty_steps for l in (prev.asks or [])[:self.levels]}
        curr_asks = {l.price_ticks: l.qty_steps for l in (curr.asks or [])[:self.levels]}

        # OFI = Σ(ΔBid) - Σ(ΔAsk)
        all_prices = set(prev_bids) | set(curr_bids) | set(prev_asks) | set(curr_asks)
        bid_delta = sum(curr_bids.get(p, 0) - prev_bids.get(p, 0) for p in all_prices if p in curr_bids or p in prev_bids)
        ask_delta = sum(curr_asks.get(p, 0) - prev_asks.get(p, 0) for p in all_prices if p in curr_asks or p in prev_asks)
        ofi = bid_delta - ask_delta

        # Best bid/ask
        best_bid = max(curr_bids.keys(), default=0) if curr_bids else 0
        best_ask = min(curr_asks.keys(), default=0) if curr_asks else 0

        if best_bid == 0 or best_ask == 0:
            self._prev = book
            return None

        snap = OFISnapshot(
            timestamp_ms=book.receive_timestamp_ms,
            symbol=book.symbol,
            ofi=ofi,
            bid_delta=bid_delta,
            ask_delta=ask_delta,
            best_bid_ticks=best_bid,
            best_ask_ticks=best_ask,
            spread_ticks=best_ask - best_bid,
            levels_used=min(len(curr_bids), len(curr_asks), self.levels),
        )
        self.ofi_history.append(snap)
        self._prev = book
        return snap

    def microprice(self, book: BookCheckpoint) -> MicropriceSnapshot | None:
        """Вычислить Microprice из текущего snapshot."""
        bids = book.bids or []
        asks = book.asks or []

        if not bids or not asks:
            return None

        best_bid = bids[0]
        best_ask = asks[0]

        total_qty = best_bid.qty_steps + best_ask.qty_steps
        if total_qty == 0:
            return None

        # Microprice = (ask_qty * bid_price + bid_qty * ask_price) / total_qty
        micro_raw = (
            best_ask.qty_steps * best_bid.price_ticks
            + best_bid.qty_steps * best_ask.price_ticks
        ) / total_qty

        mid = (best_bid.price_ticks + best_ask.price_ticks) // 2
        imbalance = best_bid.qty_steps / total_qty

        snap = MicropriceSnapshot(
            timestamp_ms=book.receive_timestamp_ms,
            symbol=book.symbol,
            microprice_ticks=round(micro_raw),
            mid_price_ticks=mid,
            best_bid_ticks=best_bid.price_ticks,
            best_ask_ticks=best_ask.price_ticks,
            best_bid_qty=best_bid.qty_steps,
            best_ask_qty=best_ask.qty_steps,
            imbalance=imbalance,
        )
        self.micro_history.append(snap)
        return snap

    def get_ofi(self, start_ms: int | None = None, end_ms: int | None = None) -> list[OFISnapshot]:
        result = self.ofi_history
        if start_ms: result = [x for x in result if x.timestamp_ms >= start_ms]
        if end_ms: result = [x for x in result if x.timestamp_ms < end_ms]
        return result

    def get_microprice(self, start_ms: int | None = None, end_ms: int | None = None) -> list[MicropriceSnapshot]:
        result = self.micro_history
        if start_ms: result = [x for x in result if x.timestamp_ms >= start_ms]
        if end_ms: result = [x for x in result if x.timestamp_ms < end_ms]
        return result
