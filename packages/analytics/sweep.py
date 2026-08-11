"""
Sweep detector (Roadmap §9.1 Этап 5, пункт 7).

Детектирует серии агрессивных сделок в одном направлении через
несколько ценовых уровней за короткий промежуток времени.

Roadmap: Sweep event set не зависит от chunk/batch boundaries.
"""

from contracts.schemas import RawTrade, TakerSide
from contracts.sweep import SweepEvent


class SweepDetector:
    """Детектор sweep событий.

    Алгоритм:
    1. Отслеживаем цепочку сделок в одном направлении
    2. Если направление изменилось или время превысило window — chain закрывается
    3. Если chain охватил >= min_levels уровней → это sweep

    Roadmap: результат не зависит от chunk/batch boundaries —
    незакрытая chain переносится между вызовами process().

    Usage:
        detector = SweepDetector(min_levels=3, window_ms=500)
        for trade in trades:
            event = detector.process(trade)
            if event:
                print(f"Sweep: {event}")
        # Flush незакрытые chains
        for event in detector.flush():
            print(f"Sweep: {event}")
    """

    def __init__(
        self,
        min_levels: int = 3,
        window_ms: int = 500,
        min_qty_steps: int = 0,
    ):
        """
        Args:
            min_levels: минимальное количество ценовых уровней для sweep
            window_ms: максимальное время chain в мс
            min_qty_steps: минимальный суммарный объём chain
        """
        self.min_levels = min_levels
        self.window_ms = window_ms
        self.min_qty_steps = min_qty_steps

        # Текущая активная chain
        self._chain_symbol: str | None = None
        self._chain_direction: str | None = None
        self._chain_start_ms: int = 0
        self._chain_last_ms: int = 0
        self._chain_prices: set[int] = set()
        self._chain_qty: int = 0
        self._chain_count: int = 0
        self._chain_start_price: int = 0
        self._chain_last_price: int = 0

        self.events: list[SweepEvent] = []

    def process(self, trade: RawTrade) -> SweepEvent | None:
        """Обработать trade — вернуть SweepEvent если chain закрылась в sweep."""
        direction = "Buy" if trade.taker_side == TakerSide.BUY else "Sell"

        # Проверить, нужно ли закрыть текущую chain
        should_close = False
        if self._chain_direction is not None:
            time_expired = (trade.exchange_timestamp_ms - self._chain_last_ms) > self.window_ms
            direction_changed = direction != self._chain_direction
            if time_expired or direction_changed:
                should_close = True

        completed = None
        if should_close:
            completed = self._close_chain()

        # Добавить trade в chain (новую или продолжить)
        if self._chain_direction is None or should_close:
            # Начать новую chain
            self._chain_symbol = trade.symbol
            self._chain_direction = direction
            self._chain_start_ms = trade.exchange_timestamp_ms
            self._chain_prices = {trade.price_ticks}
            self._chain_qty = trade.qty_steps
            self._chain_count = 1
            self._chain_start_price = trade.price_ticks
            self._chain_last_price = trade.price_ticks
        else:
            # Продолжить текущую chain
            self._chain_prices.add(trade.price_ticks)
            self._chain_qty += trade.qty_steps
            self._chain_count += 1
            self._chain_last_price = trade.price_ticks

        self._chain_last_ms = trade.exchange_timestamp_ms

        return completed

    def _close_chain(self) -> SweepEvent | None:
        """Закрыть текущую chain — вернуть SweepEvent если это sweep."""
        if self._chain_direction is None:
            return None

        levels = len(self._chain_prices)
        qty = self._chain_qty

        result = None
        if levels >= self.min_levels and qty >= self.min_qty_steps:
            event = SweepEvent(
                symbol=self._chain_symbol,
                direction=self._chain_direction,
                start_timestamp_ms=self._chain_start_ms,
                end_timestamp_ms=self._chain_last_ms,
                start_price_ticks=self._chain_start_price,
                end_price_ticks=self._chain_last_price,
                levels_swept=levels,
                total_qty_steps=qty,
                trade_count=self._chain_count,
                price_move_ticks=abs(self._chain_last_price - self._chain_start_price),
                duration_ms=self._chain_last_ms - self._chain_start_ms,
            )
            self.events.append(event)
            result = event

        # Сброс chain
        self._chain_direction = None
        self._chain_prices = set()
        self._chain_qty = 0
        self._chain_count = 0

        return result

    def flush(self) -> list[SweepEvent]:
        """Закрыть незакрытую chain (вызывать в конце потока данных)."""
        event = self._close_chain()
        return [event] if event else []

    def get_events(
        self,
        start_ms: int | None = None,
        end_ms: int | None = None,
        direction: str | None = None,
        min_levels: int | None = None,
    ) -> list[SweepEvent]:
        """Получить sweep события с фильтрацией."""
        result = self.events
        if start_ms is not None:
            result = [e for e in result if e.start_timestamp_ms >= start_ms]
        if end_ms is not None:
            result = [e for e in result if e.end_timestamp_ms < end_ms]
        if direction is not None:
            result = [e for e in result if e.direction == direction]
        if min_levels is not None:
            result = [e for e in result if e.levels_swept >= min_levels]
        return result
