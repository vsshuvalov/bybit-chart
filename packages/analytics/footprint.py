"""
Footprint analytics module (Roadmap §9.1 Этап 5).

Агрегирует bid/ask volume по ценовым уровням для footprint chart.
"""

from collections import defaultdict
from decimal import Decimal
from typing import Iterator

from contracts.footprint import FootprintBar, FootprintLevel
from contracts.schemas import RawTrade, TakerSide


class FootprintAggregator:
    """Агрегатор для footprint analytics.

    Accumulates bid/ask volume per price level в заданном интервале.

    Usage:
        aggregator = FootprintAggregator(
            venue="BYBIT",
            symbol="BTCUSDT",
            interval_seconds=60,
            tick_size=Decimal("0.1"),
            step_size=Decimal("0.001"),
        )

        for trade in trades:
            aggregator.add_trade(trade)

        footprint = aggregator.build()
    """

    def __init__(
        self,
        venue: str,
        symbol: str,
        interval_seconds: int,
        tick_size: Decimal,
        step_size: Decimal,
        interval_start_ms: int | None = None,
    ):
        """Инициализировать footprint aggregator.

        Args:
            venue: биржа (например, "BYBIT")
            symbol: торговая пара (например, "BTCUSDT")
            interval_seconds: длительность интервала (секунды)
            tick_size: размер тика цены (например, 0.1 для BTCUSDT)
            step_size: размер шага объёма (например, 0.001)
            interval_start_ms: начало интервала (Unix ms), если None — берётся из первого trade
        """
        self.venue = venue
        self.symbol = symbol
        self.interval_seconds = interval_seconds
        self.tick_size = tick_size
        self.step_size = step_size
        self.interval_start_ms = interval_start_ms

        # Установить interval_end_ms если start известен
        if interval_start_ms is not None:
            self.interval_end_ms = interval_start_ms + (interval_seconds * 1000)
        else:
            self.interval_end_ms = None

        # Агрегация по ценовым уровням: {price_str: (bid_volume, ask_volume, trade_count)}
        self.levels: dict[str, tuple[Decimal, Decimal, int]] = defaultdict(
            lambda: (Decimal(0), Decimal(0), 0)
        )

    def add_trade(self, trade: RawTrade) -> None:
        """Добавить trade в агрегацию.

        Args:
            trade: RawTrade событие
        """
        # Установить interval_start_ms из первого trade
        if self.interval_start_ms is None:
            self.interval_start_ms = trade.exchange_timestamp_ms
            self.interval_end_ms = self.interval_start_ms + (
                self.interval_seconds * 1000
            )

        # Проверить, что trade в текущем интервале
        if trade.exchange_timestamp_ms > self.interval_end_ms:
            # Trade вне интервала — игнорируем (caller должен создать новый aggregator)
            return

        # Конвертировать ticks → Decimal
        price = Decimal(trade.price_ticks) * self.tick_size
        qty = Decimal(trade.qty_steps) * self.step_size

        # Агрегировать volume по цене
        price_str = str(price)
        bid_vol, ask_vol, count = self.levels[price_str]

        if trade.taker_side == TakerSide.BUY:
            # Агрессивная покупка (taker Buy)
            bid_vol += qty
        else:
            # Агрессивная продажа (taker Sell)
            ask_vol += qty

        self.levels[price_str] = (bid_vol, ask_vol, count + 1)

    def build(self) -> FootprintBar:
        """Построить FootprintBar из агрегированных данных.

        Returns:
            FootprintBar contract

        Raises:
            ValueError: если нет данных для построения
        """
        if self.interval_start_ms is None:
            raise ValueError("Нет данных для построения FootprintBar")

        if self.interval_end_ms is None:
            self.interval_end_ms = self.interval_start_ms + (
                self.interval_seconds * 1000
            )

        # Построить FootprintLevel для каждого уровня
        footprint_levels: dict[str, FootprintLevel] = {}
        total_bid_volume = Decimal(0)
        total_ask_volume = Decimal(0)

        for price_str, (bid_vol, ask_vol, count) in self.levels.items():
            price = Decimal(price_str)
            total_volume = bid_vol + ask_vol

            # Imbalance: (bid - ask) / total
            if total_volume > 0:
                imbalance = (bid_vol - ask_vol) / total_volume
            else:
                imbalance = Decimal(0)

            footprint_levels[price_str] = FootprintLevel(
                price=price,
                bid_volume=bid_vol,
                ask_volume=ask_vol,
                total_volume=total_volume,
                imbalance=imbalance,
                trade_count=count,
            )

            total_bid_volume += bid_vol
            total_ask_volume += ask_vol

        # Найти POC (Point of Control) — уровень с максимальным объёмом
        poc_price: Decimal | None = None
        max_volume = Decimal(0)

        for level in footprint_levels.values():
            if level.total_volume > max_volume:
                max_volume = level.total_volume
                poc_price = level.price

        # Общий imbalance
        total_volume = total_bid_volume + total_ask_volume
        if total_volume > 0:
            overall_imbalance = (total_bid_volume - total_ask_volume) / total_volume
        else:
            overall_imbalance = Decimal(0)

        return FootprintBar(
            venue=self.venue,
            symbol=self.symbol,
            interval_start_ms=self.interval_start_ms,
            interval_end_ms=self.interval_end_ms,
            interval_seconds=self.interval_seconds,
            levels=footprint_levels,
            poc_price=poc_price,
            total_bid_volume=total_bid_volume,
            total_ask_volume=total_ask_volume,
            total_volume=total_volume,
            overall_imbalance=overall_imbalance,
            level_count=len(footprint_levels),
        )


def compute_footprint_bars(
    trades: Iterator[RawTrade],
    venue: str,
    symbol: str,
    interval_seconds: int,
    tick_size: Decimal,
    step_size: Decimal,
) -> Iterator[FootprintBar]:
    """Вычислить footprint bars из потока trades.

    Args:
        trades: итератор RawTrade
        venue: биржа
        symbol: торговая пара
        interval_seconds: длительность интервала (секунды)
        tick_size: размер тика цены
        step_size: размер шага объёма

    Yields:
        FootprintBar для каждого интервала
    """
    aggregator: FootprintAggregator | None = None

    for trade in trades:
        # Создать новый aggregator для первого trade
        if aggregator is None:
            aggregator = FootprintAggregator(
                venue=venue,
                symbol=symbol,
                interval_seconds=interval_seconds,
                tick_size=tick_size,
                step_size=step_size,
                interval_start_ms=trade.exchange_timestamp_ms,
            )

        # Проверить, нужен ли новый интервал
        if (
            aggregator.interval_end_ms is not None
            and trade.exchange_timestamp_ms > aggregator.interval_end_ms
        ):
            # Закрыть текущий интервал
            yield aggregator.build()

            # Создать новый aggregator для следующего интервала
            aggregator = FootprintAggregator(
                venue=venue,
                symbol=symbol,
                interval_seconds=interval_seconds,
                tick_size=tick_size,
                step_size=step_size,
                interval_start_ms=trade.exchange_timestamp_ms,
            )

        # Добавить trade в текущий aggregator
        aggregator.add_trade(trade)

    # Закрыть последний интервал
    if aggregator is not None and aggregator.levels:
        yield aggregator.build()
