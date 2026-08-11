"""
Pulling/Stacking detector (Roadmap §9.1 Этап 6, пункт 6).

Pulling — быстрое исчезновение крупного ордера до его исполнения (манипуляция).
Stacking — накопление нескольких ордеров на одном уровне с разных аккаунтов.
"""

from contracts.schemas import BookCheckpoint
from contracts.walls import Wall


class PullingStackingDetector:
    """Детектор pulling и stacking паттернов.

    Pulling: wall исчез менее чем за min_pull_ms без исполнения.
    Stacking: на одном уровне qty резко вырос (новые ордера добавились).
    """

    def __init__(
        self,
        min_wall_qty: int = 5000,
        min_pull_ms: int = 3000,    # wall исчез быстрее этого → pulling
        stack_ratio: float = 1.5,   # qty вырос в N раз → stacking
    ):
        self.min_wall_qty = min_wall_qty
        self.min_pull_ms = min_pull_ms
        self.stack_ratio = stack_ratio

        # {(side, price): (first_seen_ms, qty)}
        self._tracked: dict[tuple[str, int], tuple[int, int]] = {}

        self.pulls: list[dict] = []
        self.stacks: list[dict] = []

    def process(self, book: BookCheckpoint) -> dict:
        """Обновить детектор из нового snapshot."""
        now = book.receive_timestamp_ms
        curr_bids = {l.price_ticks: l.qty_steps for l in (book.bids or [])}
        curr_asks = {l.price_ticks: l.qty_steps for l in (book.asks or [])}

        new_pulls = []
        new_stacks = []

        for (side, price), (first_ms, prev_qty) in list(self._tracked.items()):
            curr = curr_bids if side == "Bid" else curr_asks
            curr_qty = curr.get(price, 0)

            if curr_qty < self.min_wall_qty:
                # Уровень исчез или упал
                lifetime = now - first_ms
                if prev_qty >= self.min_wall_qty and lifetime < self.min_pull_ms:
                    # Быстрое исчезновение без trades → pulling
                    event = {
                        "type": "pull", "symbol": book.symbol,
                        "side": side, "price_ticks": price,
                        "qty_steps": prev_qty, "lifetime_ms": lifetime,
                        "timestamp_ms": now,
                    }
                    self.pulls.append(event)
                    new_pulls.append(event)
                del self._tracked[(side, price)]
            elif curr_qty >= prev_qty * self.stack_ratio:
                # Qty резко вырос → stacking
                event = {
                    "type": "stack", "symbol": book.symbol,
                    "side": side, "price_ticks": price,
                    "prev_qty": prev_qty, "curr_qty": curr_qty,
                    "ratio": curr_qty / prev_qty,
                    "timestamp_ms": now,
                }
                self.stacks.append(event)
                new_stacks.append(event)
                self._tracked[(side, price)] = (first_ms, curr_qty)
            else:
                self._tracked[(side, price)] = (first_ms, curr_qty)

        # Добавить новые крупные уровни в отслеживание
        for price, qty in curr_bids.items():
            if qty >= self.min_wall_qty and ("Bid", price) not in self._tracked:
                self._tracked[("Bid", price)] = (now, qty)
        for price, qty in curr_asks.items():
            if qty >= self.min_wall_qty and ("Ask", price) not in self._tracked:
                self._tracked[("Ask", price)] = (now, qty)

        return {"pulls": new_pulls, "stacks": new_stacks}
