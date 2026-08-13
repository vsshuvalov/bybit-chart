"""
ParquetReader для чтения опубликованных сегментов (Stage 3 / P3-S3-001).

Источник: Roadmap §7 (Query & Aggregation)
Архитектура: manifest.json → find segments → read .parquet → filter → merge

Использование:
    reader = ParquetReader(base_dir="/data")
    events = reader.read_range(
        symbol="BTCUSDT",
        start_ts=1786372648000000,
        end_ts=1786372650000000,
    )
"""

import logging
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pyarrow.compute as pc

from packages.storage import Manifest, ManifestEntry

logger = logging.getLogger(__name__)


class ParquetReader:
    """Reader для чтения Parquet сегментов через manifest.

    Roadmap §7: Query должен использовать manifest.json для поиска
    релевантных сегментов вместо сканирования файловой системы.
    """

    def __init__(self, base_dir: Path | str):
        """Инициализировать reader.

        Args:
            base_dir: базовый каталог с partition dirs (symbol subdirectories)
        """
        self.base_dir = Path(base_dir).resolve()

    def _safe_child(self, *parts: str) -> Path:
        """Validate that joined path stays within base_dir (path traversal protection).

        Args:
            parts: path components to join

        Returns:
            Resolved path within base_dir

        Raises:
            ValueError: if path escapes base_dir
        """
        candidate = self.base_dir.joinpath(*parts).resolve()

        try:
            candidate.relative_to(self.base_dir)
        except ValueError as exc:
            raise ValueError(f"Path escapes configured data directory: {candidate}") from exc

        return candidate

    def read_range(
        self,
        symbol: str,
        start_ts: int,
        end_ts: int,
        *,
        limit: int | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read events in specified time range.

        Args:
            symbol: partition identifier (BTCUSDT, ETHUSDT, XRPUSDT only)
            start_ts: start of range (microseconds, inclusive)
            end_ts: end of range (microseconds, exclusive)
            limit: max number of rows (None = no limit)
            event_type: filter by eventType (None = all types)

        Returns:
            List of events (dict) in chronological order

        Raises:
            FileNotFoundError: partition or manifest does not exist
            ValueError: invalid parameters (start_ts > end_ts, path traversal)
        """
        if start_ts >= end_ts:
            raise ValueError(f"start_ts ({start_ts}) must be < end_ts ({end_ts})")

        # Path traversal protection
        partition_dir = self._safe_child(symbol)
        if not partition_dir.exists():
            raise FileNotFoundError(f"Partition does not exist: {symbol}")

        manifest_path = self._safe_child(symbol, "manifest.json")
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest does not exist: {symbol}/manifest.json")

        # 1. Read manifest
        manifest = Manifest(manifest_path)

        # 2. Find relevant segments
        # Roadmap §6.4: manifest stores min/max_event_time_ms (if populated)
        # For RawTrade we don't populate event_time (use WAL offsets),
        # so read all segments (future optimization — ADR for event_time)
        all_entries = manifest.sorted_entries()

        # OPTIMIZATION: for last N minutes read only last 100 segments
        # (each segment ~1 minute of data at 1000 trades/min)
        # Это временное решение до реализации event_time индексации
        if len(all_entries) > 100:
            import time
            now_us = int(time.time() * 1_000_000)
            # Если запрашиваем данные за последний час, берём только последние 100 сегментов
            if end_ts > now_us - (3600 * 1_000_000):
                relevant_entries = all_entries[-100:]
                logger.debug(f"Optimized: reading last 100/{len(all_entries)} segments for recent data")
            else:
                relevant_entries = all_entries
        else:
            relevant_entries = all_entries

        if not relevant_entries:
            logger.info(f"Нет сегментов для {symbol}")
            return []

        # 3. Read and filter each segment
        all_rows = []
        for entry in relevant_entries:
            segment_path = self._safe_child(symbol, entry.relative_path)

            if not segment_path.exists():
                logger.warning(f"Segment not found: {entry.relative_path}, skipping")
                continue

            try:
                rows = self._read_segment(
                    segment_path=segment_path,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    event_type=event_type,
                )
                all_rows.extend(rows)

                # Early exit если достигли limit
                if limit and len(all_rows) >= limit:
                    break

            except Exception as exc:
                logger.error(f"Ошибка чтения {segment_path}: {exc}", exc_info=True)
                continue

        # 4. Сортируем по timestampUs (сегменты могут перекрываться)
        all_rows.sort(key=lambda r: r["timestampUs"])

        # 5. Применяем limit
        if limit:
            all_rows = all_rows[:limit]

        logger.info(
            f"Прочитано {len(all_rows)} событий для {symbol} "
            f"в диапазоне [{start_ts}, {end_ts})"
        )

        return all_rows

    def _read_segment(
        self,
        segment_path: Path,
        start_ts: int,
        end_ts: int,
        event_type: str | None,
    ) -> list[dict[str, Any]]:
        """Прочитать и отфильтровать один сегмент.

        Args:
            segment_path: путь к .parquet файлу
            start_ts, end_ts: временной диапазон (microseconds)
            event_type: фильтр по eventType

        Returns:
            Список rows (dict) из сегмента
        """
        # Фильтр через PyArrow compute для эффективности
        filters = [
            (pc.field("timestampUs") >= start_ts),
            (pc.field("timestampUs") < end_ts),
        ]

        if event_type:
            filters.append(pc.field("eventType") == event_type)

        # Комбинируем фильтры через AND
        combined_filter = filters[0]
        for f in filters[1:]:
            combined_filter = combined_filter & f

        # Читаем с фильтром
        table = pq.read_table(segment_path, filters=combined_filter)

        # Конвертируем в list[dict]
        return table.to_pylist()

    def list_symbols(self) -> list[str]:
        """Получить список доступных symbols (partition directories).

        Returns:
            Список symbol names

        Пример:
            reader = ParquetReader("/data")
            symbols = reader.list_symbols()  # ["BTCUSDT", "ETHUSDT"]
        """
        if not self.base_dir.exists():
            return []

        symbols = []
        for item in self.base_dir.iterdir():
            if item.is_dir() and (item / "manifest.json").exists():
                symbols.append(item.name)

        return sorted(symbols)
