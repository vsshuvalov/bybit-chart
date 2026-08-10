"""
Backtest Engine для strategy execution (Roadmap §14).

Источник: Roadmap §14 (backtesting engine, walk-forward)

Архитектура:
- BacktestEngine — orchestrates strategy execution
- Walk-forward через исторические данные (OHLC bars)
- Order execution simulation (market orders at close)
- Position tracking and PnL calculation
- Trade journal для всех сделок

MVP: Simple execution at bar close
Future: Advanced execution models (slippage, market impact)
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from packages.backtesting.strategy import (
    Order,
    OrderSide,
    Position,
    PositionSide,
    Strategy,
    StrategyContext,
    Trade,
)

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Конфигурация backtesting.

    Roadmap §14: параметры для backtesting simulation.
    """
    initial_cash: float = 100000.0
    commission_rate: float = 0.0006  # 0.06% (Bybit maker fee)
    slippage_rate: float = 0.0001  # 0.01% slippage
    position_size_type: str = "fixed"  # "fixed" | "percent"
    max_position_size: float = 1.0  # для fixed: в единицах, для percent: 0.0-1.0


@dataclass
class BacktestResult:
    """Результаты backtesting.

    Roadmap §14: performance metrics для strategy evaluation.
    """
    # Summary
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    # Returns
    total_return: float = 0.0
    total_return_pct: float = 0.0

    # Risk metrics
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0

    # Trade statistics
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0

    # Account
    final_equity: float = 0.0
    final_cash: float = 0.0

    # History
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "summary": {
                "total_trades": self.total_trades,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
                "win_rate": self.win_rate,
            },
            "returns": {
                "total_return": self.total_return,
                "total_return_pct": self.total_return_pct,
            },
            "risk": {
                "max_drawdown": self.max_drawdown,
                "max_drawdown_pct": self.max_drawdown_pct,
                "sharpe_ratio": self.sharpe_ratio,
            },
            "statistics": {
                "avg_win": self.avg_win,
                "avg_loss": self.avg_loss,
                "profit_factor": self.profit_factor,
            },
            "final": {
                "equity": self.final_equity,
                "cash": self.final_cash,
            },
        }


