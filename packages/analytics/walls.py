"""
Walls detector (Roadmap §9.1 Этап 6, пункт 5).

Roadmap: walls OUT_OF_VIEW/lifetime/continuity.
"""

from contracts.schemas import BookCheckpoint
from contracts.walls import Wall, WallStatus


class WallDetector:
    """Детектор крупных ордеров (walls) в стакане.

    Отслеживает появление, изменение и исчезновение walls.
    Поддерживает статусы: ACTIVE, OUT_OF_VIEW, CONSUMED, MOVED.

    Usage:
        detector = WallDetector(min_qty_steps=5000)
        for book in books:
            detector.process(book)
        active = detector.get_active_walls()
    """

    def __init__(self, min_qty_steps: int = 5000, max_depth: int = 50):
        self.min_qty_steps = min_qty_steps
        self.max_depth = max_depth
        # {(side, price_ticks): Wall}
        self._walls: dict[tuple[str, int], Wall] = {}
        self.history: list[Wall] = []

    def process(self, book: BookCheckpoint) -> list[Wall]:
        """Обновить walls из нового snapshot. Возвращает изменённые walls."""
        now = book.receive_timestamp_ms
        changed: list[Wall] = []

        # Текущие уровни в stакане
        curr_bids = {l.price_ticks: l.qty_steps for l in (book.bids or [])[:self.max_depth]}
        curr_asks = {l.price_ticks: l.qty_steps for l in (book.asks or [])[:self.max_depth]}

        # Обновить существующие walls
        for (side, price), wall in list(self._walls.items()):
            if wall.status != WallStatus.ACTIVE:
                continue
            curr = curr_bids if side == "Bid" else curr_asks
            if price in curr:
                qty = curr[price]
                wall.last_seen_ms = now
                wall.last_qty_steps = qty
                wall.update_count += 1
                if qty > wall.peak_qty_steps:
                    wall.peak_qty_steps = qty
                if qty < self.min_qty_steps:
                    wall.status = WallStatus.CONSUMED
                    self.history.append(wall)
                    changed.append(wall)
            else:
                # Уровень исчез из видимой глубины
                wall.last_seen_ms = now
                wall.status = WallStatus.OUT_OF_VIEW
                self.history.append(wall)
                changed.append(wall)

        # Найти новые walls
        for price, qty in curr_bids.items():
            if qty >= self.min_qty_steps and ("Bid", price) not in self._walls:
                wall = Wall(
                    symbol=book.symbol, side="Bid", price_ticks=price,
                    first_seen_ms=now, last_seen_ms=now,
                    peak_qty_steps=qty, last_qty_steps=qty,
                )
                self._walls[("Bid", price)] = wall
                changed.append(wall)

        for price, qty in curr_asks.items():
            if qty >= self.min_qty_steps and ("Ask", price) not in self._walls:
                wall = Wall(
                    symbol=book.symbol, side="Ask", price_ticks=price,
                    first_seen_ms=now, last_seen_ms=now,
                    peak_qty_steps=qty, last_qty_steps=qty,
                )
                self._walls[("Ask", price)] = wall
                changed.append(wall)

        # Очистить неактивные
        for key in [k for k, w in self._walls.items() if w.status != WallStatus.ACTIVE]:
            del self._walls[key]

        return changed

    def get_active_walls(self) -> list[Wall]:
        return [w for w in self._walls.values() if w.is_active]

    def get_history(self, side: str | None = None) -> list[Wall]:
        if side:
            return [w for w in self.history if w.side == side]
        return self.history
