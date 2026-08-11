"""
Fixtures для IPC тестов.

На macOS sun_path в sockaddr_un ограничен 104 байтами (включая \\0).
pytest tmp_path генерирует пути ~100-120 байт → AF_UNIX path too long.
Фикстура short_sock_dir создаёт директорию в /tmp (≈26 байт).
"""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def short_sock_dir():
    """Короткий временный каталог в /tmp для UDS socket файлов.

    macOS ограничивает sun_path до 104 байт (включая null terminator).
    /tmp/tmpXXXXXX/name.sock ≈ 26 байт — гарантированно в пределах лимита.
    """
    with tempfile.TemporaryDirectory(dir="/tmp") as td:
        yield Path(td)
