"""
Prometheus Metrics для monitoring (Roadmap §15 extended).

Источник: Roadmap §15 (monitoring, observability)

Архитектура:
- MetricsCollector — собирает метрики
- Prometheus exposition format
- FastAPI /metrics endpoint
- Standard metrics + custom business metrics

Metrics:
- Request metrics (count, latency, errors)
- WebSocket connections (active, total)
- Data quality (gaps, records, segments)
- Storage metrics (Parquet files, WAL size)
- Redis metrics (pub/sub, latency)

Integration: Prometheus → Grafana dashboards
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Counter:
    """Simple counter metric."""
    name: str
    value: int = 0
    labels: dict[str, str] = field(default_factory=dict)

    def inc(self, amount: int = 1):
        """Increment counter."""
        self.value += amount


@dataclass
class Gauge:
    """Gauge metric (can go up or down)."""
    name: str
    value: float = 0.0
    labels: dict[str, str] = field(default_factory=dict)

    def set(self, value: float):
        """Set gauge value."""
        self.value = value

    def inc(self, amount: float = 1.0):
        """Increment gauge."""
        self.value += amount

    def dec(self, amount: float = 1.0):
        """Decrement gauge."""
        self.value -= amount


@dataclass
class Histogram:
    """Histogram metric for distributions."""
    name: str
    buckets: list[float] = field(default_factory=lambda: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])
    counts: dict[float, int] = field(default_factory=dict)
    sum: float = 0.0
    count: int = 0
    labels: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize bucket counts."""
        for bucket in self.buckets:
            self.counts[bucket] = 0
        self.counts[float('inf')] = 0

    def observe(self, value: float):
        """Observe a value."""
        self.sum += value
        self.count += 1

        for bucket in self.buckets:
            if value <= bucket:
                self.counts[bucket] += 1

        self.counts[float('inf')] += 1


class MetricsCollector:
    """Metrics collector для Prometheus.

    Roadmap §15: centralized metrics collection.
    """

    def __init__(self):
        """Initialize metrics collector."""
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}
        self._lock = Lock()

        # Initialize standard metrics
        self._init_standard_metrics()

    def _init_standard_metrics(self):
        """Initialize standard application metrics."""
        # HTTP metrics
        self.http_requests_total = self.counter(
            "http_requests_total",
            "Total HTTP requests"
        )
        self.http_request_duration_seconds = self.histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds"
        )
        self.http_errors_total = self.counter(
            "http_errors_total",
            "Total HTTP errors"
        )

        # WebSocket metrics
        self.websocket_connections_active = self.gauge(
            "websocket_connections_active",
            "Active WebSocket connections"
        )
        self.websocket_connections_total = self.counter(
            "websocket_connections_total",
            "Total WebSocket connections"
        )
        self.websocket_messages_sent = self.counter(
            "websocket_messages_sent",
            "WebSocket messages sent"
        )

        # Data quality metrics
        self.data_gaps_detected = self.counter(
            "data_gaps_detected",
            "Data gaps detected"
        )
        self.data_records_processed = self.counter(
            "data_records_processed",
            "Data records processed"
        )
        self.data_segments_published = self.counter(
            "data_segments_published",
            "Parquet segments published"
        )

        # Storage metrics
        self.storage_wal_size_bytes = self.gauge(
            "storage_wal_size_bytes",
            "WAL storage size in bytes"
        )
        self.storage_parquet_files = self.gauge(
            "storage_parquet_files",
            "Number of Parquet files"
        )

        # Redis metrics
        self.redis_publish_total = self.counter(
            "redis_publish_total",
            "Redis publish operations"
        )
        self.redis_publish_latency_seconds = self.histogram(
            "redis_publish_latency_seconds",
            "Redis publish latency"
        )

    def counter(self, name: str, description: str = "") -> Counter:
        """Get or create counter metric.

        Args:
            name: metric name
            description: metric description

        Returns:
            Counter instance
        """
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name=name)
            return self._counters[name]

    def gauge(self, name: str, description: str = "") -> Gauge:
        """Get or create gauge metric.

        Args:
            name: metric name
            description: metric description

        Returns:
            Gauge instance
        """
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name=name)
            return self._gauges[name]

    def histogram(self, name: str, description: str = "") -> Histogram:
        """Get or create histogram metric.

        Args:
            name: metric name
            description: metric description

        Returns:
            Histogram instance
        """
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name=name)
            return self._histograms[name]

    def export_prometheus(self) -> str:
        """Export metrics в Prometheus exposition format.

        Returns:
            Metrics в Prometheus text format
        """
        lines = []

        # Export counters
        for counter in self._counters.values():
            lines.append(f"# TYPE {counter.name} counter")
            lines.append(f"{counter.name} {counter.value}")

        # Export gauges
        for gauge in self._gauges.values():
            lines.append(f"# TYPE {gauge.name} gauge")
            lines.append(f"{gauge.name} {gauge.value}")

        # Export histograms
        for hist in self._histograms.values():
            lines.append(f"# TYPE {hist.name} histogram")

            for bucket, count in sorted(hist.counts.items()):
                bucket_str = "+Inf" if bucket == float('inf') else str(bucket)
                lines.append(f'{hist.name}_bucket{{le="{bucket_str}"}} {count}')

            lines.append(f"{hist.name}_sum {hist.sum}")
            lines.append(f"{hist.name}_count {hist.count}")

        return "\n".join(lines) + "\n"


# Global metrics collector
_metrics_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector (singleton).

    Returns:
        MetricsCollector instance
    """
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


# Context manager для timing
class Timer:
    """Context manager для timing operations.

    Example:
        with Timer(metrics.http_request_duration_seconds):
            process_request()
    """

    def __init__(self, histogram: Histogram):
        """Initialize timer.

        Args:
            histogram: Histogram для записи duration
        """
        self.histogram = histogram
        self.start_time = None

    def __enter__(self):
        """Start timer."""
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop timer и record duration."""
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.histogram.observe(duration)
