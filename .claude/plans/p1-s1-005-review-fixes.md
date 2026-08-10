# P1-S1-005: исправления по ревью + регистрация P1-S1-008/009

## Проверено своими командами (не со слов)

| Факт | Проверка | Результат |
|---|---|---|
| `os.fsync` после `truncate` | `grep 'os.fsync\|import os' tests/fault/test_property_wal_truncation.py` | `os` не импортирован, fsync нет — утверждение в docstring ложно |
| Тест `MAX_PAYLOAD_BYTES` | `grep -rn MAX_PAYLOAD_BYTES tests/` | единственное вхождение — сам комментарий; теста нет |
| Немаркированная выборка | `pytest -m "not contract and not fault and not property"` | `exit=5` (no tests collected), а не 0 |
| `scan_frames` принимает `start_offset` | `packages/storage/frames.py:136` | принимает; аргумент `start` в тесте не передаётся |
| P1-S1-004 приписан OPEN-005 | grep по 5 файлам | README:198, NEXT:53, NEXT:206, NEXT:210, TRACEABILITY:169, TODO:134, DECISIONS_PENDING:151/161 |

## 1. fsync после truncate (дефект №1)

`tests/fault/test_property_wal_truncation.py`: 7 мест делают `handle.truncate(cut)` без fsync.

Ввести helper рядом с `write_records`, повторяющий последовательность прод-кода
(`packages/storage/wal.py:215-219`):

```python
def truncate_segment(segment: Path, cut: int) -> None:
    """Обрезать сегмент с fsync — как это делает recovery в проде.

    Без fsync тест проверял бы только состояние page cache: заявленная
    в docstring проверка durability не выполнялась бы.
    """
    with open(segment, "r+b") as handle:
        handle.truncate(cut)
        handle.flush()
        os.fsync(handle.fileno())
```

Заменить все 7 мест на `truncate_segment(segment, cut)`; добавить `import os`.

## 2. Независимая модель для offsets (дефект №2)

Сейчас `test_any_sequence_preserves_invariants` принимает любой
`OffsetInvariantError` → мутант «всегда отклонять» проходит.

Вывести оракул из §6.2 независимо от кода:

| Метод | Успех тогда и только тогда |
|---|---|
| `advance_accepted(v)` | `v >= accepted` |
| `advance_durable(v)` | `v >= durable and v <= accepted` |
| `advance_closed(v)` | `v >= closed and v <= durable` |
| `advance_published(v)` | `v >= published and v <= closed` |

Переписать тест: `assert succeeded == expected_success` — тогда «всегда
отклонять» и «всегда принимать» оба падают.

Плюс параметризованный тест границ (`v = cur-1, cur, ceiling, ceiling+1`) —
детерминированное покрытие обеих ветвей, без надежды на генератор.
Значения операций сузить до `0..64`, чтобы окна успеха попадались часто.

## 3. exit 5 вместо зелёного (дефект №6)

Заменить shell-проверку на контрактный тест в `test_dependency_lock.py`:
каждый модуль `tests/**/test_*.py` обязан объявлять `pytestmark`.
Это проверяется механически, а не интерпретацией кода возврата.
В журналах записать команду как `EXPECTED exit 5 (no tests collected)`.

## 4. Два дефекта качества (дефект №7)

- Комментарий про `MAX_PAYLOAD_BYTES` (стр. 41-44): теста нет → либо написать
  его, либо убрать утверждение. Напишу тест: `encode_frame` с
  `MAX_PAYLOAD_BYTES+1` → `FrameError`, и `decode_frame` с подменённым
  `payload_len` выше лимита → `CorruptFrameError`. Комментарий поправить.
- `start` в `test_scan_offsets_are_frame_boundaries` не используется: убрать
  аргумент, а вместо него добавить отдельный тест `scan_frames(buffer, start)`
  от валидной границы фрейма — свойство, а не мёртвый код.

## 5. Синхронизация документации (дефект №3)

| Файл:строка | Что сейчас | Правка |
|---|---|---|
| NEXT.md:14 | «Не выполнено: … property-тесты» | закрыто 4 задачи; property готовы |
| NEXT.md:43 | workflow «untracked» | закоммичен в `29b7a66`; не запускался — остаётся |
| NEXT.md:163 | verifier «9 пакетов» | 11 пакетов |
| NEXT.md:175 | «ci.yml untracked» | убрать untracked |
| README.md:200 | «Property-тесты не написаны — P1-S1-005» | закрыта |
| README.md:127 | «трассировка 63 требований» | 68 |
| CURRENT.md:23 | «67 требований» | 68 |
| CURRENT.md:58 | «Property-тесты не написаны» | закрыта |
| CURRENT.md:62-69 | commit-лист до `d479e04` | добавить `29b7a66` |
| TODO.md:202 | P1-S1-003: «9 пакетов» | пометить историческим: «9 на момент закрытия; 11 после P1-S1-005» |
| TODO.md:256 | «Hypothesis не установлен» | перевести в прошедшее время (состояние до задачи) |

`REQUIREMENTS_TRACEABILITY.md` уже в порядке (68, REQ-068 DONE) — не трогаю.

## 6. Переатрибуция блокеров (решение тимлида)

OPEN-005 блокирует Linux production lock/release, но **не** разработку Parquet
writer на macOS. Реальный блокер P1-S1-004 — только ADR-004.

Правки: TODO:134, NEXT:53, NEXT:206, NEXT:210, README:198,
DECISIONS_PENDING:151/161 (заголовок «REQUIRED до P1-S1-004 и ADR-005» →
«REQUIRED до P1-S1-006 и production release»), TRACEABILITY:169 (REQ-067
блокирует P1-S1-006 и production release, не P1-S1-004).

## 7. Новые задачи

- **P1-S1-008 | P0 | TODO** — подготовка и утверждение ADR-004. Deliverable:
  таблица полей, диапазоны, precision/scale, overflow policy, правила schema
  evolution. Не заблокирована. Блокирует P1-S1-004.
- **P1-S1-009 | P0 | BLOCKED (ADR-005)** — PostgreSQL migrations. Отмечено
  тимлидом как пропущенная обязательная задача Stage 1.

## Проверка

1. `.venv/bin/python -m pytest -q` без активации venv и после — совпадение.
2. `-m property`, `-m contract`, `-m fault`, сумма = total.
3. Мутационная матрица, каждая мутация обязана уронить тест:

| Мутация | Ожидание |
|---|---|
| снят CRC | падает |
| `last_valid_offset=len(buffer)` | падает |
| снят `durable<=accepted` | падает (модель ловит) |
| **все `advance_*` всегда бросают** | **падает — новый оракул** |
| **`validate()` всегда пустой** | **падает** |
| `truncate` без реального усечения | падает |

4. `git diff packages/` пуст после мутаций.
5. `verify_dependencies.py` / `--check` / `--release` → 0 / 0 / 1.
6. `git diff --check` чисто; `pip check` чисто.
7. Артефакты не перегенерирую: состав окружения не меняется.

## Commit

Только после зелёного прогона, сообщением тимлида:
`Stage 1 / P1-S1-005: add Hypothesis property tests for WAL and offsets`
