# ADR-004: Decimal128 Precision/Scale для Arrow/Parquet Schema

**Статус:** DRAFT  
**Владелец:** Claude Code (P1-S1-008)  
**Дата:** 2026-08-10  
**Зависимости:** ADR-012 (development/production hosts)  
**Блокирует:** P1-S1-004 (Parquet writer)

---

## Контекст

Roadmap §6.4 и §7 фиксируют Apache Parquet как формат сегмента для долговременного хранения записей WAL. PyArrow Schema требует явного указания `precision` и `scale` для каждого поля типа Decimal128.

Текущее состояние:
- `price` и `qty` хранятся как **int64** (`PriceTicks`, `QtySteps`) — масштабированные целые, уже зафиксированы
- Поля, требующие Decimal128: `coverageBps` (BookCheckpoint), потенциально `turnover`, `openInterest`, `fundingRate`, накопители VWAP (упомянуты в all-modules §5, но не реализованы в текущих схемах)

Проблема: без фиксации precision/scale для Decimal128 невозможно создать валидную Arrow Schema и записать Parquet-сегмент. P1-S1-004 заблокирован.

---

## Решение

### 1. Таблица полей с Decimal128

| Поле | Источник | Precision | Scale | Диапазон (примерный) | Обоснование |
|---|---|---|---|---|
| `coverageBps` | BookCheckpoint | 18 | 4 | 0.0000 – 10000.0000 bps | Basis points с 4 знаками: 0.01 bps = 0.0001%; максимум 100% = 10000 bps |

**Поля, не требующие Decimal128 (уже int64):**
- `priceTicks`, `qtySteps` — int64, precision не применим
- `timestampUs` — int64 (микросекунды с epoch)

**Поля, пока не реализованные (резерв для будущих ADR):**
- `turnoverQuote` — если вводится: Decimal128(28, 8) — произведение price × qty, требует больший precision
- `openInterestValue` — аналогично turnover
- `fundingRate` — Decimal128(18, 8) — ставка в долях, обычно ±0.01% = ±0.0001
- VWAP накопители — требуют отдельного анализа при реализации агрегатов

### 2. Overflow Policy

**Выбор:** **REJECT** — при выходе за границы диапазона бросать `FrameError` и отклонять запись.

**Обоснование:**
- **Saturate** (обрезка до min/max) — молчаливое искажение данных; недопустимо для финансовых записей
- **Wrap** (переполнение по модулю) — абсурдное поведение для цен/объёмов
- **Reject** — явный отказ с записью incident; позволяет операторам обнаружить проблему до накопления искажений

**Реализация:** проверка в `encode_frame` перед сериализацией; исключение `FrameError` с указанием поля и значения.

### 3. Arrow Schema (PyArrow код)

```python
import pyarrow as pa

BTCUSDT_SCHEMA = pa.schema([
    ("timestampUs", pa.int64()),
    ("eventType", pa.string()),
    ("priceTicks", pa.int64()),
    ("qtySteps", pa.int64()),
    ("coverageBps", pa.decimal128(18, 4)),  # BookCheckpoint
    # другие поля по мере реализации
])
```

**Примечание:** Schema является версионируемым артефактом. Изменения подчиняются правилам эволюции (см. §4).

### 4. Schema Evolution Rules

**Разрешённые изменения (backward-compatible):**
- Добавление нового поля (старые читатели игнорируют)
- Widening precision (например, `decimal128(18, 4)` → `decimal128(20, 4)`) — при условии, что старые данные укладываются в новый диапазон

**Запрещённые изменения (breaking):**
- Удаление поля
- Изменение типа (int64 → decimal128, decimal128 → string)
- Narrowing precision или scale (потеря точности или диапазона)
- Изменение scale при фиксированном precision (несовместимость представления)

**Процедура breaking change:**
- Новая версия schema с инкрементом major version
- Миграция существующих сегментов либо поддержка чтения обеих версий (ADR по мере необходимости)

---

## Граничные значения и тестирование

### coverageBps (Decimal128(18, 4))

| Случай | Значение | Ожидание |
|---|---|---|
| Минимум | 0.0000 | accept |
| Типичное | 25.1234 bps (0.251234%) | accept |
| Максимум | 10000.0000 bps (100%) | accept |
| За границей | 10000.0001 | **reject** (FrameError) |
| За границей | −0.0001 | **reject** (отрицательное coverage недопустимо) |

**Тесты:** добавить в `test_storage_offsets_and_frames.py` или новый `test_decimal128_overflow.py`:
- Проверка accept на границах
- Проверка reject за границами с `pytest.raises(FrameError, match="превышает диапазон")`

---

## Последствия

**Плюсы:**
- P1-S1-004 разблокирован — Parquet writer может создать валидную Arrow Schema
- Overflow policy **reject** предотвращает молчаливое искажение финансовых данных
- Schema evolution rules задают чёткий контракт для будущих изменений

**Минусы:**
- Widening precision требует пересчёт диапазонов и проверку совместимости со старыми сегментами
- Breaking change требует migration либо multi-version reader (отложено до реальной необходимости)

**Риски:**
- Если реальные значения Bybit API выходят за выбранные диапазоны → FrameError на production; требуется мониторинг и расширение диапазонов в новой версии schema
- Precision 18 может оказаться недостаточным для будущих полей (например, накопленный turnover за день); расширение до 28 потребует migration

---

## Альтернативы

1. **String вместо Decimal128** — отказ от типизации; запросы Arrow/Parquet теряют семантику числа
2. **Float64 в Parquet** — нарушает контракт "no binary float in persistent"; недопустимо (Roadmap §6.6)
3. **Overflow policy = saturate** — молчаливое искажение; неприемлемо для финансовых данных

Все отклонены.

---

## Статус и следующие шаги

**TODO до утверждения:**
- [ ] Подтвердить диапазоны `coverageBps` из реальных Bybit данных (если доступны примеры из API)
- [ ] Добавить граничные тесты в `tests/contracts/`
- [ ] Зафиксировать версионирование schema (major.minor) в коде PyArrow writer
- [ ] Документировать процедуру breaking change в отдельном ADR либо Runbook

**После утверждения:**
- P1-S1-004 может начаться: `WalPartition.atomic_commit(writer_callback)` получит реальный Parquet writer с валидной Schema
