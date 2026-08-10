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
        self.base_dir = Path(base_dir)

    def read_range(
        self,
        symbol: str,
        start_ts: int,
        end_ts: int,
        *,
        limit: int | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Прочитать события в заданном временном диапазоне.

        Args:
            symbol: идентификатор partition (BTCUSDT)
            start_ts: начало диапазона (microseconds, inclusive)
            end_ts: конец диапазона (microseconds, exclusive)
            limit: максимальное количество rows (None = без ограничения)
            event_type: фильтр по eventType (None = все типы)

        Returns:
            Список событий (dict) в хронологическом порядке

        Raises:
            FileNotFoundError: partition или manifest не существует
            ValueError: некорректные параметры (start_ts > end_ts)
        """
        if start_ts >= end_ts:
            raise ValueError(f"start_ts ({start_ts}) должен быть < end_ts ({end_ts})")

        partition_dir = self.base_dir / symbol
        if not partition_dir.exists():
            raise FileNotFoundError(f"Partition не существует: {partition_dir}")

        manifest_path = partition_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest не существует: {manifest_path}")

        # 1. Читаем manifest
        manifest = Manifest(manifest_path)

        # 2. Находим релевантные сегменты
        # Roadmap §6.4: manifest хранит min/max_event_time_ms (если заполнено)
        # Для RawTrade мы не заполняем event_time (используем WAL offsets),
        # поэтому читаем все сегменты (будущая оптимизация — ADR для event_time)
        relevant_entries = manifest.sorted_entries()

        if not relevant_entries:
            logger.info(f"Нет сегментов для {symbol}")
            return []

        # 3. Читаем и фильтруем каждый сегмент
        all_rows = []
        for entry in relevant_entries:
            segment_path = partition_dir / entry.relative_path

            if not segment_path.exists():
                logger.warning(f"Сегмент не найден: {segment_path}, пропускаем")
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
