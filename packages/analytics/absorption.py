"""
Absorption detector (Roadmap §9.1 Этап 6, пункт 4).
"""

from contracts.schemas import BookCheckpoint, RawTrade, TakerSide
from contracts.absorption import AbsorptionEvent


class AbsorptionDetector:
    """Детектор поглощения агрессивного потока лимитными ордерами.

    Алгоритм:
    1. Накапливаем trades на одном ценовом уровне
    2. Сравниваем qty этого уровня в book до и после
    3. Если qty не уменьшился несмотря на trades → absorption

    Usage:
        detector = AbsorptionDetector(min_absorbed_qty=1000, window_ms=2000)
        for trade in trades:
            detector.on_trade(trade)
        for book in books:
            events = detector.on_book(book)
    """

    def __init__(
        self,
        min_absorbed_qty: int = 1000,
        window_ms: int = 2000,
        min_replenishment_ratio: float = 0.7,
    ):
        self.min_absorbed_qty = min_absorbed_qty
        self.window_ms = window_ms
        self.min_replenishment_ratio = min_replenishment_ratio

        # {price_ticks: (start_ms, absorbed_qty, trade_count, side)}
        self._pending: dict[int, tuple[int, int, int, str]] = {}
        self._prev_book: BookCheckpoint | None = None
        self.events: list[AbsorptionEvent] = []

    def on_trade(self, trade: RawTrade) -> None:
        """Зарегистрировать trade."""
        price = trade.price_ticks
        side = "Ask" if trade.taker_side == TakerSide.BUY else "Bid"
        now = trade.exchange_timestamp_ms

        if price in self._pending:
            start_ms, qty, count, prev_side = self._pending[price]
            # Проверить таймаут
            if now - start_ms > self.window_ms:
                self._pending[price] = (now, trade.qty_steps, 1, side)
            else:
                self._pending[price] = (start_ms, qty + trade.qty_steps, count + 1, side)
        else:
            self._pending[price] = (now, trade.qty_steps, 1, side)

    def on_book(self, book: BookCheckpoint) -> list[AbsorptionEvent]:
        """Проверить absorption при получении нового book snapshot."""
        if self._prev_book is None:
            self._prev_book = book
            return []

        events = []
        now = book.receive_timestamp_ms

        prev_bids = {l.price_ticks: l.qty_steps for l in (self._prev_book.bids or [])}
        prev_asks = {l.price_ticks: l.qty_steps for l in (self._prev_book.asks or [])}
        curr_bids = {l.price_ticks: l.qty_steps for l in (book.bids or [])}
        curr_asks = {l.price_ticks: l.qty_steps for l in (book.asks or [])}

        expired = [p for p, (start_ms, _, _, _) in self._pending.items()
                   if now - start_ms > self.window_ms]
        for p in expired:
            del self._pending[p]

        for price, (start_ms, absorbed_qty, count, absorber_side) in list(self._pending.items()):
            if absorbed_qty < self.min_absorbed_qty:
                continue

            if absorber_side == "Bid":
                qty_before = prev_bids.get(price, 0)
                qty_after = curr_bids.get(price, 0)
            else:
                qty_before = prev_asks.get(price, 0)
                qty_after = curr_asks.get(price, 0)

            if qty_before == 0:
                continue

            ratio = qty_after / qty_before if qty_before > 0 else 0.0
            if ratio >= self.min_replenishment_ratio:
                event = AbsorptionEvent(
                    timestamp_ms=start_ms,
                    symbol=book.symbol,
                    price_ticks=price,
                    side=absorber_side,
                    absorbed_qty_steps=absorbed_qty,
                    duration_ms=now - start_ms,
                    trade_count=count,
                    level_qty_before=qty_before,
                    level_qty_after=qty_after,
                )
                self.events.append(event)
                events.append(event)
                del self._pending[price]

        self._prev_book = book
        return events

    def get_events(self, start_ms: int | None = None, end_ms: int | None = None) -> list[AbsorptionEvent]:
        result = self.events
        if start_ms: result = [e for e in result if e.timestamp_ms >= start_ms]
        if end_ms:   result = [e for e in result if e.timestamp_ms < end_ms]
        return result
