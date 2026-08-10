# NEXT

- Обновлён: 2026-08-10T18:10:00+0700
- Project state: STAGE 1 IN PROGRESS
- Roadmap: `docs/specifications/source/BYBIT_MULTIPROCESS_PLATFORM_ROADMAP.md`
- SHA-256 roadmap: `191e78a88efa5be21343d0ceb25caef0727070a7d5d329cbd537ce46dd399930`
- Active stage/task: Stage 1 / P1-S1-003 — исправления по ревью внесены, ожидает повторной проверки
- Commits: `6edc666` Stage 0 → `ea25af6` P1-S1-001 → `c6e0d83` sync → `d479e04` P1-S1-002 → текущий блок не закоммичен

---

## Текущая цель

Stage 1 «Shared schemas и storage core» (Roadmap §19 Этап 1). Закрыты три атомарные задачи: контракты событий, storage core, dependency lock/SBOM. Не выполнено: Parquet writer, PostgreSQL migrations, property-тесты, Linux-артефакты.

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
| Dependency lock | `deploy/dependencies/darwin-arm64/requirements.lock` | 9 пакетов, SHA-256, роль `development` |
| SBOM | `deploy/dependencies/darwin-arm64/sbom.cyclonedx.json` | CycloneDX 1.5, purl, лицензии, граф связей |
| Генератор артефактов | `deploy/gen_dependency_artifacts.py` | снятие с окружения, гард против production на Darwin |
| Верификатор | `deploy/verify_dependencies.py` | offline-проверка, `--strict-platform`, `--release`, `--pending-ok` |
| CI (только конфигурация) | `.github/workflows/ci.yml` | Linux parity-тесты, macOS dev-контур, dependency gate, release gate. **Не запускалась**: покрыт тестами контракт файла, не его исполнение |

Не реализовано: сервисы (`services/*` пусты), Parquet writer, PostgreSQL, frontend, execution, стратегии, AI.

Production-подключений к Bybit нет. API-ключей нет. Remote нет.

`.github/workflows/ci.yml` **не закоммичен и ни разу не запускался**: файл untracked, remote отсутствует. Проверены только его синтаксис (YAML разобран парсером) и контракт (тесты требуют Linux-джоб, прогон `tests/fault`, вызов верификатора, установку из lock до проверки). Фактическое исполнение на runner переносится в P1-S1-007.

---

## Следующее атомарное действие

**Сейчас:** повторная проверка P1-S1-003 и commit. Тимлид зафиксировал: P1-S1-005 берётся только после закрытия и commit P1-S1-003. Новую задачу не начинать.

Далее, в порядке приоритета:

1. **P1-S1-005** — property-тесты на Hypothesis. Не блокируется ничем. Рекомендована тимлидом как следующая.
2. **P1-S1-007** — Linux parity: первый реальный прогон CI, crash-matrix на ext4/XFS, `systemd`, performance, soak. Требует remote и Linux-хоста.
3. **P1-S1-004** — Parquet writer. Блокируется ADR-004 **и** OPEN-005 (у PyArrow бинарные колёса).
4. **P1-S1-006** — Linux dependency artifacts. Блокируется OPEN-005.

