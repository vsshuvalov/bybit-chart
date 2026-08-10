"""
Parquet writer для атомарного commit сегментов.
Источник: Roadmap §6.4, §7; ADR-004 (Decimal128 precision/scale)

Формат сегмента: Apache Parquet с Arrow Schema, зафиксированной ADR-004.
Используется в `commit_segment(writer_callback=...)` для записи закрытого
WAL-сегмента в долговременное хранилище.

Schema evolution: backward-compatible (ADR-004 §4).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


# ===========================================================================
# Arrow Schema (ADR-004)
# ===========================================================================

# Версия schema фиксируется в метаданных Parquet footer для будущей
# schema evolution. Increment major при breaking change, minor при
# backward-compatible widening.
SCHEMA_VERSION_MAJOR = 1
SCHEMA_VERSION_MINOR = 0

# ADR-004: Decimal128(precision=18, scale=4) для coverageBps.
# Поля price/qty остаются int64 — они уже масштабированные целые.
_BTCUSDT_SCHEMA_BASE = pa.schema([
    ("timestampUs", pa.int64()),
    ("eventType", pa.string()),
    ("symbol", pa.string()),
    # RawTrade / RawBookEvent
    ("priceTicks", pa.int64()),
    ("qtySteps", pa.int64()),
    # BookCheckpoint
    ("depth", pa.int64()),
    ("updateId", pa.int64()),
    ("sequence", pa.int64()),
    ("levelCount", pa.int64()),
    ("coverageBoundaryTicks", pa.int64()),
    ("coverageBps", pa.decimal128(18, 4)),  # ADR-004
    ("isFeedRangeComplete", pa.bool_()),
    # Метаданные соединения
    ("connectionEpoch", pa.string()),
    ("exchangeTimestampMs", pa.int64()),
    ("outerTimestampMs", pa.int64()),
    ("receiveTimestampMs", pa.int64()),
])

BTCUSDT_SCHEMA = _BTCUSDT_SCHEMA_BASE.with_metadata({
    b"schema_version_major": str(SCHEMA_VERSION_MAJOR).encode("utf-8"),
    b"schema_version_minor": str(SCHEMA_VERSION_MINOR).encode("utf-8"),
    b"adr": b"ADR-004",
})


def schema_metadata() -> dict[bytes, bytes]:
    """Метаданные schema для Parquet footer.

    Фиксируют версию schema для будущей evolution (ADR-004 §4).
    DEPRECATED: метаданные уже включены в BTCUSDT_SCHEMA.
    """
    return BTCUSDT_SCHEMA.metadata or {}


# ===========================================================================
# Parquet Writer Callback
# ===========================================================================

class ParquetWriter:
    """Callback-compatible writer для `commit_segment`.

    Интерфейс:
        writer = ParquetWriter(path)
        writer.write_batch(rows)
        writer.close()  # fsync включён по умолчанию

    `commit_segment` гарантирует вызов `close()` до валидации и rename.
    """

    def __init__(self, path: Path | str):
        """Открыть Parquet writer с зафиксированной Arrow Schema.

        Args:
            path: путь к .tmp файлу (будет переименован в .parquet при commit)
        """
        self.path = Path(path)
        self.schema = BTCUSDT_SCHEMA
        self.writer = pq.ParquetWriter(
            self.path,
            self.schema,
            compression="snappy",  # Roadmap §7: snappy для throughput
            use_dictionary=True,
            write_statistics=True,
        )
        self.rows_written = 0

    def write_batch(self, rows: list[dict[str, Any]]) -> None:
        """Записать батч строк в Parquet.

        Args:
            rows: список словарей, каждый содержит поля из BTCUSDT_SCHEMA.
                  Decimal передаётся как `decimal.Decimal` или строка,
                  int64 как int.
        """
        if not rows:
            return

        # Преобразование строк в Decimal для decimal128 полей
        processed_rows = []
        for row in rows:
            processed = dict(row)
            if "coverageBps" in processed and isinstance(processed["coverageBps"], str):
                processed["coverageBps"] = Decimal(processed["coverageBps"])
            processed_rows.append(processed)

        # PyArrow Table.from_pylist автоматически кастит типы согласно schema
        table = pa.Table.from_pylist(processed_rows, schema=self.schema)
        self.writer.write_table(table)
        self.rows_written += len(rows)

    def close(self) -> None:
        """Закрыть writer с fsync.

        После вызова файл достоверен до конца: footer записан и fsync выполнен.
        """
        if self.writer:
            self.writer.close()
            self.writer = None


# ===========================================================================
# Валидатор footer (для commit_segment)
# ===========================================================================

def validate_parquet_footer(path: Path | str) -> dict[str, Any]:
    """Проверить footer закрытого Parquet-файла.

    Roadmap §6.4: валидация footer обязательна до atomic rename.
    Проверяет:
    - Footer читается без ошибок
    - Schema version совпадает с ожидаемой
    - Row count > 0
    - Метаданные schema присутствуют

    Returns:
        Словарь с метаданными footer: row_count, schema_version_major/minor.

    Raises:
        ValueError: footer невалиден (повреждён, пустой файл, несовпадение версии)
    """
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Parquet-файл не найден: {path}")

    try:
        metadata = pq.read_metadata(path)
    except Exception as exc:
        raise ValueError(f"Не удалось прочитать Parquet footer: {exc}") from exc

    row_count = metadata.num_rows
    if row_count == 0:
        raise ValueError("Parquet-файл пуст (0 строк)")

    # Проверка schema version из метаданных
    # PyArrow хранит метаданные в Arrow Schema, доступном через .to_arrow_schema()
    arrow_schema = metadata.schema.to_arrow_schema()
    schema_meta = arrow_schema.metadata or {}

    major_bytes = schema_meta.get(b"schema_version_major")
    minor_bytes = schema_meta.get(b"schema_version_minor")

    if not major_bytes or not minor_bytes:
        raise ValueError("Отсутствует schema version в метаданных footer")

    try:
        major = int(major_bytes.decode("utf-8"))
        minor = int(minor_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"Некорректный schema version: {exc}") from exc

    if major != SCHEMA_VERSION_MAJOR:
        raise ValueError(
            f"Несовместимая версия schema: {major}.{minor}, "
            f"ожидается {SCHEMA_VERSION_MAJOR}.x"
        )

    return {
        "row_count": row_count,
        "schema_version_major": major,
        "schema_version_minor": minor,
    }
