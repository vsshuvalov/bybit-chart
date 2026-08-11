"""
Tests для IPC Publisher и Subscriber.

Источник: ADR-016, Roadmap §5.1 (Этап 2)

Тестируется:
    - Non-blocking publish (не блокирует при отсутствии subscriber)
    - Publisher → Subscriber round-trip
    - Backpressure: drop при недоступном subscriber
    - Version mismatch handling
    - Parse error handling
    - Metrics tracking
    - Graceful stop
"""

import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from packages.ipc.publisher import IPCPublisher, PublisherMetrics
from packages.ipc.subscriber import IPCSubscriber, SubscriberMetrics

pytestmark = pytest.mark.integration


# ------------------------------------------------------------------
# Publisher unit tests
# ------------------------------------------------------------------

class TestIPCPublisher:

    def test_publish_returns_false_when_no_subscriber(self, short_sock_dir):
        """Нет subscriber → drop (не бросает исключение)."""
        sock_path = short_sock_dir / "test.sock"
        pub = IPCPublisher(sock_path)
        result = pub.publish_raw("TestEvent", {"value": 1})
        # Нет subscriber → FileNotFoundError → False
        assert result is False

    def test_publish_increments_connect_errors_when_no_subscriber(self, short_sock_dir):
        sock_path = short_sock_dir / "test.sock"
        pub = IPCPublisher(sock_path)
        pub.publish_raw("TestEvent", {"value": 1})
        assert pub.metrics.connect_errors == 1
        assert pub.metrics.published == 0

    def test_publish_raw_sends_valid_envelope(self, short_sock_dir):
        """Отправленный envelope содержит все поля."""
        sock_path = short_sock_dir / "recv.sock"

        # Создаём временный DGRAM socket для приёма
        recv_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        recv_sock.bind(str(sock_path))
        recv_sock.settimeout(1.0)

        try:
            pub = IPCPublisher(sock_path)
            ok = pub.publish_raw("RawTrade", {"price": 50000, "qty": 1})
            assert ok is True
            assert pub.metrics.published == 1

            data, _ = recv_sock.recvfrom(65507)
            envelope = json.loads(data.decode())

            assert envelope["version"] == 1
            assert envelope["event_type"] == "RawTrade"
            assert envelope["payload"] == {"price": 50000, "qty": 1}
            assert "timestamp_us" in envelope
            assert "source" in envelope
        finally:
            recv_sock.close()
            sock_path.unlink(missing_ok=True)

    def test_oversized_message_dropped(self, short_sock_dir):
        """Сообщение > 65507 байт дропается."""
        sock_path = short_sock_dir / "recv.sock"
        recv_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        recv_sock.bind(str(sock_path))

        try:
            pub = IPCPublisher(sock_path)
            big_payload = {"data": "x" * 70000}
            ok = pub.publish_raw("BigEvent", big_payload)
            assert ok is False
            assert pub.metrics.oversized_drops == 1
        finally:
            recv_sock.close()
            sock_path.unlink(missing_ok=True)

    def test_close_cleans_up_socket(self, short_sock_dir):
        """close() корректно закрывает socket."""
        sock_path = short_sock_dir / "test.sock"
        pub = IPCPublisher(sock_path)
        pub._sock = pub._create_socket()  # Force socket creation
        pub.close()
        assert pub._sock is None

    def test_metrics_total_drops(self, short_sock_dir):
        """total_drops = backpressure_drops + oversized_drops."""
        metrics = PublisherMetrics()
        metrics.backpressure_drops = 3
        metrics.oversized_drops = 2
        assert metrics.total_drops == 5

    def test_metrics_to_dict(self, short_sock_dir):
        """to_dict() содержит все счётчики."""
        metrics = PublisherMetrics(published=10, backpressure_drops=2, errors=1)
        d = metrics.to_dict()
        assert d["published"] == 10
        assert d["backpressure_drops"] == 2
        assert d["errors"] == 1


# ------------------------------------------------------------------
# Subscriber unit tests
# ------------------------------------------------------------------