class BacktestEngine:
    """Backtesting engine для strategy evaluation.

    Roadmap §14: walk-forward execution через исторические данные.
    """

    def __init__(self, config: BacktestConfig | None = None):
        """Initialize backtest engine.

        Args:
            config: конфигурация backtesting (default: BacktestConfig())
        """
        self.config = config or BacktestConfig()

        # Account state
        self.cash = self.config.initial_cash
        self.equity = self.config.initial_cash

        # Position tracking
        self.position: Position | None = None

        # Trade history
        self.trades: list[Trade] = []
        self.equity_curve: list[dict[str, Any]] = []

        # Counters
        self.trade_id_counter = 0

    def run(
        self,
        strategy: Strategy,
        bars: list[dict[str, Any]],
        analytics: dict[int, dict[str, Any]] | None = None,
    ) -> BacktestResult:
        """Запустить backtesting стратегии.

        Args:
            strategy: Strategy instance
            bars: список OHLC bars (с timestamp_us, open, high, low, close, volume)
            analytics: optional analytics data (timestamp_us → analytics dict)

        Returns:
            BacktestResult с performance metrics

        Roadmap §14: walk-forward через bars, execute strategy на каждом bar.
        """
        logger.info(f"Starting backtest: strategy={strategy.name}, bars={len(bars)}")

        strategy.on_start()

        for bar in bars:
            timestamp_us = bar["timestamp_us"]

            # Prepare context
            analytics_data = analytics.get(timestamp_us, {}) if analytics else {}

            context = StrategyContext(
                timestamp_us=timestamp_us,
                symbol=strategy.symbol,
                open=bar["open"],
                high=bar["high"],
                low=bar["low"],
                close=bar["close"],
                volume=bar["volume"],
                delta=analytics_data.get("delta"),
                cvd=analytics_data.get("cvd"),
                vwap=analytics_data.get("vwap"),
                position=self.position,
                cash=self.cash,
                equity=self.equity,
            )

            # Strategy generates orders
            orders = strategy.on_bar(context)

            # Execute orders
            for order in orders:
                self._execute_order(order, bar["close"])

            # Update unrealized PnL
            if self.position and self.position.side != PositionSide.FLAT:
                self.position.update_unrealized_pnl(bar["close"])
                self.equity = self.cash + self.position.unrealized_pnl
            else:
                self.equity = self.cash

            # Record equity curve
            self.equity_curve.append({
                "timestamp_us": timestamp_us,
                "equity": self.equity,
                "cash": self.cash,
                "unrealized_pnl": self.position.unrealized_pnl if self.position else 0.0,
            })

        strategy.on_finish()

        # Calculate performance metrics
        result = self._calculate_metrics()

        logger.info(
            f"Backtest complete: trades={result.total_trades}, "
            f"return={result.total_return_pct:.2f}%, sharpe={result.sharpe_ratio:.2f}"
        )

        return result

    def _execute_order(self, order: Order, execution_price: float):
        """Исполнить ордер (simulation).

        Args:
            order: Order для исполнения
            execution_price: цена исполнения (close price)
        """
        # Apply slippage
        if order.side == OrderSide.BUY:
            execution_price *= (1 + self.config.slippage_rate)
        else:
            execution_price *= (1 - self.config.slippage_rate)

        # Calculate commission
        trade_value = order.quantity * execution_price
        commission = trade_value * self.config.commission_rate

        # Execute trade
        self.trade_id_counter += 1
        trade = Trade(
            trade_id=f"trade_{self.trade_id_counter}",
            order_id=order.order_id,
            timestamp_us=order.timestamp_us,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=execution_price,
            commission=commission,
        )

        self.trades.append(trade)

        # Update position
        if order.side == OrderSide.BUY:
            self._execute_buy(trade)
        else:
            self._execute_sell(trade)

    def _execute_buy(self, trade: Trade):
        """Исполнить BUY trade."""
        if self.position is None or self.position.side == PositionSide.FLAT:
            # Open LONG
            cost = trade.value + trade.commission
            if self.cash >= cost:
                self.cash -= cost
                self.position = Position(
                    symbol=trade.symbol,
                    side=PositionSide.LONG,
                    quantity=trade.quantity,
                    entry_price=trade.price,
                    entry_timestamp_us=trade.timestamp_us,
                )
            else:
                logger.warning(f"Insufficient cash for BUY: required={cost}, available={self.cash}")

        elif self.position.side == PositionSide.SHORT:
            # Close SHORT
            realized_pnl = (self.position.entry_price - trade.price) * self.position.quantity - trade.commission
            self.cash += self.position.entry_price * self.position.quantity  # return initial proceeds
            self.cash -= trade.value + trade.commission  # pay for closing
            self.position = Position(symbol=trade.symbol, side=PositionSide.FLAT)

    def _execute_sell(self, trade: Trade):
        """Исполнить SELL trade."""
        if self.position is None or self.position.side == PositionSide.FLAT:
            # Open SHORT
            proceeds = trade.value - trade.commission
            self.cash += proceeds
            self.position = Position(
                symbol=trade.symbol,
                side=PositionSide.SHORT,
                quantity=trade.quantity,
                entry_price=trade.price,
                entry_timestamp_us=trade.timestamp_us,
            )

        elif self.position.side == PositionSide.LONG:
            # Close LONG
            proceeds = trade.value - trade.commission
            self.cash += proceeds
            self.position = Position(symbol=trade.symbol, side=PositionSide.FLAT)

    def _calculate_metrics(self) -> BacktestResult:
        """Рассчитать performance metrics."""
        result = BacktestResult(
            trades=self.trades,
            equity_curve=self.equity_curve,
            final_equity=self.equity,
            final_cash=self.cash,
        )

        if not self.trades:
            return result

        # Calculate trade pairs (entry + exit)
        winning_pnls = []
        losing_pnls = []

        for i in range(0, len(self.trades) - 1, 2):
            if i + 1 >= len(self.trades):
                break

            entry = self.trades[i]
            exit_trade = self.trades[i + 1]

            if entry.side == OrderSide.BUY:
                pnl = (exit_trade.price - entry.price) * entry.quantity - entry.commission - exit_trade.commission
            else:
                pnl = (entry.price - exit_trade.price) * entry.quantity - entry.commission - exit_trade.commission

            if pnl > 0:
                winning_pnls.append(pnl)
            else:
                losing_pnls.append(pnl)

        result.total_trades = len(winning_pnls) + len(losing_pnls)
        result.winning_trades = len(winning_pnls)
        result.losing_trades = len(losing_pnls)

        # Returns
        result.total_return = self.equity - self.config.initial_cash
        result.total_return_pct = (result.total_return / self.config.initial_cash) * 100

        # Win rate
        if result.total_trades > 0:
            result.win_rate = result.winning_trades / result.total_trades

        # Avg win/loss
        if winning_pnls:
            result.avg_win = sum(winning_pnls) / len(winning_pnls)
        if losing_pnls:
            result.avg_loss = sum(losing_pnls) / len(losing_pnls)

        # Profit factor
        total_wins = sum(winning_pnls) if winning_pnls else 0
        total_losses = abs(sum(losing_pnls)) if losing_pnls else 0
        if total_losses > 0:
            result.profit_factor = total_wins / total_losses

        # Max drawdown
        peak = self.config.initial_cash
        for point in self.equity_curve:
            equity = point["equity"]
            if equity > peak:
                peak = equity
            drawdown = peak - equity
            if drawdown > result.max_drawdown:
                result.max_drawdown = drawdown
                result.max_drawdown_pct = (drawdown / peak) * 100

        # Sharpe ratio (simplified)
        if len(self.equity_curve) > 1:
            returns = []
            for i in range(1, len(self.equity_curve)):
                ret = (self.equity_curve[i]["equity"] - self.equity_curve[i-1]["equity"]) / self.equity_curve[i-1]["equity"]
                returns.append(ret)

            if returns:
                import statistics
                avg_return = statistics.mean(returns)
                std_return = statistics.stdev(returns) if len(returns) > 1 else 0
                if std_return > 0:
                    result.sharpe_ratio = (avg_return / std_return) * (252 ** 0.5)  # annualized

        return result
