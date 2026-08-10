# ADR-012: Разделение development- и production-хоста

- **Дата:** 2026-08-10
- **Статус:** ACCEPTED
- **Авторы:** владелец проекта (решение), Claude Code (запись)
- **Reviewer:** тимлид
- **Закрывает:** CONFLICT-004

## Контекст

Roadmap §4 объявляет reference production environment — Linux + `systemd`, и
одновременно допускает: «если целевой 24/7-хост остаётся macOS, тимлид
отдельным ADR заменяет unit/runbook на `launchd`, сохраняя те же process
boundaries, health и immutable release». Разработка ведётся на macOS
(Darwin arm64), поэтому целевой хост оставался неподтверждённым
(CONFLICT-004).

Вопрос перестал быть теоретическим на задаче P1-S1-003 (dependency lock и
SBOM). Набор зависимостей содержит платформенно-зависимое колесо
`pydantic_core-2.33.0-cp313-cp313-macosx_11_0_arm64.whl`. Lock, снятый на
macOS, на Linux невоспроизводим: `pip install --require-hashes` не найдёт
нужного артефакта. Без решения о хосте нельзя ни объявить lock валидным,
ни объявить его непригодным.

Дополнительно от платформы зависит существо storage core, уже
реализованного в P1-S1-002: поведение `fsync`, `fsync` каталога, атомарность
`rename`, семантика durability при crash. Эти гарантии на APFS и на
ext4/XFS различаются, а тесты пока прогонялись только на macOS.

## Варианты

1. **Единый хост macOS + launchd.** Разработка и production на одной
   платформе, один lock, `launchd` вместо `systemd`. Требует отдельного ADR
   по §4 и оставляет 24/7-нагрузку на непредназначенной для неё ОС.
2. **Единый хост Linux.** Разработка тоже переезжает на Linux (VM или
   контейнер). Один lock, полное совпадение платформ, но текущий рабочий
   контур ломается.
3. **Разделение: development на macOS, production на Linux + systemd.**
   Соответствует reference environment Roadmap §4 без переезда разработки.
   Цена — по одному набору dependency artifacts на платформу и обязательный
   повтор платформенно-зависимых тестов на Linux.

## Решение

Принят вариант 3.

| Роль | Платформа | Статус |
|---|---|---|
| Development host | macOS / Darwin arm64 | DECIDED |
| Production host | Linux + `systemd` | DECIDED |
| Production architecture (x86_64 / arm64) | — | **OPEN** |
| Production Python version (точная) | — | **OPEN** |

Следствия, обязательные к исполнению:

1. **Dependency artifacts — по одному набору на платформу**, с явной ролью
   в шапке:

   ```
   deploy/dependencies/darwin-arm64/    РОЛЬ: development
   deploy/dependencies/linux-<arch>/    РОЛЬ: production
   ```

2. **macOS-lock никогда не является Linux release artifact.** Правило
   проверяется механически: генератор отказывается выпускать
   `--role production` на Darwin; `verify_dependencies.py --release`
   отвергает lock с ролью `development`.

3. **Linux-lock снимается только в чистом Linux-окружении** — установка по
   `requirements.in`, прогон pytest, затем генератор. Ручная правка
   macOS-lock под Linux запрещена: состав транзитивных зависимостей и
   колёса зависят от платформы, а исправленный руками файл не соответствует
   ни одному окружению, на котором проходили тесты.

4. **Прямые зависимости общие.** `requirements.in` один для обеих платформ;
   расходится только разрешённый состав и хеши.

5. **Обязательный повтор тестов на Linux** до production: WAL, `fsync`,
   atomic `rename`, crash recovery, `systemd`-контур, performance и soak.
   Зелёные тесты на macOS не являются свидетельством для production
   (Roadmap §18.4 hard gates, §22 DoD).

6. **Отсутствие Linux-lock блокирует production release, но не разработку
   на macOS.** Release gate падает по существу, а не пропускает выкат.

7. **Архитектура production-хоста и точная версия Python обязаны быть
   зафиксированы до введения PyArrow (P1-S1-004) и PostgreSQL-драйвера**
   (ADR-005): у обеих библиотек бинарные колёса, привязанные к
   архитектуре и `cp3xx`. Ввод их в зависимости без этого решения
   означал бы фиксацию состава для неизвестной платформы.

## Последствия

**Положительные**

- Production идёт на reference environment Roadmap §4; `launchd`-ветка и
  сопутствующий ADR не нужны.
- Правило «lock не пересекает платформу» проверяется кодом и тестами, а не
  договорённостью.
- Development не блокируется отсутствием Linux-хоста.
- Разделение введено до PyArrow и PostgreSQL, поэтому платформенную модель
  не придётся переписывать — добавится только Linux-набор артефактов.

**Отрицательные / компромиссы**

- Два набора dependency artifacts; обновление зависимости требует
  регенерации на обеих платформах.
- Платформенно-зависимые тесты дублируются в CI.
- Development-окружение не совпадает с production: часть дефектов
  (`fsync`, права, лимиты) проявится только в Linux CI.

**Риски**

- Расхождение версий Python между хостами даст разный состав колёс.
  Снимается фиксацией точной версии до PyArrow (следствие 7).
- Соблазн «поправить lock руками» под Linux. Снят гардом генератора и
  release gate, но остаётся организационно.
- Пока Linux CI не подключён, storage core остаётся проверенным только на
  APFS.

## Ссылки

- Roadmap §4 — технологический стек, reference production environment, lock и SBOM
- Roadmap §18.4 — release hard gates
- Roadmap §20.1 — immutable release artifact, dependency lock
- Roadmap §22 — Definition of Done
- `docs/architecture/DECISIONS_PENDING.md` — CONFLICT-004
- ADR-004 (Decimal128 precision/scale), ADR-005 (PostgreSQL) — зависят от следствия 7
- Задачи: P1-S1-003 (development-lock), P1-S1-006 (Linux artifacts), P1-S1-007 (Linux parity)
