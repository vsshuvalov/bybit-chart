# Нерешённые вопросы и конфликты

**Stage:** 0  
**Дата:** 2026-08-10  
**Статус:** ни одно решение не принято молча — всё требует ADR от тимлида.

---

## Условные обозначения

- `REQUIRED` — решение обязательно до реализации этапа.
- `DECIDED` — уже зафиксировано в нормативных документах.
- `ASSUMPTION` — рабочее предположение, не подтверждённое явно.
- `OPEN` — открытый вопрос, конфликт или пропущенная деталь.

---

## ADR-001: Границы процессов и запрещённые зависимости (REQUIRED)

Roadmap фиксирует ответственность и запреты каждого процесса (§3.3). Но явный список запрещённых Python-импортов и CI-правил его проверки — не задан.

Нужно утвердить:
- какой инструмент проверяет import boundaries в CI;
- допустимые внутренние зависимости между packages;
- entry point каждого долгоживущего сервиса.

## ADR-002: Protobuf-схемы, IPC и правила совместимости протокола (REQUIRED)

Roadmap требует gRPC по Unix domain sockets (§4). Конкретные `.proto`-файлы и policy major/minor/patch для `protocolVersion` не определены.

## ADR-003: Владение WAL, Parquet, manifest и checkpoint (REQUIRED)

Roadmap описывает ownership table (§6.1) и состояния файла (§6.3). Конкретный механизм lease (файловый lock / PostgreSQL advisory / другой) не выбран.

## ADR-004: Каноническая integer/Decimal-модель и wire-format (REQUIRED)

Roadmap задаёт integer/Decimal128 модель (§6.6). Не зафиксировано:
- хранение `tickSize` и `qtyStep` в InstrumentConfig;
- точный Parquet schema (Decimal128 precision/scale);
- JSON wire-format для int64 (строки) и Decimal.

## ADR-005: PostgreSQL для транзакционных данных (REQUIRED)

Roadmap включает PostgreSQL (§4.1). Не определены:
- версия PostgreSQL;
- инструмент миграций (Alembic / Flyway / другой);
- схема для workspaces/scripts/drawings/execution;
- backup-strategy (WAL archiving vs base backup vs managed).

## ADR-006: DataQuality, gaps, watermark и signal gating (REQUIRED)

Стартовые пороги watermark (§7.3 ROADMAP, §7 strategies doc) — `RESEARCH` пресеты, не production values. Нужно утвердить SLO-значения до Stage 9.

## ADR-007: Внутренний OrderIntent и единый Risk Engine (REQUIRED до Stage 9)

Roadmap фиксирует `OrderIntentProposal` lifecycle (§5.4) и risk defaults (§15.3). Конкретные live risk limits не утверждены.

## ADR-008: Граница поддерживаемого Pine-compatible subset (REQUIRED до трека P)

Roadmap задаёт v0.1 subset (§12.3). Parser framework (ANTLR4 или Lark) не выбран.

## ADR-009: Симулятор исполнения и консервативная fill-модель (REQUIRED до Stage 8)

Roadmap описывает три сценария (optimistic / base / conservative) (§13.3). Конкретная модель latency не утверждена.

## ADR-010: Жизненный цикл ML-модели и запрет прямого доступа ИИ к бирже (REQUIRED до Stage 11)

## ADR-011: Release, rollback, backup, RPO/RTO и secrets (REQUIRED до Stage 12)

Roadmap требует immutable artifact, canary и restore drill (§18.5, §20). RPO/RTO не зафиксированы числами.

---

## CONFLICT-001: Порядок приоритетов документов — незначительное расхождение

**Roadmap §1.1** задаёт порядок:
1. Roadmap
2. `multi-process-architecture.md`
3. `all-modules-data-persistence-architecture.md`
4. `all-modules-data-persistence-architecture-changes.md`
5. Heatmap spec
6. Strategies

**Промт CLAUDE_CODE_GREENFIELD_START_PROMPT.md** задаёт порядок:
1. Roadmap
2. Явные решения пользователя
3. `all-modules-data-persistence-architecture-changes.md`
4. `multi-process-architecture.md`
5. `all-modules-data-persistence-architecture.md`

**Влияние на Stage 0:** нет — Stage 0 не принимает доменных решений, поэтому конфликт не блокирует.  
**Влияние на Stage 1+:** низкое, т.к. Roadmap имеет приоритет в обоих списках. Использую порядок из промта как более актуальный.

