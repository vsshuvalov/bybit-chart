"""
Тесты Real-Time Alert System (Feature B).

Проверяют: AlertEngine, alert evaluation, trigger callbacks.
"""

import pytest

from packages.analytics.alerts import AlertEngine, AlertType, AlertStatus

pytestmark = pytest.mark.contract


class TestAlertEngine:
    """Тесты AlertEngine."""

    def test_create_alert(self):
        """create_alert() создаёт новый alert."""
        engine = AlertEngine()

        alert = engine.create_alert(
            alert_id="alert_1",
            symbol="BTCUSDT",
            alert_type=AlertType.PRICE_ABOVE,
            threshold=65000.0,
        )

        assert alert.id == "alert_1"
        assert alert.symbol == "BTCUSDT"
        assert alert.status == AlertStatus.ACTIVE
        assert alert.condition.alert_type == AlertType.PRICE_ABOVE
        assert alert.condition.threshold == 65000.0

    def test_cancel_alert(self):
        """cancel_alert() отменяет alert."""
        engine = AlertEngine()

        engine.create_alert("alert_1", "BTCUSDT", AlertType.PRICE_ABOVE, 65000.0)
        result = engine.cancel_alert("alert_1")

        assert result is True
        assert engine.alerts["alert_1"].status == AlertStatus.CANCELLED

    def test_cancel_nonexistent_alert(self):
        """cancel_alert() возвращает False для несуществующего alert."""
        engine = AlertEngine()
        result = engine.cancel_alert("nonexistent")

        assert result is False

    def test_price_above_alert_triggers(self):
        """PRICE_ABOVE alert срабатывает когда price достигает threshold."""
        engine = AlertEngine()
        triggered_alerts = []

        engine.register_callback(lambda alert: triggered_alerts.append(alert))
        engine.create_alert("alert_1", "BTCUSDT", AlertType.PRICE_ABOVE, 65000.0)

        # Price ниже threshold — не срабатывает
        engine.evaluate_price_alert("BTCUSDT", price_ticks=6400000, price_tick=0.01)
        assert len(triggered_alerts) == 0

        # Price достигает threshold — срабатывает
        engine.evaluate_price_alert("BTCUSDT", price_ticks=6500000, price_tick=0.01)
        assert len(triggered_alerts) == 1
        assert triggered_alerts[0].id == "alert_1"
        assert triggered_alerts[0].status == AlertStatus.TRIGGERED

    def test_price_below_alert_triggers(self):
        """PRICE_BELOW alert срабатывает когда price падает ниже threshold."""
        engine = AlertEngine()
        triggered_alerts = []

        engine.register_callback(lambda alert: triggered_alerts.append(alert))
        engine.create_alert("alert_1", "BTCUSDT", AlertType.PRICE_BELOW, 64000.0)

        # Price выше threshold — не срабатывает
        engine.evaluate_price_alert("BTCUSDT", price_ticks=6500000, price_tick=0.01)
        assert len(triggered_alerts) == 0

        # Price падает ниже threshold — срабатывает
        engine.evaluate_price_alert("BTCUSDT", price_ticks=6390000, price_tick=0.01)
        assert len(triggered_alerts) == 1

    def test_volume_spike_alert_triggers(self):
        """VOLUME_SPIKE alert срабатывает при spike."""
        engine = AlertEngine()
        triggered_alerts = []

        engine.register_callback(lambda alert: triggered_alerts.append(alert))
        engine.create_alert("alert_1", "BTCUSDT", AlertType.VOLUME_SPIKE, 3.0)  # 3x avg

        # Обычный volume — не срабатывает
        engine.evaluate_volume_alert("BTCUSDT", volume_steps=1000, avg_volume_steps=1000)
        assert len(triggered_alerts) == 0

        # Volume spike 3x — срабатывает
        engine.evaluate_volume_alert("BTCUSDT", volume_steps=3000, avg_volume_steps=1000)
        assert len(triggered_alerts) == 1

    def test_delta_positive_alert_triggers(self):
        """DELTA_POSITIVE alert срабатывает при сильном buying pressure."""
        engine = AlertEngine()
        triggered_alerts = []

        engine.register_callback(lambda alert: triggered_alerts.append(alert))
        engine.create_alert("alert_1", "BTCUSDT", AlertType.DELTA_POSITIVE, 10000)

        # Delta ниже threshold — не срабатывает
        engine.evaluate_delta_alert("BTCUSDT", delta=5000)
        assert len(triggered_alerts) == 0

        # Delta достигает threshold — срабатывает
        engine.evaluate_delta_alert("BTCUSDT", delta=10000)
        assert len(triggered_alerts) == 1

    def test_delta_negative_alert_triggers(self):
        """DELTA_NEGATIVE alert срабатывает при сильном selling pressure."""
        engine = AlertEngine()
        triggered_alerts = []

        engine.register_callback(lambda alert: triggered_alerts.append(alert))
        engine.create_alert("alert_1", "BTCUSDT", AlertType.DELTA_NEGATIVE, 10000)

        # Delta не достаточно отрицательный — не срабатывает
        engine.evaluate_delta_alert("BTCUSDT", delta=-5000)
        assert len(triggered_alerts) == 0

        # Delta достигает -threshold — срабатывает
        engine.evaluate_delta_alert("BTCUSDT", delta=-10000)
        assert len(triggered_alerts) == 1

    def test_imbalance_bullish_alert_triggers(self):
        """IMBALANCE_BULLISH alert срабатывает при bullish imbalance."""
        engine = AlertEngine()
        triggered_alerts = []

        engine.register_callback(lambda alert: triggered_alerts.append(alert))
        engine.create_alert("alert_1", "BTCUSDT", AlertType.IMBALANCE_BULLISH, 0.5)

        # Imbalance ниже threshold — не срабатывает
        engine.evaluate_imbalance_alert("BTCUSDT", imbalance=0.3)
        assert len(triggered_alerts) == 0

        # Imbalance достигает threshold — срабатывает
        engine.evaluate_imbalance_alert("BTCUSDT", imbalance=0.6)
        assert len(triggered_alerts) == 1

    def test_imbalance_bearish_alert_triggers(self):
        """IMBALANCE_BEARISH alert срабатывает при bearish imbalance."""
        engine = AlertEngine()
        triggered_alerts = []

        engine.register_callback(lambda alert: triggered_alerts.append(alert))
        engine.create_alert("alert_1", "BTCUSDT", AlertType.IMBALANCE_BEARISH, 0.5)

        # Imbalance не достаточно отрицательный — не срабатывает
        engine.evaluate_imbalance_alert("BTCUSDT", imbalance=-0.3)
        assert len(triggered_alerts) == 0

        # Imbalance достигает -threshold — срабатывает
        engine.evaluate_imbalance_alert("BTCUSDT", imbalance=-0.6)
        assert len(triggered_alerts) == 1

    def test_alert_triggers_only_once(self):
        """Alert срабатывает только один раз."""
        engine = AlertEngine()
        triggered_alerts = []

        engine.register_callback(lambda alert: triggered_alerts.append(alert))
        engine.create_alert("alert_1", "BTCUSDT", AlertType.PRICE_ABOVE, 65000.0)

        # Первый trigger
        engine.evaluate_price_alert("BTCUSDT", price_ticks=6500000, price_tick=0.01)
        assert len(triggered_alerts) == 1

        # Второй вызов — не срабатывает (уже triggered)
        engine.evaluate_price_alert("BTCUSDT", price_ticks=6600000, price_tick=0.01)
        assert len(triggered_alerts) == 1

    def test_get_active_alerts(self):
        """get_active_alerts() возвращает только активные."""
        engine = AlertEngine()

        engine.create_alert("alert_1", "BTCUSDT", AlertType.PRICE_ABOVE, 65000.0)
        engine.create_alert("alert_2", "ETHUSDT", AlertType.PRICE_ABOVE, 3200.0)
        engine.cancel_alert("alert_1")

        active = engine.get_active_alerts()
        assert len(active) == 1
        assert active[0].id == "alert_2"

    def test_get_active_alerts_by_symbol(self):
        """get_active_alerts() фильтрует по symbol."""
        engine = AlertEngine()

        engine.create_alert("alert_1", "BTCUSDT", AlertType.PRICE_ABOVE, 65000.0)
        engine.create_alert("alert_2", "ETHUSDT", AlertType.PRICE_ABOVE, 3200.0)

        active_btc = engine.get_active_alerts(symbol="BTCUSDT")
        assert len(active_btc) == 1
        assert active_btc[0].symbol == "BTCUSDT"

    def test_get_triggered_alerts(self):
        """get_triggered_alerts() возвращает историю."""
        engine = AlertEngine()
        engine.register_callback(lambda alert: None)

        engine.create_alert("alert_1", "BTCUSDT", AlertType.PRICE_ABOVE, 65000.0)
        engine.create_alert("alert_2", "BTCUSDT", AlertType.PRICE_ABOVE, 66000.0)

        # Trigger оба
        engine.evaluate_price_alert("BTCUSDT", price_ticks=6700000, price_tick=0.01)

        triggered = engine.get_triggered_alerts()
        assert len(triggered) == 2

    def test_alert_to_dict(self):
        """Alert.to_dict() сериализует в JSON-compatible формат."""
        engine = AlertEngine()
        alert = engine.create_alert("alert_1", "BTCUSDT", AlertType.PRICE_ABOVE, 65000.0)

        data = alert.to_dict()

        assert data["id"] == "alert_1"
        assert data["symbol"] == "BTCUSDT"
        assert data["alert_type"] == "price_above"
        assert data["threshold"] == 65000.0
        assert data["status"] == "active"
        assert "created_at" in data
