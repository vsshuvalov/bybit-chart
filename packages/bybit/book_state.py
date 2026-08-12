"""
BookState machine для orderbook delta reconstruction (Roadmap §8.2).

Алгоритм:
1. Получить snapshot → инициализировать state (bids/asks dict)
2. Получить delta → apply changes:
   - qty > 0: add/update level
   - qty = 0: delete level
3. Sequence validation: delta.update_id == state.update_id + 1
4. Gap detection: seq jump → trigger resnapshot

Инварианты:
- State достоверен только внутри connection_epoch
- Delta применяется только если update_id строго последовательный
- При gap → state сбрасывается, нужен новый snapshot
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from contracts.schemas import BookCheckpoint, RawBookEvent, RawBookLevel


class BookStateStatus(str, Enum):
    """Статус BookState machine."""
    EMPTY = "empty"           # Нет snapshot, delta применять нельзя
    READY = "ready"           # Snapshot получен, принимаем delta
    GAP_DETECTED = "gap"      # Обнаружен gap, нужен resnapshot


@dataclass
class BookStateGap:
    """Gap в orderbook sequence.

    Attributes:
        expected_update_id: ожидаемый update_id
        received_update_id: полученный update_id
        symbol: символ
        connection_epoch: эпоха соединения
    """
    expected_update_id: int
    received_update_id: int
    symbol: str
    connection_epoch: str


class BookState:
    """Stateful orderbook reconstruction из snapshot + delta stream.

    Usage:
        state = BookState(symbol="BTCUSDT", depth=200)

        # Инициализация snapshot
        state.apply_snapshot(snapshot_event)

        # Применение delta
        for event in delta_stream:
            gap = state.apply_delta(event)
            if gap:
                # Запросить resnapshot
                request_resnapshot()
                continue

        # Текущее состояние
        bids = state.get_bids()   # отсортированы bid side (desc)
        asks = state.get_asks()   # отсортированы ask side (asc)
    """

    def __init__(self, symbol: str, depth: int):
        """Инициализировать BookState.

        Args:
            symbol: торговая пара
            depth: глубина orderbook (1|50|200|1000)
        """
        self.symbol = symbol
        self.depth = depth

        # Bid/Ask state: price_ticks → qty_steps
        self._bids: dict[int, int] = {}
        self._asks: dict[int, int] = {}

        # Sequence tracking
        self._update_id: int = 0
        self._connection_epoch: str = ""
        self._status: BookStateStatus = BookStateStatus.EMPTY
        self._snapshot_timestamp_ms: int = 0

        # Stats
        self.delta_count: int = 0
        self.gap_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def status(self) -> BookStateStatus:
        return self._status

    @property
    def update_id(self) -> int:
        return self._update_id

    @property
    def is_ready(self) -> bool:
        return self._status == BookStateStatus.READY

    def apply_snapshot(self, event: RawBookEvent) -> None:
        """Применить snapshot — полная замена state.

        Args:
            event: RawBookEvent с type="snapshot"

        Raises:
            ValueError: event.type != "snapshot"
        """
        if event.type != "snapshot":
            raise ValueError(
                f"apply_snapshot requires type='snapshot', got '{event.type}'"
            )

        # Полная замена state
        self._bids = {}
        self._asks = {}

        for level in event.bids:
            if level.qty_steps > 0:
                self._bids[level.price_ticks] = level.qty_steps

        for level in event.asks:
            if level.qty_steps > 0:
                self._asks[level.price_ticks] = level.qty_steps

        self._update_id = event.update_id
        self._connection_epoch = event.connection_epoch
        self._status = BookStateStatus.READY
        self._snapshot_timestamp_ms = event.exchange_timestamp_ms

    def apply_delta(self, event: RawBookEvent) -> BookStateGap | None:
        """Применить delta update.

        Args:
            event: RawBookEvent с type="delta"

        Returns:
            BookStateGap если обнаружен gap (нужен resnapshot), иначе None

        Note:
            При gap state переходит в GAP_DETECTED — delta не применяется.
            После gap необходимо вызвать apply_snapshot() для восстановления.
        """
        if event.type != "delta":
            raise ValueError(
                f"apply_delta requires type='delta', got '{event.type}'"
            )

        # State должен быть инициализирован snapshot
        if self._status == BookStateStatus.EMPTY:
            # Нет snapshot — пропускаем delta, ждём snapshot
            return None

        if self._status == BookStateStatus.GAP_DETECTED:
            # Уже в состоянии gap — ждём resnapshot
            return None

        # Epoch validation — данные достоверны только внутри эпохи
        if event.connection_epoch != self._connection_epoch:
            self._status = BookStateStatus.GAP_DETECTED
            self.gap_count += 1
            return BookStateGap(
                expected_update_id=self._update_id + 1,
                received_update_id=event.update_id,
                symbol=self.symbol,
                connection_epoch=event.connection_epoch,
            )

        # Sequence validation: delta.update_id должен быть строго next
        expected = self._update_id + 1
        if event.update_id != expected:
            self._status = BookStateStatus.GAP_DETECTED
            self.gap_count += 1
            return BookStateGap(
                expected_update_id=expected,
                received_update_id=event.update_id,
                symbol=self.symbol,
                connection_epoch=self._connection_epoch,
            )

        # Apply delta levels
        for level in event.bids:
            self._apply_level(self._bids, level)

        for level in event.asks:
            self._apply_level(self._asks, level)

        self._update_id = event.update_id
        self.delta_count += 1
        return None

    def get_bids(self) -> list[RawBookLevel]:
        """Получить bid levels, отсортированные по убыванию цены."""
        return [
            RawBookLevel(price_ticks=p, qty_steps=q)
            for p, q in sorted(self._bids.items(), reverse=True)
        ]

    def get_asks(self) -> list[RawBookLevel]:
        """Получить ask levels, отсортированные по возрастанию цены."""
        return [
            RawBookLevel(price_ticks=p, qty_steps=q)
            for p, q in sorted(self._asks.items())
        ]

    def best_bid(self) -> int | None:
        """Лучший bid (наивысшая цена)."""
        return max(self._bids.keys()) if self._bids else None

    def best_ask(self) -> int | None:
        """Лучший ask (наименьшая цена)."""
        return min(self._asks.keys()) if self._asks else None

    def mid_price_ticks(self) -> int | None:
        """Mid price (среднее между best bid и best ask)."""
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return (bid + ask) // 2

    def reset(self) -> None:
        """Сбросить state (например, при переподключении)."""
        self._bids.clear()
        self._asks.clear()
        self._update_id = 0
        self._connection_epoch = ""
        self._status = BookStateStatus.EMPTY
        self._snapshot_timestamp_ms = 0

    def level_count(self) -> tuple[int, int]:
        """Количество уровней (bid_count, ask_count)."""
        return len(self._bids), len(self._asks)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_level(side: dict[int, int], level: RawBookLevel) -> None:
        """Применить один level к стороне orderbook.

        qty = 0 → удалить уровень
        qty > 0 → добавить/обновить уровень
        """
        if level.qty_steps == 0:
            side.pop(level.price_ticks, None)
        else:
            side[level.price_ticks] = level.qty_steps
