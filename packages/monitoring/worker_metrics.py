"""
Worker-specific metrics для 5-process architecture (Этап 5.1).

Каждый worker должен экспортировать:
- Базовые: process_up, restarts_total, cpu_seconds, memory_bytes
- Специфичные: зависят от роли worker

Integration:
    from packages.monitoring.worker_metrics import CollectorMetrics
    metrics = CollectorMetrics()
    metrics.trades_received.inc()
"""

import logging
from dataclasses import dataclass

from packages.monitoring.metrics import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)


def _to_prometheus_format(metrics_obj) -> str:
    """Helper: export metrics object to Prometheus format."""
    lines = []
    for attr_name in dir(metrics_obj):
        attr = getattr(metrics_obj, attr_name)
        if isinstance(attr, Counter):
            lines.append(f"# TYPE {attr.name} counter")
            lines.append(f"{attr.name} {attr.value}")
        elif isinstance(attr, Gauge):
            lines.append(f"# TYPE {attr.name} gauge")
            lines.append(f"{attr.name} {attr.value}")
        elif isinstance(attr, Histogram):
            lines.append(f"# TYPE {attr.name} histogram")
            # Sort buckets: regular floats first, then +Inf
            regular_buckets = [(b, c) for b, c in attr.counts.items() if b != float('inf')]
            regular_buckets.sort(key=lambda x: x[0])
            for bucket, count in regular_buckets:
                lines.append(f'{attr.name}_bucket{{le="{bucket}"}} {count}')
            # +Inf last
            if float('inf') in attr.counts:
                lines.append(f'{attr.name}_bucket{{le="+Inf"}} {attr.counts[float("inf")]}')
            lines.append(f"{attr.name}_sum {attr.sum}")
            lines.append(f"{attr.name}_count {attr.count}")
    return "\n".join(lines)


@dataclass
class CollectorMetrics:
    """Metrics для collector-worker (WebSocket → WAL)."""

    # Process health
    process_up: Gauge
    restarts_total: Counter

    # WebSocket
    ws_connections_active: Gauge
    ws_reconnects_total: Counter
    ws_messages_received_total: Counter
    ws_errors_total: Counter

    # Data ingestion
    trades_received_total: Counter
    book_events_received_total: Counter
    wal_writes_total: Counter
    wal_write_latency_seconds: Histogram
    wal_fsync_latency_seconds: Histogram

    # IPC publishing
    ipc_published_total: Counter
    ipc_drops_total: Counter

    # Fencing (WriterLease)
    fencing_conflicts_total: Counter
    fencing_renewals_total: Counter

    def __init__(self):
        self.process_up = Gauge("collector_process_up")
        self.restarts_total = Counter("collector_restarts_total")

        self.ws_connections_active = Gauge("collector_ws_connections_active")
        self.ws_reconnects_total = Counter("collector_ws_reconnects_total")
        self.ws_messages_received_total = Counter("collector_ws_messages_received_total")
        self.ws_errors_total = Counter("collector_ws_errors_total")

        self.trades_received_total = Counter("collector_trades_received_total")
        self.book_events_received_total = Counter("collector_book_events_received_total")
        self.wal_writes_total = Counter("collector_wal_writes_total")
        self.wal_write_latency_seconds = Histogram("collector_wal_write_latency_seconds")
        self.wal_fsync_latency_seconds = Histogram("collector_wal_fsync_latency_seconds")

        self.ipc_published_total = Counter("collector_ipc_published_total")
        self.ipc_drops_total = Counter("collector_ipc_drops_total")

        self.fencing_conflicts_total = Counter("collector_fencing_conflicts_total")
        self.fencing_renewals_total = Counter("collector_fencing_renewals_total")

        self.process_up.set(1)

    def to_prometheus(self) -> str:
        """Export all metrics в Prometheus exposition format."""
        return _to_prometheus_format(self)


@dataclass
class AnalyticsMetrics:
    """Metrics для analytics-worker (Parquet + WAL tail → analytics)."""

    process_up: Gauge
    restarts_total: Counter

    # Storage reads
    parquet_reads_total: Counter
    parquet_read_latency_seconds: Histogram
    wal_tail_reads_total: Counter
    wal_tail_events_merged: Counter

    # Queries
    queries_total: Counter
    query_latency_seconds: Histogram
    query_errors_total: Counter

    # Cache
    cache_hits_total: Counter
    cache_misses_total: Counter
    cache_invalidations_total: Counter

    # Data quality
    data_gaps_detected_total: Counter

    def __init__(self):
        self.process_up = Gauge("analytics_process_up")
        self.restarts_total = Counter("analytics_restarts_total")

        self.parquet_reads_total = Counter("analytics_parquet_reads_total")
        self.parquet_read_latency_seconds = Histogram("analytics_parquet_read_latency_seconds")
        self.wal_tail_reads_total = Counter("analytics_wal_tail_reads_total")
        self.wal_tail_events_merged = Counter("analytics_wal_tail_events_merged")

        self.queries_total = Counter("analytics_queries_total")
        self.query_latency_seconds = Histogram("analytics_query_latency_seconds")
        self.query_errors_total = Counter("analytics_query_errors_total")

        self.cache_hits_total = Counter("analytics_cache_hits_total")
        self.cache_misses_total = Counter("analytics_cache_misses_total")
        self.cache_invalidations_total = Counter("analytics_cache_invalidations_total")

        self.data_gaps_detected_total = Counter("analytics_data_gaps_detected_total")

        self.process_up.set(1)

    def to_prometheus(self) -> str:
        return _to_prometheus_format(self)