class TestIPCSubscriber:

    def test_register_handler(self, short_sock_dir):
        """Handler регистрируется корректно."""
        sock_path = short_sock_dir / "sub.sock"
        sub = IPCSubscriber(sock_path)
        called = []
        sub.register_handler("TestEvent", lambda p: called.append(p))
        assert "TestEvent" in sub._handlers

    def test_dispatch_calls_handler(self, short_sock_dir):
        """_dispatch вызывает зарегистрированный handler."""
        sock_path = short_sock_dir / "sub.sock"
        sub = IPCSubscriber(sock_path)
        received = []
        sub.register_handler("RawTrade", lambda p: received.append(p))

        envelope = {
            "version": 1,
            "event_type": "RawTrade",
            "source": "collector",
            "timestamp_us": 1000,
            "payload": {"price": 50000},
        }
        sub._dispatch(json.dumps(envelope).encode())

        assert len(received) == 1
        assert received[0]["price"] == 50000
        assert sub.metrics.processed == 1

    def test_dispatch_version_mismatch(self, short_sock_dir):
        """Неверная версия → skip + increment version_mismatches."""
        sock_path = short_sock_dir / "sub.sock"
        sub = IPCSubscriber(sock_path)
        called = []
        sub.register_handler("Event", lambda p: called.append(p))

        envelope = {"version": 99, "event_type": "Event", "payload": {}}
        sub._dispatch(json.dumps(envelope).encode())

        assert len(called) == 0
        assert sub.metrics.version_mismatches == 1

    def test_dispatch_parse_error(self, short_sock_dir):
        """Невалидный JSON → skip + increment parse_errors."""
        sock_path = short_sock_dir / "sub.sock"
        sub = IPCSubscriber(sock_path)

        sub._dispatch(b"not-valid-json")

        assert sub.metrics.parse_errors == 1
        assert sub.metrics.processed == 0

    def test_dispatch_unknown_type(self, short_sock_dir):
        """Незнакомый event_type → skip + increment unknown_types."""
        sock_path = short_sock_dir / "sub.sock"
        sub = IPCSubscriber(sock_path)

        envelope = {"version": 1, "event_type": "Unknown", "payload": {}}
        sub._dispatch(json.dumps(envelope).encode())

        assert sub.metrics.unknown_types == 1

    def test_dispatch_handler_error_increments_metric(self, short_sock_dir):
        """Handler exception → increment handler_errors, не падаем."""
        sock_path = short_sock_dir / "sub.sock"
        sub = IPCSubscriber(sock_path)
        sub.register_handler("BadEvent", lambda p: 1 / 0)

        envelope = {"version": 1, "event_type": "BadEvent", "payload": {}}
        sub._dispatch(json.dumps(envelope).encode())  # Не должен бросать

        assert sub.metrics.handler_errors == 1


# ------------------------------------------------------------------
# Integration: Publisher → Subscriber round-trip
# ------------------------------------------------------------------

class TestPublisherSubscriberRoundTrip:

    def test_end_to_end_delivery(self, short_sock_dir):
        """Publisher отправляет → Subscriber получает."""
        sock_path = short_sock_dir / "roundtrip.sock"
        received = []
        done = threading.Event()

        sub = IPCSubscriber(sock_path)

        def on_event(payload):
            received.append(payload)
            if len(received) >= 3:
                done.set()

        sub.register_handler("TestEvent", on_event)
        thread = sub.run_in_thread(daemon=True)

        # Дать время subscriber-у создать socket
        time.sleep(0.05)

        pub = IPCPublisher(sock_path)
        for i in range(3):
            ok = pub.publish_raw("TestEvent", {"index": i})
            assert ok is True

        done.wait(timeout=2.0)
        sub.stop()
        thread.join(timeout=2.0)

        assert len(received) == 3
        assert [r["index"] for r in received] == [0, 1, 2]
        assert pub.metrics.published == 3

    def test_subscriber_handles_multiple_event_types(self, short_sock_dir):
        """Subscriber диспатчит разные event types в разные handlers."""
        sock_path = short_sock_dir / "multi.sock"
        trades = []
        books = []
        done = threading.Event()

        sub = IPCSubscriber(sock_path)
        sub.register_handler("RawTrade", lambda p: trades.append(p))

        def on_book(p):
            books.append(p)
            if len(trades) >= 1 and len(books) >= 1:
                done.set()

        sub.register_handler("RawBookEvent", on_book)
        thread = sub.run_in_thread(daemon=True)
        time.sleep(0.05)

        pub = IPCPublisher(sock_path)
        pub.publish_raw("RawTrade", {"price": 50000})
        pub.publish_raw("RawBookEvent", {"bids": []})

        done.wait(timeout=2.0)
        sub.stop()
        thread.join(timeout=2.0)

        assert len(trades) == 1
        assert len(books) == 1

    def test_subscriber_survives_malformed_messages(self, short_sock_dir):
        """Subscriber продолжает работать после невалидных сообщений."""
        sock_path = short_sock_dir / "robust.sock"
        received = []
        done = threading.Event()

        sub = IPCSubscriber(sock_path)

        def on_event(p):
            received.append(p)
            done.set()

        sub.register_handler("GoodEvent", on_event)
        thread = sub.run_in_thread(daemon=True)
        time.sleep(0.05)

        # Отправить напрямую мусор + потом хорошее сообщение
        raw_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            raw_sock.sendto(b"garbage-data", str(sock_path))
            raw_sock.sendto(b"{invalid json}", str(sock_path))
        finally:
            raw_sock.close()

        time.sleep(0.05)

        # Хорошее сообщение после мусора
        pub = IPCPublisher(sock_path)
        pub.publish_raw("GoodEvent", {"ok": True})

        done.wait(timeout=2.0)
        sub.stop()
        thread.join(timeout=2.0)

        assert len(received) == 1
        assert received[0]["ok"] is True
        assert sub.metrics.parse_errors >= 2

    def test_metrics_to_dict(self, short_sock_dir):
        """SubscriberMetrics.to_dict() содержит все поля."""
        metrics = SubscriberMetrics(received=10, processed=8, parse_errors=2)
        d = metrics.to_dict()
        assert d["received"] == 10
        assert d["processed"] == 8
        assert d["parse_errors"] == 2
