"""
Тесты IPC Infrastructure (Roadmap §3).

Проверяют: UDSServer, UDSClient, ProcessRegistry, IPCMessage.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from packages.ipc import IPCMessage, ProcessRegistry, UDSClient, UDSServer

pytestmark = pytest.mark.contract


class TestIPCMessage:
    """Тесты IPCMessage serialization."""

    def test_message_to_bytes(self):
        """to_bytes() сериализует сообщение."""
        msg = IPCMessage(
            message_type="event",
            payload={"symbol": "BTCUSDT", "price": 65000},
            source="collector",
            correlation_id="test_123",
        )

        data = msg.to_bytes()

        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_message_from_bytes(self):
        """from_bytes() десериализует сообщение."""
        original = IPCMessage(
            message_type="event",
            payload={"symbol": "BTCUSDT", "price": 65000},
            source="collector",
            correlation_id="test_123",
        )

        data = original.to_bytes()
        # Skip length prefix (4 bytes)
        restored = IPCMessage.from_bytes(data[4:])

        assert restored.message_type == "event"
        assert restored.payload["symbol"] == "BTCUSDT"
        assert restored.payload["price"] == 65000
        assert restored.source == "collector"
        assert restored.correlation_id == "test_123"

    def test_message_roundtrip(self):
        """Roundtrip serialization корректен."""
        original = IPCMessage(
            message_type="request",
            payload={"query": "get_data"},
            source="api",
        )

        data = original.to_bytes()
        restored = IPCMessage.from_bytes(data[4:])

        assert restored.message_type == original.message_type
        assert restored.payload == original.payload
        assert restored.source == original.source


class TestProcessRegistry:
    """Тесты ProcessRegistry."""

    def test_register_process(self):
        """register_process() создаёт registry file."""
        with tempfile.TemporaryDirectory() as td:
            registry = ProcessRegistry(Path(td))
            socket_path = Path(td) / "test.sock"

            registry.register_process("test_process", socket_path)

            registry_file = Path(td) / "test_process.socket"
            assert registry_file.exists()
            assert registry_file.read_text().strip() == str(socket_path)

    def test_discover_process(self):
        """discover_process() находит зарегистрированный процесс."""
        with tempfile.TemporaryDirectory() as td:
            registry = ProcessRegistry(Path(td))
            socket_path = Path(td) / "test.sock"
            socket_path.touch()  # Create socket file

            registry.register_process("test_process", socket_path)

            discovered = registry.discover_process("test_process")
            assert discovered == socket_path

    def test_discover_nonexistent_process(self):
        """discover_process() возвращает None для несуществующего процесса."""
        with tempfile.TemporaryDirectory() as td:
            registry = ProcessRegistry(Path(td))

            discovered = registry.discover_process("nonexistent")
            assert discovered is None

    def test_list_processes(self):
        """list_processes() возвращает все зарегистрированные процессы."""
        with tempfile.TemporaryDirectory() as td:
            registry = ProcessRegistry(Path(td))

            registry.register_process("collector", Path(td) / "collector.sock")
            registry.register_process("analytics", Path(td) / "analytics.sock")

            processes = registry.list_processes()
            assert "collector" in processes
            assert "analytics" in processes
            assert len(processes) == 2


class TestUDSServerClient:
    """Интеграционные тесты UDS server/client."""

    @pytest.mark.asyncio
    async def test_server_starts_and_stops(self):
        """UDSServer запускается и останавливается."""
        with tempfile.TemporaryDirectory() as td:
            socket_path = Path(td) / "test.sock"
            server = UDSServer(socket_path, "test_server")

            # Start server in background
            server_task = asyncio.create_task(server.start())

            # Wait for startup
            await asyncio.sleep(0.1)

            assert socket_path.exists()

            # Stop server
            await server.stop()
            server_task.cancel()

            try:
                await server_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_client_sends_message(self):
        """UDSClient отправляет сообщение на сервер."""
        with tempfile.TemporaryDirectory() as td:
            socket_path = Path(td) / "test.sock"
            server = UDSServer(socket_path, "test_server")

            received_messages = []

            def handler(msg: IPCMessage):
                received_messages.append(msg)

            server.register_handler("event", handler)

            # Start server
            server_task = asyncio.create_task(server.start())
            await asyncio.sleep(0.1)

            # Connect client and send message
            client = UDSClient(socket_path, "test_client")
            await client.connect()

            message = IPCMessage(
                message_type="event",
                payload={"test": "data"},
                source="test_client",
            )

            await client.send_message(message)
            await asyncio.sleep(0.1)

            # Cleanup
            await client.close()
            await server.stop()
            server_task.cancel()

            try:
                await server_task
            except asyncio.CancelledError:
                pass

            # Verify
            assert len(received_messages) == 1
            assert received_messages[0].payload["test"] == "data"

    @pytest.mark.asyncio
    async def test_request_response_pattern(self):
        """Request/response pattern работает."""
        with tempfile.TemporaryDirectory() as td:
            socket_path = Path(td) / "test.sock"
            server = UDSServer(socket_path, "test_server")

            def request_handler(msg: IPCMessage):
                # Return response
                return {"result": "success", "echo": msg.payload}

            server.register_handler("request", request_handler)

            # Start server
            server_task = asyncio.create_task(server.start())
            await asyncio.sleep(0.1)

            # Send request
            client = UDSClient(socket_path, "test_client")
            await client.connect()

            request = IPCMessage(
                message_type="request",
                payload={"query": "get_data"},
                source="test_client",
                correlation_id="req_123",
            )

            response = await client.send_message(request)

            # Cleanup
            await client.close()
            await server.stop()
            server_task.cancel()

            try:
                await server_task
            except asyncio.CancelledError:
                pass

            # Verify response
            assert response is not None
            assert response.message_type == "response"
            assert response.payload["result"] == "success"
            assert response.payload["echo"]["query"] == "get_data"
            assert response.correlation_id == "req_123"
