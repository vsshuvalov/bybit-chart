# NEXT

Обновлён: 2026-08-10T03:40:00+0700  
Project state: STAGE 1 IN PROGRESS  
Roadmap: `docs/specifications/source/BYBIT_MULTIPROCESS_PLATFORM_ROADMAP.md`  
SHA-256 roadmap: `191e78a88efa5be21343d0ceb25caef0727070a7d5d329cbd537ce46dd399930`  
Active stage/task: Stage 1 / следующая задача не начата  
Commits: `6edc666` Stage 0 → `ea25af6` P1-S1-001 → `c6e0d83` sync → текущий (P1-S1-002)

---

## Текущая цель

Stage 1 «Shared schemas и storage core» (Roadmap §19 Этап 1). Выполнены первые две атомарные задачи: контракты событий и storage core. Не выполнено: Parquet writer, PostgreSQL migrations, lock/SBOM.

---

## Текущее состояние

Реализовано и покрыто тестами:

| Компонент | Файл | Содержание |
|---|---|---|
| Числовые примитивы | `packages/numeric/primitives.py` | PriceTicks/QtySteps/Decimal128, запрет float |
| Схемы событий | `contracts/schemas.py` | RawTrade, RawBookEvent, RawRpiBookEvent, BookCheckpoint, RawLiquidation, GapMarker, RawEventEnvelope |
| WAL offsets | `packages/storage/offsets.py` | accepted/durable/closed/published/consumer + инварианты |
| Формат фрейма | `packages/storage/frames.py` | header 16B, length + CRC32, torn/corrupt detection |
| WAL | `packages/storage/wal.py` | append, bounded group commit, recovery, read_range |
| State machine | `packages/storage/segment_state.py` | ACTIVE→CLOSED_PENDING→PUBLISHING→COMMITTED→FAILED, lease, quarantine |
| Manifest | `packages/storage/manifest.py` | atomic replace, published_offset, партиционирование §6.5 |
| Atomic commit | `packages/storage/atomic_commit.py` | tmp→validate→fsync→rename→fsync(dir)→manifest→checkpoint |

Не реализовано: сервисы (`services/*` пусты), Parquet writer, PostgreSQL, frontend, execution, стратегии, AI.

Production-подключений к Bybit нет. API-ключей нет. Remote нет.

---

## Следующее атомарное действие

Ровно одна из задач `TODO.md`, в порядке приоритета:

1. **P1-S1-003** — dependency lock + SBOM (требование Roadmap §4, сейчас нарушено).
2. **P1-S1-004** — Parquet writer/validator поверх готового контракта `SegmentWriter`. Блокируется ADR-004 (Decimal128 precision/scale).
3. **P1-S1-005** — property-тесты на Hypothesis.

Рекомендую P1-S1-003: это формальное требование roadmap, невыполнение которого блокирует любой release gate, и оно не зависит от открытых ADR.

---

## Action log

```
2026-08-10T02:10 | P0-S0-001 | Прочитан промт CLAUDE_CODE_GREENFIELD_START_PROMPT.md | OK
2026-08-10T02:11 | P0-S0-001 | Найдены и хешированы 6 нормативных документов | SHA-256 зафиксированы
2026-08-10T02:12 | P0-S0-001 | Подтверждение пользователя: вариант 1 (git init в существующем каталоге) | CONFIRMED
2026-08-10T02:13 | P0-S0-001 | Прочитаны все 6 документов полностью (docx через textutil) | COMPLETE
2026-08-10T02:14 | P0-S0-001 | git init -b main | OK
2026-08-10T02:15 | P0-S0-001 | Спецификации скопированы, SHA-256 сверены | PASS 6/6
2026-08-10T02:16 | P0-S0-002 | Созданы CURRENT/TARGET/DECISIONS_PENDING/adr/REQUIREMENTS_TRACEABILITY | OK
2026-08-10T02:22 | P0-S0-003 | Созданы .gitignore, NEXT.md, TODO.md, README.md | OK
2026-08-10T02:24 | P0-S0-004 | Проверки Stage 0 выполнены | PASS
2026-08-10T02:40 | P0-S0-004 | Подтверждение пользователя на первый commit | CONFIRMED
2026-08-10T02:42 | P0-S0-004 | Первый commit 6edc666, 50 файлов | OK
2026-08-10T02:45 | P1-S1-001 | Создан .venv, установлены pydantic==2.11.1, pytest==8.3.5 | DEVIATION зафиксирован ниже
2026-08-10T02:50 | P1-S1-001 | contracts/schemas.py + packages/numeric/primitives.py | OK
2026-08-10T02:55 | P1-S1-001 | tests/contracts/test_contracts_and_numeric.py | PASS 55
2026-08-10T02:58 | P1-S1-001 | Commit ea25af6 | OK
2026-08-10T03:05 | P1-S1-002 | packages/storage/offsets.py + frames.py | OK
2026-08-10T03:10 | P1-S1-002 | Исправлен replay_safe_offset: разделены parquet-capable и wal-only consumers | DECISION
2026-08-10T03:15 | P1-S1-002 | packages/storage/wal.py, segment_state.py, manifest.py, atomic_commit.py | OK
2026-08-10T03:20 | P1-S1-002 | tests/contracts/test_storage_offsets_and_frames.py | PASS 30
2026-08-10T03:25 | P1-S1-002 | Тест нашёл баг: expire_lease терял generation → старый holder мог перезахватить сегмент | BUG FIXED
2026-08-10T03:26 | P1-S1-002 | Добавлено поле last_lease_generation; fencing floor сохраняется после снятия lease | OK
2026-08-10T03:30 | P1-S1-002 | tests/contracts/test_segment_state_and_manifest.py | PASS 34
2026-08-10T03:33 | P1-S1-002 | tests/fault/test_atomic_commit_crash_matrix.py | PASS 16
2026-08-10T03:36 | P1-S1-002 | tests/fault/test_wal_recovery.py | PASS 21
2026-08-10T03:38 | P1-S1-002 | Полный прогон pytest -q | PASS 156
```

