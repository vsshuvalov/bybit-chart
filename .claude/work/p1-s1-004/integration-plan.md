"""
План интеграции WalPartition → Parquet (P1-S1-004 финализация)

## Текущее состояние

`WalPartition`:
- `append()` → пишет в ACTIVE .wal
- `commit()` → fsync, advance durable
- `roll_segment()` → закрывает ACTIVE, advance closed, но НЕ пишет Parquet

`ParquetWriter`:
- принимает список rows (dict), пишет в .parquet
- используется через `commit_segment(writer=..., validator=...)`

## Задача

Добавить метод `close_and_publish_segment(start_offset, end_offset)`:
1. Читает WAL-диапазон через `read_range(start, end)`
2. Конвертирует фреймы в rows для ParquetWriter
3. Вызывает `commit_segment(writer_callback, validator_callback)`
4. После успешного commit вызывает `mark_published(end_offset)`

## Проблема: конверсия Frame → row

`read_range()` возвращает `list[Frame]` с полем `payload: bytes`.
ParquetWriter ожидает `list[dict]` с полями из BTCUSDT_SCHEMA.

**Решение:** payload содержит сериализованное событие (RawTrade/BookCheckpoint).
Нужен десериализатор `payload → dict` для передачи в ParquetWriter.

Но события имеют разные схемы (RawTrade ≠ BookCheckpoint), а BTCUSDT_SCHEMA
единая. Это блокер: нужен либо multi-table Parquet (по типу события),
либо sparse schema с опциональными полями.

## Упрощение для MVP

Вместо реальной десериализации событий записываем минимальный stub:
- `timestampUs` = offset фрейма
- `eventType` = "raw_frame"
- `symbol` = partition_id
- Остальные поля = default/null

Это позволяет проверить интеграцию commit_segment + ParquetWriter + manifest,
отложив полную десериализацию событий до Stage 2 (когда появится
RawEventReader и реальные события из Bybit).

## Реализация

1. Добавить `close_and_publish_segment(start_offset, end_offset)` в WalPartition
2. Внутри: read_range → stub rows → ParquetWriter → commit_segment
3. Тест: append records → roll → close_and_publish → проверка .parquet
4. Интеграционный тест с manifest (отложен, т.к. manifest пока mock)

## Файлы

- `packages/storage/wal.py` — добавить метод
- `tests/contracts/test_wal_parquet_integration.py` — новый файл
