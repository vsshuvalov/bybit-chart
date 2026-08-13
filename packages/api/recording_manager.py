"""
Recording Manager - управление записью trades в базу данных.

Запускает отдельные процессы для каждого символа, которые:
1. Подключаются к Bybit WebSocket
2. Получают live trades
3. Записывают в PostgreSQL (таблица raw_trades)
"""

import asyncio
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


class RecordingManager:
    """Менеджер для управления процессами записи trades."""

    def __init__(self):
        self.active_recordings: Dict[str, subprocess.Popen] = {}
        self.recording_dir = Path("/opt/bybit-chart")
        self.venv_python = self.recording_dir / ".venv" / "bin" / "python"

    def start_recording(self, symbol: str) -> bool:
        """
        Запустить запись для символа.

        Args:
            symbol: Символ для записи (BTCUSDT)

        Returns:
            True если запись началась, False если уже идёт
        """
        if symbol in self.active_recordings:
            logger.warning(f"Recording already active for {symbol}")
            return False

        try:
            # Запускаем recording worker как отдельный процесс
            script_path = self.recording_dir / "workers" / "recording_worker.py"

            process = subprocess.Popen(
                [str(self.venv_python), str(script_path), symbol],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.recording_dir),
            )

            self.active_recordings[symbol] = process
            logger.info(f"Started recording for {symbol}, PID: {process.pid}")
            return True

        except Exception as e:
            logger.error(f"Failed to start recording for {symbol}: {e}")
            return False

    def stop_recording(self, symbol: str) -> bool:
        """
        Остановить запись для символа.

        Args:
            symbol: Символ

        Returns:
            True если запись остановлена, False если не было активной
        """
        if symbol not in self.active_recordings:
            logger.warning(f"No active recording for {symbol}")
            return False

        try:
            process = self.active_recordings[symbol]
            process.terminate()
            process.wait(timeout=5)
            del self.active_recordings[symbol]
            logger.info(f"Stopped recording for {symbol}")
            return True

        except subprocess.TimeoutExpired:
            # Force kill если не остановился
            process.kill()
            del self.active_recordings[symbol]
            logger.warning(f"Force killed recording for {symbol}")
            return True

        except Exception as e:
            logger.error(f"Failed to stop recording for {symbol}: {e}")
            return False

    def get_status(self, symbol: str) -> dict:
        """Получить статус записи для символа."""
        if symbol not in self.active_recordings:
            return {"recording": False}

        process = self.active_recordings[symbol]

        # Проверяем что процесс жив
        if process.poll() is not None:
            # Процесс завершился
            del self.active_recordings[symbol]
            return {"recording": False, "error": "Process died"}

        return {
            "recording": True,
            "pid": process.pid,
            "symbol": symbol,
        }

    def get_all_status(self) -> dict:
        """Получить статус всех активных записей."""
        statuses = {}

        # Очищаем мёртвые процессы
        dead_symbols = []
        for symbol, process in self.active_recordings.items():
            if process.poll() is not None:
                dead_symbols.append(symbol)

        for symbol in dead_symbols:
            del self.active_recordings[symbol]

        # Возвращаем статусы живых
        for symbol, process in self.active_recordings.items():
            statuses[symbol] = {
                "recording": True,
                "pid": process.pid,
            }

        return statuses


# Глобальный instance
recording_manager = RecordingManager()