@dataclass
class OrderflowMetrics:
    """Metrics для orderflow-worker (live BookState + detectors)."""

    process_up: Gauge
    restarts_total: Counter

    # BookState
    book_snapshots_processed: Counter
    book_deltas_processed: Counter
    book_gaps_detected_total: Counter
    book_state_status: Gauge  # 0=not_ready, 1=syncing, 2=ready, 3=gap

    # Detectors
    sweeps_detected_total: Counter
    cascades_detected_total: Counter
    walls_detected_total: Counter
    absorption_events_total: Counter

    # Regime
    regime_changes_total: Counter
    regime_confidence: Gauge

    # IPC
    ipc_events_received_total: Counter
    ipc_events_dropped_total: Counter
    orderflow_events_published_total: Counter
    orderflow_events_dropped_total: Counter

    # Performance
    event_processing_latency_seconds: Histogram

    def __init__(self):
        self.process_up = Gauge("orderflow_process_up")
        self.restarts_total = Counter("orderflow_restarts_total")

        self.book_snapshots_processed = Counter("orderflow_book_snapshots_processed")
        self.book_deltas_processed = Counter("orderflow_book_deltas_processed")
        self.book_gaps_detected_total = Counter("orderflow_book_gaps_detected_total")
        self.book_state_status = Gauge("orderflow_book_state_status")

        self.sweeps_detected_total = Counter("orderflow_sweeps_detected_total")
        self.cascades_detected_total = Counter("orderflow_cascades_detected_total")
        self.walls_detected_total = Counter("orderflow_walls_detected_total")
        self.absorption_events_total = Counter("orderflow_absorption_events_total")

        self.regime_changes_total = Counter("orderflow_regime_changes_total")
        self.regime_confidence = Gauge("orderflow_regime_confidence")

        self.ipc_events_received_total = Counter("orderflow_ipc_events_received_total")
        self.ipc_events_dropped_total = Counter("orderflow_ipc_events_dropped_total")
        self.orderflow_events_published_total = Counter("orderflow_events_published_total")
        self.orderflow_events_dropped_total = Counter("orderflow_events_dropped_total")

        self.event_processing_latency_seconds = Histogram("orderflow_event_processing_latency_seconds")

        self.process_up.set(1)

    def to_prometheus(self) -> str:
        return _to_prometheus_format(self)


@dataclass
class MaintenanceMetrics:
    """Metrics для maintenance-worker (WAL → Parquet + cleanup)."""

    process_up: Gauge
    restarts_total: Counter

    # WAL → Parquet
    segments_committed_total: Counter
    segment_commit_latency_seconds: Histogram
    segment_size_bytes: Histogram
    events_per_segment: Histogram

    # Cleanup
    segments_deleted_total: Counter
    wal_files_rotated_total: Counter
    disk_space_freed_bytes: Counter

    # Health
    wal_lag_seconds: Gauge
    parquet_segments_total: Gauge
    disk_usage_bytes: Gauge

    def __init__(self):
        self.process_up = Gauge("maintenance_process_up")
        self.restarts_total = Counter("maintenance_restarts_total")

        self.segments_committed_total = Counter("maintenance_segments_committed_total")
        self.segment_commit_latency_seconds = Histogram("maintenance_segment_commit_latency_seconds")
        self.segment_size_bytes = Histogram("maintenance_segment_size_bytes")
        self.events_per_segment = Histogram("maintenance_events_per_segment")

        self.segments_deleted_total = Counter("maintenance_segments_deleted_total")
        self.wal_files_rotated_total = Counter("maintenance_wal_files_rotated_total")
        self.disk_space_freed_bytes = Counter("maintenance_disk_space_freed_bytes")

        self.wal_lag_seconds = Gauge("maintenance_wal_lag_seconds")
        self.parquet_segments_total = Gauge("maintenance_parquet_segments_total")
        self.disk_usage_bytes = Gauge("maintenance_disk_usage_bytes")

        self.process_up.set(1)

    def to_prometheus(self) -> str:
        return _to_prometheus_format(self)


@dataclass
class APIMetrics:
    """Metrics для api-server (HTTP/WebSocket proxy)."""

    process_up: Gauge
    restarts_total: Counter

    # HTTP
    http_requests_total: Counter
    http_request_duration_seconds: Histogram
    http_errors_total: Counter

    # WebSocket
    ws_connections_active: Gauge
    ws_messages_sent_total: Counter

    # IPC client
    ipc_requests_total: Counter
    ipc_request_latency_seconds: Histogram
    ipc_errors_total: Counter
    ipc_timeouts_total: Counter

    def __init__(self):
        self.process_up = Gauge("api_process_up")
        self.restarts_total = Counter("api_restarts_total")

        self.http_requests_total = Counter("api_http_requests_total")
        self.http_request_duration_seconds = Histogram("api_http_request_duration_seconds")
        self.http_errors_total = Counter("api_http_errors_total")

        self.ws_connections_active = Gauge("api_ws_connections_active")
        self.ws_messages_sent_total = Counter("api_ws_messages_sent_total")

        self.ipc_requests_total = Counter("api_ipc_requests_total")
        self.ipc_request_latency_seconds = Histogram("api_ipc_request_latency_seconds")
        self.ipc_errors_total = Counter("api_ipc_errors_total")
        self.ipc_timeouts_total = Counter("api_ipc_timeouts_total")

        self.process_up.set(1)

    def to_prometheus(self) -> str:
        return _to_prometheus_format(self)