Требуется решение владельца: **OPEN-005** — архитектура production-хоста и точная версия Python. Рекомендованный тимлидом default — Linux x86_64 и CPython 3.13.7; остаётся `OPEN` до подтверждения железа. Без решения не двигаются P1-S1-004, P1-S1-006 и ADR-005.

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
2026-08-10T03:40 | P1-S1-002 | Commit d479e04 | OK
2026-08-10T16:52 | P1-S1-003 | requirements.in, генератор, верификатор, SBOM, tests/contracts/test_dependency_lock.py | OK
2026-08-10T16:54 | P1-S1-003 | Генератор поймал расхождение: свежее разрешение даёт typing-inspection 0.4.3, окружение 0.4.2 | DECISION: lock снимается с окружения
2026-08-10T17:05 | P1-S1-003 | Ревизия перед commit: .gitignore шаблон *.lock скрывал requirements.lock из git | BUG FOUND
2026-08-10T17:10 | P1-S1-003 | Решение владельца: dev macOS, prod Linux+systemd, архитектура и версия Python OPEN | CONFIRMED
2026-08-10T17:15 | P1-S1-003 | .gitignore: *.lock → *.runtime.lock + .lock + явный !deploy/dependencies/**/requirements.lock | FIXED
2026-08-10T17:20 | P1-S1-003 | Введены роль артефакта и раскладка по платформам; генератор отказывает на --role production под Darwin | OK
2026-08-10T17:25 | P1-S1-003 | Верификатор: --release (роль+строгая платформа), --pending-ok (PENDING вместо ошибки) | OK
2026-08-10T17:28 | P1-S1-003 | Артефакты перегенерированы в deploy/dependencies/darwin-arm64/; старые файлы из корня удалены | OK
2026-08-10T17:30 | P1-S1-003 | ADR-012 создан, CONFLICT-004 закрыт, остаток вынесен в OPEN-005 | OK
2026-08-10T17:33 | P1-S1-003 | .github/workflows/ci.yml: Linux parity, macOS dev, dependency gate, release gate | OK
2026-08-10T17:36 | P1-S1-003 | Тесты роли, release gate и CI-контракта | PASS 91 в файле
2026-08-10T17:38 | P1-S1-003 | Полный прогон pytest -q | PASS 247
2026-08-10T17:50 | P1-S1-003 | Ревью тимлида: NO-GO на commit, 6 несоответствий | REJECTED
2026-08-10T17:52 | P1-S1-003 | Тест запускал системный python3 вместо sys.executable → 1 failed без активации venv | BUG FIXED
2026-08-10T17:56 | P1-S1-003 | --check сравнивал только наличие файлов; добавлено сравнение состава без волатильных полей | FIXED
2026-08-10T17:58 | P1-S1-003 | Проверено: --check на подложенном pytest==8.3.4 → exit 1, на актуальном → exit 0 | PASS
2026-08-10T18:00 | P1-S1-003 | Новые тесты --check нашли дефект: relative_to падал на пути вне REPO_ROOT | BUG FIXED
2026-08-10T18:02 | P1-S1-003 | release gate не ставил окружение из lock → остался бы красным навсегда | FIXED
2026-08-10T18:04 | P1-S1-003 | Исправлено ложное утверждение о закоммиченном CI; счёт 79 → 91 | FIXED
2026-08-10T18:06 | P1-S1-003 | Убран trailing whitespace в NEXT.md, REQUIREMENTS_TRACEABILITY.md, ADR-012 | FIXED
2026-08-10T18:08 | P1-S1-003 | Полный прогон .venv/bin/python -m pytest -q (без активации) | PASS 258
2026-08-10T18:12 | P1-S1-003 | Второе ревью тимлида: NO-GO, 3 блокера (trigger по тегу, статус criterion, ложное состояние документов) | REJECTED
2026-08-10T18:14 | P1-S1-003 | on.push задавал только branches → tag push не запускает workflow, release gate недостижим | FIXED: добавлен tags ["**"]
2026-08-10T18:16 | P1-S1-003 | Добавлен парсер блока on: и 6 тестов на разобранную конфигурацию триггеров | PASS
2026-08-10T18:17 | P1-S1-003 | Независимая проверка ruby -ryaml: push = {branches, tags} | CONFIRMED
2026-08-10T18:18 | P1-S1-003 | Criterion разделён: статическая проверка install→verifier здесь, фактический CI run в P1-S1-007 | OK
2026-08-10T18:20 | P1-S1-003 | Ложное состояние исправлено: REQ-066 → NOT_STARTED, README Stage 1, TODO Stage 1 IN_PROGRESS, CURRENT.md перезаписан | FIXED
2026-08-10T18:22 | P1-S1-003 | Полный прогон без активации venv | PASS 264
```

---

## Tests and evidence

Прогон намеренно выполнен **без активации venv** — так ревью нашло дефект с системным `python3`.

| Команда | Результат | Кол-во | Покрытие |
|---|---|---|---|
| `.venv/bin/python -m pytest -q` | PASS | 264 | весь проект (macOS, CPython 3.13.7) |
| то же после `source .venv/bin/activate` | PASS | 264 | совпадает с прогоном без активации |
| `pytest tests/contracts/test_contracts_and_numeric.py` | PASS | 55 | схемы событий, числовая модель |
| `pytest tests/contracts/test_storage_offsets_and_frames.py` | PASS | 30 | инварианты offsets, формат фрейма |
| `pytest tests/contracts/test_segment_state_and_manifest.py` | PASS | 34 | state machine, lease, manifest |
| `pytest tests/contracts/test_dependency_lock.py` | PASS | 108 | lock, SBOM, роль, release gate, `--check`, триггеры и контракт CI |
| `pytest tests/fault/test_atomic_commit_crash_matrix.py` | PASS | 16 | 4 точки crash, валидация, идемпотентность |
| `pytest tests/fault/test_wal_recovery.py` | PASS | 21 | torn/CRC recovery, group commit, live-tail ceiling |
| `deploy/verify_dependencies.py` | exit 0 | — | «СОГЛАСОВАНО», 9 пакетов, платформа совпадает |
| `deploy/verify_dependencies.py --strict-platform` | exit 0 | — | платформа совпадает точно |
| `deploy/verify_dependencies.py --release` | exit 1 | — | development-роль отвергнута (ожидаемо) |
| `gen_dependency_artifacts.py --check` | exit 0 | — | артефакты совпадают с составом окружения |
| то же на подложенном `pytest==8.3.4` | exit 1 | — | устаревший lock обнаружен |
| `git check-ignore …/requirements.lock` | exit 1 | — | lock не игнорируется git |
| `git add --dry-run …/requirements.lock` | OK | — | lock попадает в индекс |
| `git diff --check` | exit 0 | — | trailing whitespace отсутствует |
| YAML `ci.yml` | OK | — | разобран парсером: 3 джоба, матрица 3.12/3.13 |

SKIPPED: 0. FAILED: 0.

Не запускалось: **CI ни разу не выполнялся** — remote отсутствует, `.github/workflows/ci.yml` untracked. Проверены только синтаксис и контракт workflow; фактический прогон — P1-S1-007. Также нет frontend Vitest/Playwright, integration/soak, performance, demo/testnet.

---

## Decisions and assumptions

| Решение | Источник | Последствия |
|---|---|---|
| Формат WAL-фрейма: header 16B (magic/version/flags/len/CRC32) | Roadmap §6.2 требует length+checksum, формат не фиксирует | Повреждение длины детектируется CRC отдельно от заголовка |
| `replay_safe_offset` = `published`, а не min(consumer) | §6.2: отставший consumer читает Parquet и не блокирует collector | WAL-only consumers указываются явно параметром |
| Формат файла сегмента не зафиксирован; writer — callback | §6.4 описывает протокол, не формат | PyArrow не является зависимостью Stage 1; реальный writer — P1-S1-004 |
| `last_lease_generation` сохраняется после снятия lease | §19 Этап 2: старый fencing token не пишет никогда | Просроченный writer не может перезахватить сегмент |
| Удаление сегментов не реализовано | §6.3: удаление только COMMITTED после retention checks | `may_delete()` даёт предикат; сама операция — задача maintenance |
| Lock снимается с окружения, а не с нового разрешения | §4: версии выбираются после smoke-теста | Генератор падает при расхождении; проверено на typing-inspection 0.4.2 vs 0.4.3 |
| Development host macOS, production host Linux+systemd | Решение владельца 2026-08-10, ADR-012 | Два набора dependency artifacts; parity-тесты на Linux обязательны |
| Роль в шапке артефакта; отсутствие роли = development | ADR-012 | Артефакт не может молча стать release artifact |
| Release gate — отдельный CI-джоб по тегу/вручную | §18.4, §20.1 | Ожидаемое падение release gate не красит обычный push |
| ASSUMPTION: `protocolVersion` — строка `major.minor` | §5.5 требует major bump, формат строки не задан | Уточнить в ADR-002 |

### DEVIATION: установка зависимостей

Stage 0 запрещал установку зависимостей. Stage 1 по Roadmap §19 Этап 1 требует `contracts` (Pydantic) и schema compatibility tests (pytest), поэтому в `.venv` установлены `pydantic==2.11.1` и `pytest==8.3.5`. Обе библиотеки прямо перечислены в Roadmap §4. `.venv/` исключён из git.

Нарушение Roadmap §4 (отсутствие lock и SBOM) закрыто для development-платформы задачей P1-S1-003. Для production остаётся открытым до P1-S1-006.

---

## Blockers and risks

| Блокер | Влияние | Проверки | Требуется |
|---|---|---|---|
| OPEN-005: архитектура production-хоста и версия Python | Блокирует P1-S1-004 (PyArrow), P1-S1-006 (Linux lock), ADR-005 (PostgreSQL) | Зафиксировано в DECISIONS_PENDING и ADR-012 | Решение владельца/тимлида |
| Нет Linux dependency artifacts | **Production release заблокирован**; разработка не блокируется | `verify_dependencies.py --release` падает по существу | P1-S1-006 после OPEN-005 |
| CI ни разу не запускался | Конфигурация не проверена на реальном runner | Синтаксис и контракт покрыты тестами, исполнение — нет | Remote + первый прогон |
| ADR-001…011 не утверждены | Формально Stage 1 идёт без утверждённых ADR | Зафиксированы в `docs/architecture/DECISIONS_PENDING.md` | Утверждение тимлидом |
| ADR-004 (Decimal128 precision/scale) | Блокирует P1-S1-004 вместе с OPEN-005 | Числовая модель реализована, Arrow schema — нет | Решение по precision/scale |
| Storage core проверен только на APFS | Гарантии fsync/rename на ext4/XFS не подтверждены замером | Linux CI прогоняет `tests/fault`, но crash-matrix с SIGKILL на ext4/XFS — нет | P1-S1-007 |
| Нет Hypothesis | Roadmap §4 требует property-тесты | Тесты только example-based | P1-S1-005 |

---

## Handoff

**Новые файлы этого блока:**

```
.github/workflows/ci.yml
docs/adr/ADR-012-development-and-production-hosts.md
deploy/dependencies/README.md
deploy/dependencies/darwin-arm64/requirements.lock
deploy/dependencies/darwin-arm64/sbom.cyclonedx.json
deploy/gen_dependency_artifacts.py
deploy/verify_dependencies.py
requirements.in
tests/contracts/test_dependency_lock.py
```

**Изменённые:** `.gitignore` (шаблон `*.lock` скрывал lock из git), `TODO.md` (P1-S1-003 → DONE, Stage 1 → IN_PROGRESS, добавлены P1-S1-006 и P1-S1-007, синхронизирован зависший статус P0-S0-004), `README.md` (Stage 0 → Stage 1, снято ложное «нет рабочего кода»), `NEXT.md`, `docs/adr/README.md`, `docs/architecture/DECISIONS_PENDING.md` (CONFLICT-004 → RESOLVED, добавлен OPEN-005), `docs/architecture/CURRENT.md` (перезаписан: было «нет никакого рабочего кода» и «первый commit ещё не создан»), `docs/REQUIREMENTS_TRACEABILITY.md` (REQ-064…067; REQ-066 → NOT_STARTED).

**Удалены:** `requirements.lock` и `deploy/sbom.cyclonedx.json` из корня — заменены платформенной раскладкой.

**Точка остановки:** P1-S1-003 — все 6 несоответствий ревью исправлены, тесты зелёные без активации venv, изменения **не закоммичены**. Ожидается повторная проверка тимлида; commit разрешён не был.

**Безопасное продолжение:**
```bash
cd /Users/vs/Desktop/bybit-chart
# без активации venv — именно так ревью нашло дефект с системным python3
.venv/bin/python -m pytest -q                            # ожидается 264 passed
.venv/bin/python deploy/verify_dependencies.py           # ожидается exit 0
.venv/bin/python deploy/verify_dependencies.py --release  # ожидается exit 1
.venv/bin/python deploy/gen_dependency_artifacts.py --check  # exit 0; нужна сеть
git diff --check                                         # ожидается чисто
# затем: commit P1-S1-003 после разрешения, далее P1-S1-005
```
