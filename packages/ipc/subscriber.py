"""
IPC Subscriber — blocking event loop для получения событий.

Источник: ADR-016, Roadmap §5.1 (Этап 2)

Принцип:
    - Blocking recv в отдельном потоке (не блокирует основной цикл)
    - Dispatch по event_type → зарегистрированные handlers
    - Drop при version mismatch / parse error → log + continue
    - Автоматический cleanup socket файла при stop

Usage:
    sub = IPCSubscriber("/tmp/bybit-analytics.sock")
    sub.register_handler("RawTrade", on_trade)
    sub.register_handler("RawBookEvent", on_book)
    sub.run()  # blocking, запускать в thread
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_RECV_BUFFER = 65507
_SUPPORTED_VERSION = 1


@dataclass
class SubscriberMetrics:
    """Счётчики для мониторинга subscriber."""
    received: int = 0
    processed: int = 0
    parse_errors: int = 0
    version_mismatches: int = 0
    unknown_types: int = 0
    handler_errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "received": self.received,
            "processed": self.processed,
            "parse_errors": self.parse_errors,
            "version_mismatches": self.version_mismatches,
            "unknown_types": self.unknown_types,
            "handler_errors": self.handler_errors,
        }


Handler = Callable[[dict], None]


class IPCSubscriber:
    """Blocking IPC subscriber через Unix Domain Socket SOCK_DGRAM.

    Analytics использует этот класс для получения событий от collector.

    Важно: при потере сообщений (backpressure на publisher side) analytics
    восстанавливает state из WAL.

    Usage:
        sub = IPCSubscriber("/tmp/bybit-analytics.sock")
        sub.register_handler("RawTrade", lambda payload: process_trade(payload))

        # В отдельном потоке:
        thread = threading.Thread(target=sub.run, daemon=True)
        thread.start()

        # Остановка:
        sub.stop()
    """

    def __init__(
        self,
        socket_path: str | Path,
        buffer_size: int = _RECV_BUFFER,
    ):
        """Инициализировать subscriber.

        Args:
            socket_path: путь к UDS socket (будет создан при start)
            buffer_size: размер recv buffer (bytes)
        """
        self.socket_path = Path(socket_path)
        self.buffer_size = buffer_size
        self.metrics = SubscriberMetrics()
        self._handlers: dict[str, Handler] = {}
        self._sock: socket.socket | None = None
        self._running = False
        self._lock = threading.Lock()

    def register_handler(self, event_type: str, handler: Handler) -> None:
        """Зарегистрировать handler для event type.

        Args:
            event_type: тип события (например, "RawTrade", "RawBookEvent")
            handler: callable(payload: dict) → None
        """
        self._handlers[event_type] = handler

    def run(self) -> None:
        """Запустить blocking event loop.

        Вызывать в отдельном потоке. Возвращает управление только после stop().
        """
        self._start_socket()
        self._running = True
        logger.info("IPC subscriber started: %s", self.socket_path)

        try:
            while self._running:
                try:
                    data, _ = self._sock.recvfrom(self.buffer_size)
                    self.metrics.received += 1
                    self._dispatch(data)
                except OSError as exc:
                    if not self._running:
                        break  # Graceful shutdown
                    logger.debug("IPC recv error: %s", exc)
        finally:
            self._cleanup()
            logger.info("IPC subscriber stopped: %s", self.socket_path)

    def stop(self) -> None:
        """Остановить event loop."""
        self._running = False
        # Закрыть socket чтобы разблокировать recvfrom
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def run_in_thread(self, daemon: bool = True) -> threading.Thread:
        """Запустить subscriber в фоновом потоке.

        Args:
            daemon: если True, поток завершится вместе с main процессом

        Returns:
            Thread object
        """
        t = threading.Thread(target=self.run, daemon=daemon, name="ipc-subscriber")
        t.start()
        return t

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _start_socket(self) -> None:
        """Создать и bind UDS socket."""
        # Удалить старый socket файл
        if self.socket_path.exists():
            self.socket_path.unlink()

        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._sock.bind(str(self.socket_path))
        # Blocking recv (main loop использует timeout-based check)
        self._sock.settimeout(1.0)  # 1s timeout для проверки _running

    def _dispatch(self, data: bytes) -> None:
        """Разобрать и диспатчить сообщение."""
        try:
            envelope = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.metrics.parse_errors += 1
            logger.debug("IPC parse error: %s", exc)
            return

        # Version check
        version = envelope.get("version")
        if version != _SUPPORTED_VERSION:
            self.metrics.version_mismatches += 1
            logger.debug("IPC version mismatch: got %s, expected %s", version, _SUPPORTED_VERSION)
            return

        event_type = envelope.get("event_type", "")
        payload = envelope.get("payload", {})

        handler = self._handlers.get(event_type)
        if handler is None:
            self.metrics.unknown_types += 1
            return

        try:
            handler(payload)
            self.metrics.processed += 1
        except Exception as exc:
            self.metrics.handler_errors += 1
            logger.error("IPC handler error for %s: %s", event_type, exc)

    def _cleanup(self) -> None:
        """Закрыть socket и удалить socket файл."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError:
                pass
