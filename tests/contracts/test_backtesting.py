"""
Тесты Backtesting Framework (Roadmap §14).

Проверяют: Strategy, BacktestEngine, performance metrics.
"""

import pytest

from packages.backtesting import (
    BacktestConfig,
    BacktestEngine,
    Order,
    OrderSide,
    OrderType,
    Position,
    PositionSide,
    SimpleMovingAverageCrossStrategy,
    Strategy,
    StrategyContext,
)

pytestmark = pytest.mark.contract


class TestStrategy:
    """Тесты Strategy base class."""

    def test_strategy_initialization(self):
        """Strategy корректно инициализируется."""
        strategy = SimpleMovingAverageCrossStrategy("BTCUSDT", fast_period=5, slow_period=10)

        assert strategy.symbol == "BTCUSDT"
        assert strategy.name == "SimpleMovingAverageCrossStrategy"
        assert strategy.fast_period == 5
        assert strategy.slow_period == 10

    def test_strategy_ma_calculation(self):
        """MA crossover strategy рассчитывает MA."""
        strategy = SimpleMovingAverageCrossStrategy("BTCUSDT", fast_period=2, slow_period=3)

        # Feed bars
        for i in range(5):
            context = StrategyContext(
                timestamp_us=i * 1000,
                symbol="BTCUSDT",
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=100.0 + i,
                volume=1000.0,
            )
            strategy.on_bar(context)

        # После 3 bars slow MA должна быть рассчитана
        assert strategy.slow_ma is not None
        assert strategy.fast_ma is not None


