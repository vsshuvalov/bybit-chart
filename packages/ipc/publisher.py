"""
IPC Publisher — non-blocking SOCK_DGRAM sender.

Источник: ADR-016, Roadmap §5.1 (Этап 2)

Принцип:
    - Non-blocking: если receiver buffer полон → drop (не блокировать collector)
    - Best-effort: analytics rebuilds от WAL при потерях
    - Метрики: published / backpressure_drops / errors

Usage:
    publisher = IPCPublisher(socket_path="/tmp/bybit-analytics.sock")
    ok = publisher.publish(raw_trade)
    if not ok:
        metrics.increment("ipc_drop")
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Maximum datagram size (UDP-style limit для SOCK_DGRAM over UDS)
_MAX_DGRAM = 65507


@dataclass
class PublisherMetrics:
    """Счётчики для мониторинга publisher."""
    published: int = 0
    backpressure_drops: int = 0
    oversized_drops: int = 0
    errors: int = 0
    connect_errors: int = 0

    @property
    def total_drops(self) -> int:
        return self.backpressure_drops + self.oversized_drops

    def to_dict(self) -> dict[str, int]:
        return {
            "published": self.published,
            "backpressure_drops": self.backpressure_drops,
            "oversized_drops": self.oversized_drops,
            "errors": self.errors,
            "connect_errors": self.connect_errors,
        }


class IPCPublisher:
    """Non-blocking IPC publisher через Unix Domain Socket SOCK_DGRAM.

    Collector использует этот класс для публикации событий в analytics.
    При переполнении буфера приёмника — событие дропается (не блокирует collector).

    Важно: analytics всегда может восстановить state из WAL.
    IPC = best-effort optimization, не source of truth.

    Usage:
        publisher = IPCPublisher("/tmp/bybit-analytics.sock")
        ok = publisher.publish(trade)
        # ok=True → доставлено, ok=False → dropped (backpressure/error)
    """

    def __init__(
        self,
        socket_path: str | Path,
        source_name: str = "collector",
    ):
        """Инициализировать publisher.

        Args:
            socket_path: путь к UDS socket подписчика
            source_name: имя процесса-отправителя (для envelope)
        """
        self.socket_path = str(socket_path)
        self.source_name = source_name
        self.metrics = PublisherMetrics()
        self._sock: socket.socket | None = None

    def publish(self, event: Any) -> bool:
        """Отправить событие non-blocking.

        Args:
            event: объект с методом model_dump() (Pydantic model)
                   или dict

        Returns:
            True если отправлено, False если dropped
        """
        if self._sock is None:
            self._sock = self._create_socket()

        try:
            payload = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            envelope = {
                "version": 1,
                "event_type": type(event).__name__,
                "source": self.source_name,
                "timestamp_us": int(time.time() * 1_000_000),
                "payload": payload,
            }
            msg = json.dumps(envelope, default=str).encode("utf-8")

            if len(msg) > _MAX_DGRAM:
                self.metrics.oversized_drops += 1
                logger.warning(
                    "IPC drop: oversized message %d bytes for %s",
                    len(msg), type(event).__name__,
                )
                return False

            self._sock.sendto(msg, self.socket_path)
            self.metrics.published += 1
            return True

        except BlockingIOError:
            # Receiver buffer full — drop
            self.metrics.backpressure_drops += 1
            return False

        except FileNotFoundError:
            # Subscriber socket не существует — drop silently
            self.metrics.connect_errors += 1
            return False

        except OSError as exc:
            self.metrics.errors += 1
            logger.debug("IPC publish error: %s", exc)
            return False

    def publish_raw(self, event_type: str, payload: dict) -> bool:
        """Отправить сырой payload без Pydantic model.

        Args:
            event_type: тип события (для envelope)
            payload: данные события

        Returns:
            True если отправлено, False если dropped
        """
        if self._sock is None:
            self._sock = self._create_socket()

        try:
            envelope = {
                "version": 1,
                "event_type": event_type,
                "source": self.source_name,
                "timestamp_us": int(time.time() * 1_000_000),
                "payload": payload,
            }
            msg = json.dumps(envelope, default=str).encode("utf-8")

            if len(msg) > _MAX_DGRAM:
                self.metrics.oversized_drops += 1
                return False

            self._sock.sendto(msg, self.socket_path)
            self.metrics.published += 1
            return True

        except BlockingIOError:
            self.metrics.backpressure_drops += 1
            return False

        except (FileNotFoundError, OSError) as exc:
            self.metrics.connect_errors += 1
            logger.debug("IPC publish_raw error: %s", exc)
            return False

    def close(self) -> None:
        """Закрыть socket."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            finally:
                self._sock = None

    def __del__(self) -> None:
        self.close()

    @staticmethod
    def _create_socket() -> socket.socket:
        """Создать non-blocking SOCK_DGRAM socket."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.setblocking(False)
        return sock
