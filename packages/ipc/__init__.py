"""
IPC Infrastructure для multi-process architecture (Roadmap §3).

Источник: Roadmap §3 (целевая архитектура, изолированные процессы)

Архитектура:
- Unix Domain Sockets для быстрой межпроцессной коммуникации
- Message bus для pub/sub между процессами
- Process discovery через socket files
- Graceful shutdown и reconnection

Процессы:
- collector-worker: WebSocket → WAL
- analytics-worker: Parquet → индикаторы
- api-server: REST API + WebSocket
- maintenance-worker: WAL → Parquet

IPC Patterns:
- Pub/Sub: collector публикует события → analytics подписывается
- Request/Reply: API запрашивает данные → analytics отвечает
- Health checks: периодический ping/pong

Roadmap требования:
- Crash isolation (падение analytics не убивает collector)
- Independent restart (можно перезапустить analytics без потери данных)
- Resource isolation (каждый процесс имеет свой memory limit)
"""

import asyncio
import json
import logging
import os
import socket
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class IPCMessage:
    """IPC message между процессами.

    Roadmap §3: standard envelope для всех IPC сообщений.
    """
    message_type: str  # "event", "request", "response", "health"
    payload: dict[str, Any]
    source: str  # process name
    correlation_id: str | None = None

    def to_bytes(self) -> bytes:
        """Serialize to bytes for socket transmission."""
        data = {
            "message_type": self.message_type,
            "payload": self.payload,
            "source": self.source,
            "correlation_id": self.correlation_id,
        }
        json_data = json.dumps(data).encode("utf-8")
        # Length prefix (4 bytes) + JSON data
        return struct.pack("!I", len(json_data)) + json_data

    @classmethod
    def from_bytes(cls, data: bytes) -> "IPCMessage":
        """Deserialize from bytes."""
        obj = json.loads(data.decode("utf-8"))
        return cls(
            message_type=obj["message_type"],
            payload=obj["payload"],
            source=obj["source"],
            correlation_id=obj.get("correlation_id"),
        )


class UDSServer:
    """Unix Domain Socket server для IPC.

    Roadmap §3: один сокет на процесс для приёма сообщений.
    """

    def __init__(self, socket_path: Path, process_name: str):
        """Initialize UDS server.

        Args:
            socket_path: путь к Unix socket файлу
            process_name: имя процесса (для логов)
        """
        self.socket_path = socket_path
        self.process_name = process_name
        self.server_socket: socket.socket | None = None
        self.handlers: dict[str, Callable[[IPCMessage], Any]] = {}
        self.running = False

    def register_handler(self, message_type: str, handler: Callable[[IPCMessage], Any]):
        """Зарегистрировать handler для message type.

        Args:
            message_type: тип сообщения
            handler: функция-обработчик
        """
        self.handlers[message_type] = handler

    async def start(self):
        """Запустить UDS server."""
        # Remove old socket file
        if self.socket_path.exists():
            self.socket_path.unlink()

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.bind(str(self.socket_path))
        self.server_socket.listen(5)
        self.server_socket.setblocking(False)

        self.running = True

        logger.info(f"{self.process_name}: UDS server started at {self.socket_path}")

        # Accept connections loop
        while self.running:
            try:
                # Accept new connection
                loop = asyncio.get_event_loop()
                client_socket, _ = await loop.sock_accept(self.server_socket)

                # Handle client in background task
                asyncio.create_task(self._handle_client(client_socket))

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"{self.process_name}: Error accepting connection: {exc}")
                await asyncio.sleep(0.1)

    async def _handle_client(self, client_socket: socket.socket):
        """Handle client connection."""
        try:
            loop = asyncio.get_event_loop()

            while True:
                # Read length prefix (4 bytes)
                length_data = await loop.sock_recv(client_socket, 4)
                if not length_data:
                    break

                message_length = struct.unpack("!I", length_data)[0]

                # Read message data
                message_data = b""
                while len(message_data) < message_length:
                    chunk = await loop.sock_recv(client_socket, message_length - len(message_data))
                    if not chunk:
                        break
                    message_data += chunk

                # Deserialize message
                message = IPCMessage.from_bytes(message_data)

                # Handle message
                if message.message_type in self.handlers:
                    try:
                        response = self.handlers[message.message_type](message)

                        # Send response if any
                        if response is not None:
                            response_msg = IPCMessage(
                                message_type="response",
                                payload=response,
                                source=self.process_name,
                                correlation_id=message.correlation_id,
                            )
                            await loop.sock_sendall(client_socket, response_msg.to_bytes())

                    except Exception as exc:
                        logger.error(f"{self.process_name}: Handler error: {exc}")

        except Exception as exc:
            logger.error(f"{self.process_name}: Client handler error: {exc}")
        finally:
            client_socket.close()

    async def stop(self):
        """Остановить UDS server."""
        self.running = False

        if self.server_socket:
            self.server_socket.close()

        if self.socket_path.exists():
            self.socket_path.unlink()

        logger.info(f"{self.process_name}: UDS server stopped")