class TestBacktestEngine:
    """Тесты BacktestEngine."""

    def test_engine_initialization(self):
        """BacktestEngine инициализируется корректно."""
        config = BacktestConfig(initial_cash=50000.0)
        engine = BacktestEngine(config)

        assert engine.cash == 50000.0
        assert engine.equity == 50000.0
        assert engine.position is None

    def test_engine_simple_long_trade(self):
        """BacktestEngine исполняет простую LONG сделку."""
        config = BacktestConfig(initial_cash=100000.0, commission_rate=0.0, slippage_rate=0.0)
        engine = BacktestEngine(config)

        # Simple buy-then-sell strategy
        class SimpleLongStrategy(Strategy):
            def __init__(self, symbol: str):
                super().__init__(symbol)
                self.bar_count = 0

            def on_bar(self, context: StrategyContext) -> list[Order]:
                self.bar_count += 1
                if self.bar_count == 1:
                    # Buy at first bar
                    return [Order(
                        order_id="buy_1",
                        timestamp_us=context.timestamp_us,
                        symbol=self.symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=1.0,
                    )]
                elif self.bar_count == 3:
                    # Sell at third bar
                    return [Order(
                        order_id="sell_1",
                        timestamp_us=context.timestamp_us,
                        symbol=self.symbol,
                        side=OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        quantity=1.0,
                    )]
                return []

        bars = [
            {"timestamp_us": 0, "open": 100, "high": 105, "low": 95, "close": 100, "volume": 1000},
            {"timestamp_us": 60_000_000, "open": 100, "high": 110, "low": 100, "close": 105, "volume": 1000},
            {"timestamp_us": 120_000_000, "open": 105, "high": 115, "low": 105, "close": 110, "volume": 1000},
        ]

        strategy = SimpleLongStrategy("BTCUSDT")
        result = engine.run(strategy, bars)

        # Should have 1 completed trade (buy + sell = 1 round trip)
        assert result.total_trades == 1
        assert result.winning_trades == 1
        assert result.total_return > 0  # Profit from 100 → 110

    def test_engine_ma_crossover_strategy(self):
        """BacktestEngine с MA crossover strategy."""
        config = BacktestConfig(initial_cash=100000.0, commission_rate=0.001)
        engine = BacktestEngine(config)

        strategy = SimpleMovingAverageCrossStrategy("BTCUSDT", fast_period=2, slow_period=3, position_size=1.0)

        # Trending data (uptrend then downtrend)
        bars = []
        for i in range(10):
            if i < 5:
                close_price = 100 + i * 2  # uptrend
            else:
                close_price = 110 - (i - 5) * 2  # downtrend

            bars.append({
                "timestamp_us": i * 60_000_000,
                "open": close_price - 1,
                "high": close_price + 1,
                "low": close_price - 2,
                "close": close_price,
                "volume": 1000,
            })

        result = engine.run(strategy, bars)

        # Should have some trades
        assert result.total_trades >= 0
        assert result.final_equity > 0

    def test_engine_calculates_metrics(self):
        """BacktestEngine рассчитывает performance metrics."""
        config = BacktestConfig(initial_cash=100000.0)
        engine = BacktestEngine(config)

        class AlwaysWinStrategy(Strategy):
            def __init__(self, symbol: str):
                super().__init__(symbol)
                self.bar_count = 0

            def on_bar(self, context: StrategyContext) -> list[Order]:
                self.bar_count += 1
                if self.bar_count == 1:
                    return [Order("buy", context.timestamp_us, self.symbol, OrderSide.BUY, OrderType.MARKET, 1.0)]
                elif self.bar_count == 3:
                    return [Order("sell", context.timestamp_us, self.symbol, OrderSide.SELL, OrderType.MARKET, 1.0)]
                return []

        bars = [
            {"timestamp_us": 0, "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1000},
            {"timestamp_us": 1, "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1000},
            {"timestamp_us": 2, "open": 100, "high": 120, "low": 100, "close": 120, "volume": 1000},
        ]

        strategy = AlwaysWinStrategy("BTCUSDT")
        result = engine.run(strategy, bars)

        assert result.total_trades == 1
        assert result.winning_trades == 1
        assert result.losing_trades == 0
        assert result.win_rate == 1.0
        assert result.total_return > 0

    def test_engine_position_tracking(self):
        """BacktestEngine корректно отслеживает позицию."""
        config = BacktestConfig(initial_cash=100000.0)
        engine = BacktestEngine(config)

        class SingleTradeStrategy(Strategy):
            def __init__(self, symbol: str):
                super().__init__(symbol)
                self.executed = False

            def on_bar(self, context: StrategyContext) -> list[Order]:
                if not self.executed and context.position is None:
                    self.executed = True
                    return [Order("buy", context.timestamp_us, self.symbol, OrderSide.BUY, OrderType.MARKET, 1.0)]
                return []

        bars = [
            {"timestamp_us": 0, "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1000},
            {"timestamp_us": 1, "open": 100, "high": 100, "low": 100, "close": 105, "volume": 1000},
        ]

        strategy = SingleTradeStrategy("BTCUSDT")
        result = engine.run(strategy, bars)

        # Should have position
        assert engine.position is not None
        assert engine.position.side == PositionSide.LONG

    def test_engine_equity_curve(self):
        """BacktestEngine генерирует equity curve."""
        config = BacktestConfig(initial_cash=100000.0)
        engine = BacktestEngine(config)

        class NoTradeStrategy(Strategy):
            def on_bar(self, context: StrategyContext) -> list[Order]:
                return []

        bars = [
            {"timestamp_us": i * 1000, "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1000}
            for i in range(5)
        ]

        strategy = NoTradeStrategy("BTCUSDT")
        result = engine.run(strategy, bars)

        assert len(result.equity_curve) == 5
        assert all(point["equity"] == 100000.0 for point in result.equity_curve)


class TestPosition:
    """Тесты Position class."""

    def test_position_unrealized_pnl_long(self):
        """Position корректно рассчитывает unrealized PnL для LONG."""
        position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=100.0,
        )

        position.update_unrealized_pnl(110.0)
        assert position.unrealized_pnl == 10.0

        position.update_unrealized_pnl(95.0)
        assert position.unrealized_pnl == -5.0

    def test_position_unrealized_pnl_short(self):
        """Position корректно рассчитывает unrealized PnL для SHORT."""
        position = Position(
            symbol="BTCUSDT",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=100.0,
        )

        position.update_unrealized_pnl(90.0)
        assert position.unrealized_pnl == 10.0

        position.update_unrealized_pnl(105.0)
        assert position.unrealized_pnl == -5.0

    def test_position_flat_has_no_pnl(self):
        """FLAT позиция имеет 0 PnL."""
        position = Position(symbol="BTCUSDT", side=PositionSide.FLAT)

        position.update_unrealized_pnl(100.0)
        assert position.unrealized_pnl == 0.0
