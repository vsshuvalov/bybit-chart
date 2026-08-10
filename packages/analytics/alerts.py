"""
Real-Time Alert System (Feature B).

Источник: User request для practical trading features

Архитектура:
- Alert conditions: price levels, volume spikes, Delta/CVD thresholds
- Real-time evaluation при каждом trade/update
- WebSocket push notifications на frontend
- Persistent alert storage (JSON/SQLite в future)

Alert Types:
- Price Alert: trigger когда price достигает level
- Volume Alert: trigger когда volume spike detected
- Delta Alert: trigger когда Delta exceeds threshold
- Imbalance Alert: trigger когда orderbook imbalance критический

MVP: In-memory alerts, WebSocket notifications
Future: Persistent storage, email/SMS notifications
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class AlertType(Enum):
    """Типы alerts."""
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    VOLUME_SPIKE = "volume_spike"
    DELTA_POSITIVE = "delta_positive"
    DELTA_NEGATIVE = "delta_negative"
    IMBALANCE_BULLISH = "imbalance_bullish"
    IMBALANCE_BEARISH = "imbalance_bearish"


class AlertStatus(Enum):
    """Статусы alerts."""
    ACTIVE = "active"
    TRIGGERED = "triggered"
    CANCELLED = "cancelled"


@dataclass
class AlertCondition:
    """Условие для alert trigger."""
    alert_type: AlertType
    threshold: float  # price level, volume multiplier, delta threshold
    symbol: str


@dataclass
class Alert:
    """Alert instance."""
    id: str
    symbol: str
    condition: AlertCondition
    status: AlertStatus = AlertStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.utcnow)
    triggered_at: datetime | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize alert to dict."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "alert_type": self.condition.alert_type.value,
            "threshold": self.condition.threshold,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "message": self.message,
        }


class AlertEngine:
    """Real-time alert evaluation engine."""

    def __init__(self):
        """Initialize alert engine."""
        self.alerts: dict[str, Alert] = {}  # alert_id → Alert
        self.alert_callbacks: list[Callable[[Alert], None]] = []

    def create_alert(
        self,
        alert_id: str,
        symbol: str,
        alert_type: AlertType,
        threshold: float,
    ) -> Alert:
        """Создать новый alert.

        Args:
            alert_id: unique alert ID
            symbol: BTCUSDT, ETHUSDT, XRPUSDT
            alert_type: тип alert (PRICE_ABOVE, VOLUME_SPIKE, ...)
            threshold: порог срабатывания

        Returns:
            Alert instance
        """
        condition = AlertCondition(
            alert_type=alert_type,
            threshold=threshold,
            symbol=symbol,
        )

        alert = Alert(
            id=alert_id,
            symbol=symbol,
            condition=condition,
            status=AlertStatus.ACTIVE,
        )

        self.alerts[alert_id] = alert
        logger.info(f"Alert created: {alert_id}, type={alert_type.value}, threshold={threshold}")

        return alert

    def cancel_alert(self, alert_id: str) -> bool:
        """Отменить alert.

        Args:
            alert_id: ID alert для отмены

        Returns:
            True если успешно отменён
        """
        if alert_id in self.alerts:
            self.alerts[alert_id].status = AlertStatus.CANCELLED
            logger.info(f"Alert cancelled: {alert_id}")
            return True

        return False

    def register_callback(self, callback: Callable[[Alert], None]):
        """Зарегистрировать callback для triggered alerts.

        Args:
            callback: функция, вызываемая при trigger alert
        """
        self.alert_callbacks.append(callback)

    def evaluate_price_alert(self, symbol: str, price_ticks: int, price_tick: float):
        """Проверить price alerts для symbol.

        Args:
            symbol: BTCUSDT, ETHUSDT, XRPUSDT
            price_ticks: текущая цена (scaled integer)
            price_tick: PRICE_TICK для конверсии
        """
        current_price = price_ticks * price_tick

        for alert in self.alerts.values():
            if alert.status != AlertStatus.ACTIVE or alert.symbol != symbol:
                continue

            if alert.condition.alert_type == AlertType.PRICE_ABOVE:
                if current_price >= alert.condition.threshold:
                    self._trigger_alert(
                        alert,
                        f"Price ${current_price:.2f} reached alert level ${alert.condition.threshold:.2f}"
                    )

            elif alert.condition.alert_type == AlertType.PRICE_BELOW:
                if current_price <= alert.condition.threshold:
                    self._trigger_alert(
                        alert,
                        f"Price ${current_price:.2f} dropped below ${alert.condition.threshold:.2f}"
                    )

    def evaluate_volume_alert(self, symbol: str, volume_steps: int, avg_volume_steps: int):
        """Проверить volume spike alerts.

        Args:
            symbol: BTCUSDT, ETHUSDT, XRPUSDT
            volume_steps: текущий volume
            avg_volume_steps: средний volume (baseline)
        """
        if avg_volume_steps == 0:
            return

        volume_ratio = volume_steps / avg_volume_steps

        for alert in self.alerts.values():
            if alert.status != AlertStatus.ACTIVE or alert.symbol != symbol:
                continue

            if alert.condition.alert_type == AlertType.VOLUME_SPIKE:
                if volume_ratio >= alert.condition.threshold:
                    self._trigger_alert(
                        alert,
                        f"Volume spike detected: {volume_ratio:.1f}x average volume"
                    )

    def evaluate_delta_alert(self, symbol: str, delta: int):
        """Проверить Delta alerts.

        Args:
            symbol: BTCUSDT, ETHUSDT, XRPUSDT
            delta: текущий Delta (buy_volume - sell_volume)
        """
        for alert in self.alerts.values():
            if alert.status != AlertStatus.ACTIVE or alert.symbol != symbol:
                continue

            if alert.condition.alert_type == AlertType.DELTA_POSITIVE:
                if delta >= alert.condition.threshold:
                    self._trigger_alert(
                        alert,
                        f"Strong buying pressure: Delta = {delta}"
                    )

            elif alert.condition.alert_type == AlertType.DELTA_NEGATIVE:
                if delta <= -alert.condition.threshold:
                    self._trigger_alert(
                        alert,
                        f"Strong selling pressure: Delta = {delta}"
                    )

    def evaluate_imbalance_alert(self, symbol: str, imbalance: float):
        """Проверить orderbook imbalance alerts.

        Args:
            symbol: BTCUSDT, ETHUSDT, XRPUSDT
            imbalance: orderbook imbalance [-1, 1]
        """
        for alert in self.alerts.values():
            if alert.status != AlertStatus.ACTIVE or alert.symbol != symbol:
                continue

            if alert.condition.alert_type == AlertType.IMBALANCE_BULLISH:
                if imbalance >= alert.condition.threshold:
                    self._trigger_alert(
                        alert,
                        f"Bullish orderbook imbalance: {imbalance:.2f}"
                    )

            elif alert.condition.alert_type == AlertType.IMBALANCE_BEARISH:
                if imbalance <= -alert.condition.threshold:
                    self._trigger_alert(
                        alert,
                        f"Bearish orderbook imbalance: {imbalance:.2f}"
                    )

    def _trigger_alert(self, alert: Alert, message: str):
        """Trigger alert и вызвать callbacks.

        Args:
            alert: Alert instance
            message: описание trigger события
        """
        alert.status = AlertStatus.TRIGGERED
        alert.triggered_at = datetime.utcnow()
        alert.message = message

        logger.info(f"Alert triggered: {alert.id}, {message}")

        # Вызываем callbacks
        for callback in self.alert_callbacks:
            try:
                callback(alert)
            except Exception as exc:
                logger.error(f"Alert callback error: {exc}", exc_info=True)

    def get_active_alerts(self, symbol: str | None = None) -> list[Alert]:
        """Получить список активных alerts.

        Args:
            symbol: фильтр по symbol (optional)

        Returns:
            Список активных alerts
        """
        alerts = [a for a in self.alerts.values() if a.status == AlertStatus.ACTIVE]

        if symbol:
            alerts = [a for a in alerts if a.symbol == symbol]

        return alerts

    def get_triggered_alerts(self, symbol: str | None = None, limit: int = 50) -> list[Alert]:
        """Получить историю triggered alerts.

        Args:
            symbol: фильтр по symbol (optional)
            limit: максимальное количество alerts

        Returns:
            Список triggered alerts (newest first)
        """
        alerts = [a for a in self.alerts.values() if a.status == AlertStatus.TRIGGERED]

        if symbol:
            alerts = [a for a in alerts if a.symbol == symbol]

        # Сортируем по triggered_at (newest first)
        alerts.sort(key=lambda a: a.triggered_at or datetime.min, reverse=True)

        return alerts[:limit]
