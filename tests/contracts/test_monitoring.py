"""
Тесты Monitoring & Metrics (Roadmap §15 extended).

Проверяют: MetricsCollector, Counter, Gauge, Histogram, Timer, Prometheus export.
"""

import pytest

from packages.monitoring import (
    Counter,
    Gauge,
    Histogram,
    MetricsCollector,
    Timer,
    get_metrics_collector,
)

pytestmark = pytest.mark.contract


class TestMetricsCollector:
    """Тесты MetricsCollector."""

    def test_collector_initialization(self):
        """MetricsCollector инициализируется с standard metrics."""
        collector = MetricsCollector()

        assert collector.http_requests_total is not None
        assert collector.http_request_duration_seconds is not None
        assert collector.websocket_connections_active is not None
        assert collector.data_gaps_detected is not None

    def test_create_counter(self):
        """counter() создаёт новый counter metric."""
        collector = MetricsCollector()

        counter = collector.counter("test_counter", "Test counter")

        assert counter.name == "test_counter"
        assert counter.value == 0

    def test_create_gauge(self):
        """gauge() создаёт новый gauge metric."""
        collector = MetricsCollector()

        gauge = collector.gauge("test_gauge", "Test gauge")

        assert gauge.name == "test_gauge"
        assert gauge.value == 0.0

    def test_create_histogram(self):
        """histogram() создаёт новый histogram metric."""
        collector = MetricsCollector()

        histogram = collector.histogram("test_histogram", "Test histogram")

        assert histogram.name == "test_histogram"
        assert histogram.count == 0
        assert histogram.sum == 0.0

    def test_get_same_metric(self):
        """Повторный вызов counter() возвращает тот же metric."""
        collector = MetricsCollector()

        counter1 = collector.counter("test_counter")
        counter1.inc()

        counter2 = collector.counter("test_counter")

        assert counter2.value == 1
        assert counter1 is counter2

    def test_export_prometheus_format(self):
        """export_prometheus() возвращает Prometheus format."""
        collector = MetricsCollector()

        counter = collector.counter("test_counter")
        counter.inc(5)

        gauge = collector.gauge("test_gauge")
        gauge.set(42.5)

        output = collector.export_prometheus()

        assert "# TYPE test_counter counter" in output
        assert "test_counter 5" in output
        assert "# TYPE test_gauge gauge" in output
        assert "test_gauge 42.5" in output

    def test_singleton_collector(self):
        """get_metrics_collector() возвращает singleton."""
        collector1 = get_metrics_collector()
        collector2 = get_metrics_collector()

        assert collector1 is collector2


class TestCounter:
    """Тесты Counter metric."""

    def test_counter_increment(self):
        """inc() увеличивает counter."""
        counter = Counter("test")

        counter.inc()
        assert counter.value == 1

        counter.inc(5)
        assert counter.value == 6

    def test_counter_initial_value(self):
        """Counter начинается с 0."""
        counter = Counter("test")
        assert counter.value == 0


class TestGauge:
    """Тесты Gauge metric."""

    def test_gauge_set(self):
        """set() устанавливает значение gauge."""
        gauge = Gauge("test")

        gauge.set(42.5)
        assert gauge.value == 42.5

        gauge.set(10.0)
        assert gauge.value == 10.0

    def test_gauge_increment(self):
        """inc() увеличивает gauge."""
        gauge = Gauge("test")

        gauge.inc()
        assert gauge.value == 1.0

        gauge.inc(5.5)
        assert gauge.value == 6.5

    def test_gauge_decrement(self):
        """dec() уменьшает gauge."""
        gauge = Gauge("test")
        gauge.set(10.0)

        gauge.dec()
        assert gauge.value == 9.0

        gauge.dec(3.0)
        assert gauge.value == 6.0


class TestHistogram:
    """Тесты Histogram metric."""

    def test_histogram_observe(self):
        """observe() записывает значения."""
        histogram = Histogram("test")

        histogram.observe(0.5)
        histogram.observe(1.5)
        histogram.observe(3.0)

        assert histogram.count == 3
        assert histogram.sum == 5.0

    def test_histogram_buckets(self):
        """observe() обновляет bucket counts."""
        histogram = Histogram("test", buckets=[1.0, 5.0, 10.0])

        histogram.observe(0.5)  # Falls in 1.0 bucket
        histogram.observe(3.0)  # Falls in 5.0 bucket
        histogram.observe(7.0)  # Falls in 10.0 bucket
        histogram.observe(15.0)  # Falls in +Inf bucket

        assert histogram.counts[1.0] == 1
        assert histogram.counts[5.0] == 2  # cumulative
        assert histogram.counts[10.0] == 3  # cumulative
        assert histogram.counts[float('inf')] == 4

    def test_histogram_export(self):
        """Histogram экспортируется в Prometheus format."""
        collector = MetricsCollector()
        histogram = collector.histogram("request_duration")

        histogram.observe(0.1)
        histogram.observe(0.5)
        histogram.observe(2.0)

        output = collector.export_prometheus()

        assert "# TYPE request_duration histogram" in output
        assert "request_duration_count 3" in output
        assert "request_duration_sum 2.6" in output
        assert 'request_duration_bucket{le="1.0"}' in output


class TestTimer:
    """Тесты Timer context manager."""

    def test_timer_records_duration(self):
        """Timer записывает duration в histogram."""
        import time

        histogram = Histogram("test")

        with Timer(histogram):
            time.sleep(0.01)

        assert histogram.count == 1
        assert histogram.sum > 0.01
        assert histogram.sum < 0.1  # Should be ~0.01s

    def test_timer_multiple_observations(self):
        """Timer работает для multiple operations."""
        histogram = Histogram("test")

        for _ in range(3):
            with Timer(histogram):
                pass

        assert histogram.count == 3


class TestMetricsIntegration:
    """Интеграционные тесты metrics."""

    def test_http_metrics_workflow(self):
        """Полный workflow HTTP metrics."""
        collector = MetricsCollector()

        # Simulate request
        collector.http_requests_total.inc()

        with Timer(collector.http_request_duration_seconds):
            pass  # simulate processing

        # Check metrics
        assert collector.http_requests_total.value == 1
        assert collector.http_request_duration_seconds.count == 1

    def test_websocket_metrics_workflow(self):
        """WebSocket metrics workflow."""
        collector = MetricsCollector()

        # Connection opened
        collector.websocket_connections_active.inc()
        collector.websocket_connections_total.inc()

        assert collector.websocket_connections_active.value == 1
        assert collector.websocket_connections_total.value == 1

        # Message sent
        collector.websocket_messages_sent.inc()

        # Connection closed
        collector.websocket_connections_active.dec()

        assert collector.websocket_connections_active.value == 0
        assert collector.websocket_connections_total.value == 1

    def test_data_quality_metrics(self):
        """Data quality metrics workflow."""
        collector = MetricsCollector()

        # Gaps detected
        collector.data_gaps_detected.inc(2)

        # Records processed
        collector.data_records_processed.inc(1000)

        # Segment published
        collector.data_segments_published.inc()

        assert collector.data_gaps_detected.value == 2
        assert collector.data_records_processed.value == 1000
        assert collector.data_segments_published.value == 1