class UDSClient:
    """Unix Domain Socket client для отправки сообщений.

    Roadmap §3: клиент для подключения к другим процессам.
    """

    def __init__(self, socket_path: Path, source_name: str):
        """Initialize UDS client.

        Args:
            socket_path: путь к Unix socket сервера
            source_name: имя этого процесса
        """
        self.socket_path = socket_path
        self.source_name = source_name
        self.client_socket: socket.socket | None = None

    async def connect(self):
        """Connect to UDS server."""
        self.client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client_socket.setblocking(False)

        loop = asyncio.get_event_loop()

        try:
            await loop.sock_connect(self.client_socket, str(self.socket_path))
            logger.info(f"{self.source_name}: Connected to {self.socket_path}")
        except Exception as exc:
            logger.error(f"{self.source_name}: Connection failed: {exc}")
            self.client_socket = None
            raise

    async def send_message(self, message: IPCMessage) -> IPCMessage | None:
        """Send message и получить response.

        Args:
            message: сообщение для отправки

        Returns:
            Response message или None
        """
        if not self.client_socket:
            await self.connect()

        loop = asyncio.get_event_loop()

        # Send message
        await loop.sock_sendall(self.client_socket, message.to_bytes())

        # Read response (if expected)
        if message.message_type == "request":
            # Read length prefix
            length_data = await loop.sock_recv(self.client_socket, 4)
            if not length_data:
                return None

            message_length = struct.unpack("!I", length_data)[0]

            # Read message data
            message_data = b""
            while len(message_data) < message_length:
                chunk = await loop.sock_recv(self.client_socket, message_length - len(message_data))
                if not chunk:
                    break
                message_data += chunk

            return IPCMessage.from_bytes(message_data)

        return None

    async def close(self):
        """Close connection."""
        if self.client_socket:
            self.client_socket.close()
            self.client_socket = None


class ProcessRegistry:
    """Registry для discovery других процессов.

    Roadmap §3: процессы регистрируются при старте и могут найти друг друга.
    """

    def __init__(self, registry_dir: Path):
        """Initialize process registry.

        Args:
            registry_dir: директория с socket files
        """
        self.registry_dir = registry_dir
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    def register_process(self, process_name: str, socket_path: Path):
        """Зарегистрировать процесс.

        Args:
            process_name: имя процесса
            socket_path: путь к его UDS socket
        """
        registry_file = self.registry_dir / f"{process_name}.socket"
        registry_file.write_text(str(socket_path))

        logger.info(f"Process registered: {process_name} → {socket_path}")

    def discover_process(self, process_name: str) -> Path | None:
        """Найти socket path для процесса.

        Args:
            process_name: имя процесса

        Returns:
            Path к socket или None
        """
        registry_file = self.registry_dir / f"{process_name}.socket"

        if registry_file.exists():
            socket_path = Path(registry_file.read_text().strip())
            if socket_path.exists():
                return socket_path

        return None

    def list_processes(self) -> list[str]:
        """Список всех зарегистрированных процессов.

        Returns:
            Список имён процессов
        """
        return [f.stem for f in self.registry_dir.glob("*.socket")]