## CONFLICT-002: `all-modules-data-persistence-architecture-changes.md` — архитектура одного процесса vs многопроцессная

**`all-modules-data-persistence-architecture-changes.md`** описывает исправления для стека «один FastAPI-процесс + Parquet + localStorage».

**Roadmap** целиком заменяет этот стек многопроцессной архитектурой.

**Разрешение (DECIDED):** Roadmap имеет приоритет (§1.1 п.1). Доменные правила changes-документа (нормализация ликвидаций, числовая модель, atomic Parquet commit, gap semantics) сохраняются и переносятся в соответствующие модули. Ссылки на «один FastAPI-процесс» в changes-документе игнорируются.

## CONFLICT-003: Full Orderbook — неопределённость availability

**Roadmap §8.2:** по состоянию на дату документа linear testnet был доступен с 2026-08-04, mainnet rollout ожидался 2026-08-11; scope **DEFERRED**, feature flag.

**Решение:** Full Orderbook остаётся DEFERRED до независимой проверки production-доступности. Перед реализацией тимлид подтверждает доступность и выдаёт отдельное ADR.

## CONFLICT-004: Целевой хост — macOS vs Linux

**Roadmap §4:** reference production environment — Linux + systemd. Текущий рабочий каталог — macOS.

**Roadmap §4 (явное):** «если целевой 24/7-хост остаётся macOS, тимлид отдельным ADR заменяет unit/runbook на `launchd`, сохраняя те же process boundaries, health и immutable release».

**Статус: RESOLVED** решением владельца 2026-08-10, зафиксировано в `docs/adr/ADR-012-development-and-production-hosts.md`.

| Роль | Платформа |
|---|---|
| Development host | macOS / Darwin arm64 |
| Production host | Linux + `systemd` |

Ветка `launchd` не применяется: целевой 24/7-хост — Linux, то есть reference environment §4.

**Остаётся OPEN (перенесено в OPEN-005):** архитектура production-хоста (x86_64 vs arm64) и точная версия Python.

## CONFLICT-005: BTC-specific thresholds в Heatmap spec vs instrument-neutral roadmap

**Heatmap spec (docx)** содержит абсолютные BTC-пороги (minimumVolumeBtc и т.д.).

**Roadmap §9.1 и Appendix A** заменяет их на `CalibratedThreshold` с `unit=base|quote|...` и `calibrationStatus=UNCALIBRATED` по умолчанию.

**Разрешение (DECIDED):** Roadmap имеет приоритет. BTC-числа из Heatmap spec сохраняются только как `baselineId=legacy_btc_v1, calibrationStatus=RESEARCH` (см. §A.16 Roadmap). ETH/XRP получают `value=null, calibrationStatus=UNCALIBRATED`.

---

## OPEN-001: Выбор Bybit client library

Roadmap §4 предлагает `httpx + websockets` либо официальный `pybit` за адаптером и требует выбора через ADR.

## OPEN-002: Experiment registry для ML

Roadmap §4 предлагает MLflow или собственный минимальный registry. Выбор после MVP research.

## OPEN-003: Целевой объём диска и retention политика

Roadmap §6.8 задаёт стартовый target raw retention 30 суток, но принимает его только после 72-часового замера. Числа для Stage 0 не утверждены.

## OPEN-004: NTP и clock sync

Roadmap §18.1 требует NTP sync для Bybit authentication window. Конкретный NTP source и допустимое смещение не зафиксированы.

## OPEN-005: Архитектура production-хоста и точная версия Python (REQUIRED до P1-S1-004 и ADR-005)

ADR-012 зафиксировал Linux + `systemd` как production-хост, но не архитектуру и не версию Python.

Нужно утвердить:
- архитектуру: x86_64 или arm64 (`linux-x86_64` vs `linux-aarch64` в каталоге артефактов);
- точную версию Python (например 3.13.7), а не `>=3.12`.

**Рекомендованный default (тимлид, 2026-08-10):** Linux x86_64 и CPython 3.13.7. Статус — рекомендация, не решение: остаётся `OPEN` до подтверждения фактического железа. Каталог артефактов при этом варианте — `deploy/dependencies/linux-x86_64/`.

**Почему блокирует:** PyArrow (P1-S1-004) и PostgreSQL-драйвер (ADR-005) поставляются бинарными колёсами, привязанными к архитектуре и `cp3xx`. Ввод их в зависимости без этого решения означает фиксацию состава для неизвестной платформы. До решения Linux-lock (P1-S1-006) не может быть снят.
