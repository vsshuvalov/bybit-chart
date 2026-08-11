"""
Liquidation cascades detector (Roadmap §9.1 Этап 6, пункт 7).
"""

from contracts.schemas import RawTrade, TakerSide


class LiquidationCascadeDetector:
    """Детектор каскадных ликвидаций.

    Ликвидация = крупная сделка в направлении движения цены,
    которая порождает следующие ликвидации.

    Cascade = серия ликвидаций в одном направлении за короткое время.
    """

    def __init__(
        self,
        min_trade_qty: int = 5000,
        window_ms: int = 3000,
        min_cascade_count: int = 3,
    ):
        self.min_trade_qty = min_trade_qty
        self.window_ms = window_ms
        self.min_cascade_count = min_cascade_count

        self._chain: list[dict] = []
        self._chain_direction: str | None = None
        self.cascades: list[dict] = []

    def process(self, trade: RawTrade) -> dict | None:
        """Обработать trade — вернуть cascade если серия завершена."""
        if trade.qty_steps < self.min_trade_qty:
            return None

        direction = "Buy" if trade.taker_side == TakerSide.BUY else "Sell"
        now = trade.exchange_timestamp_ms

        # Проверить таймаут или смену направления
        if self._chain:
            last_ts = self._chain[-1]["ts"]
            if (now - last_ts > self.window_ms) or (direction != self._chain_direction):
                completed = self._close_cascade()
                self._chain = []
                self._chain_direction = None
                if completed:
                    return completed

        self._chain.append({"ts": now, "qty": trade.qty_steps, "price": trade.price_ticks})
        self._chain_direction = direction
        return None

    def _close_cascade(self) -> dict | None:
        if len(self._chain) < self.min_cascade_count:
            return None
        total_qty = sum(x["qty"] for x in self._chain)
        event = {
            "type": "cascade",
            "direction": self._chain_direction,
            "start_ms": self._chain[0]["ts"],
            "end_ms": self._chain[-1]["ts"],
            "trade_count": len(self._chain),
            "total_qty_steps": total_qty,
            "start_price": self._chain[0]["price"],
            "end_price": self._chain[-1]["price"],
        }
        self.cascades.append(event)
        return event

    def flush(self) -> dict | None:
        result = self._close_cascade()
        self._chain = []
        self._chain_direction = None
        return result