---

## Tests and evidence

| Команда | Результат | Кол-во | Покрытие |
|---|---|---|---|
| `pytest -q` | PASS | 156 | весь проект |
| `pytest tests/contracts/test_contracts_and_numeric.py` | PASS | 55 | схемы событий, числовая модель |
| `pytest tests/contracts/test_storage_offsets_and_frames.py` | PASS | 30 | инварианты offsets, формат фрейма |
| `pytest tests/contracts/test_segment_state_and_manifest.py` | PASS | 34 | state machine, lease, manifest |
| `pytest tests/fault/test_atomic_commit_crash_matrix.py` | PASS | 16 | 4 точки crash, валидация, идемпотентность |
| `pytest tests/fault/test_wal_recovery.py` | PASS | 21 | torn/CRC recovery, group commit, live-tail ceiling |

SKIPPED: 0. FAILED: 0.

Не запускалось (нет кода): frontend Vitest/Playwright, integration/soak, performance, demo/testnet contract tests.

---

## Decisions and assumptions

| Решение | Источник | Последствия |
|---|---|---|
| Формат WAL-фрейма: header 16B (magic/version/flags/len/CRC32) | Roadmap §6.2 требует length+checksum, формат не фиксирует | Повреждение длины детектируется CRC отдельно от заголовка |
| `replay_safe_offset` = `published`, а не min(consumer) | §6.2: отставший consumer читает Parquet и не блокирует collector | WAL-only consumers указываются явно параметром |
| Формат файла сегмента не зафиксирован; writer — callback | §6.4 описывает протокол, не формат | PyArrow не является зависимостью Stage 1; реальный writer — P1-S1-004 |
| `last_lease_generation` сохраняется после снятия lease | §19 Этап 2: старый fencing token не пишет никогда | Просроченный writer не может перезахватить сегмент |
| Удаление сегментов не реализовано | §6.3: удаление только COMMITTED после retention checks | `may_delete()` даёт предикат; сама операция — задача maintenance |
| ASSUMPTION: `protocolVersion` — строка `major.minor` | §5.5 требует major bump, формат строки не задан | Уточнить в ADR-002 |

### DEVIATION: установка зависимостей

Stage 0 запрещал установку зависимостей. Stage 1 по Roadmap §19 Этап 1 требует `contracts` (Pydantic) и schema compatibility tests (pytest), поэтому в `.venv` установлены `pydantic==2.11.1` и `pytest==8.3.5`. Обе библиотеки прямо перечислены в Roadmap §4. `.venv/` исключён из git.

Нарушение, оставшееся открытым: Roadmap §4 требует lock-файл и SBOM для всех зависимостей — это задача P1-S1-003.

---

## Blockers and risks

| Блокер | Влияние | Проверки | Требуется |
|---|---|---|---|
| ADR-001…011 не утверждены | Формально Stage 1 идёт без утверждённых ADR | Зафиксированы в `docs/architecture/DECISIONS_PENDING.md` | Утверждение тимлидом |
| ADR-004 (Decimal128 precision/scale) | Блокирует P1-S1-004 Parquet writer | Числовая модель реализована, Arrow schema — нет | Решение по precision/scale |
| Нет lock-файла и SBOM | Нарушение Roadmap §4; блокирует release gate | Версии в `.venv` зафиксированы вручную | P1-S1-003 |
| Целевой хост не подтверждён (macOS vs Linux) | systemd vs launchd в `deploy/` | CONFLICT-004 | Ответ пользователя |
| Нет Hypothesis | Roadmap §4 требует property-тесты | Тесты только example-based | P1-S1-005 |

---

## Handoff

**Новые файлы этого блока:**

```
pyproject.toml
packages/storage/__init__.py
packages/storage/offsets.py
packages/storage/frames.py
packages/storage/wal.py
packages/storage/segment_state.py
packages/storage/manifest.py
packages/storage/atomic_commit.py
tests/fault/__init__.py
tests/fault/test_atomic_commit_crash_matrix.py
tests/fault/test_wal_recovery.py
tests/contracts/test_storage_offsets_and_frames.py
tests/contracts/test_segment_state_and_manifest.py
```

**Точка остановки:** P1-S1-002 закрыта, все тесты зелёные, изменения закоммичены.

**Безопасное продолжение:**
```bash
cd /Users/vs/Desktop/bybit-chart
source .venv/bin/activate
python3 -m pytest -q          # ожидается 156 passed
# затем взять одну задачу: P1-S1-003 (рекомендуется), P1-S1-004 или P1-S1-005
```
