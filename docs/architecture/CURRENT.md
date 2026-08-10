# Текущее состояние архитектуры

**Версия:** Stage 0  
**Дата:** 2026-08-10  
**Статус:** `GREENFIELD / NO IMPLEMENTATION`

---

## Фактически реализовано

На дату Stage 0 в репозитории нет никакого рабочего кода.

Созданы только:

- структура каталогов, обоснованная дорожной картой (§3.5 ROADMAP);
- копии нормативных документов в `docs/specifications/source/`;
- документация Stage 0: `CURRENT.md`, `TARGET.md`, `DECISIONS_PENDING.md`, `docs/adr/README.md`;
- файлы журнала: `NEXT.md`, `TODO.md`, `README.md`;
- `.gitignore`.

## Что отсутствует

- `market-collector` — не реализован;
- `orderflow-worker` — не реализован;
- `api-gateway` — не реализован;
- `maintenance-worker` — не реализован;
- `execution-risk` — не реализован;
- `strategy-worker` — не реализован;
- `contracts` (Protobuf/Pydantic схемы) — не реализованы;
- WAL / Parquet-хранилище — не реализовано;
- PostgreSQL-схема — не реализована;
- Frontend (React/TypeScript) — не реализован;
- Pine-compatible runtime — не реализован;
- Simulator/replay — не реализован;
- AI-ассистент — не реализован;
- Production-подключения, API-ключи, торговые операции — **не инициализированы и не запускались**.

## Git-статус

Репозиторий инициализирован командой `git init -b main`. Первый commit ещё не создан — ожидает review gate.

Нет remote, нет тегов, нет веток кроме `main` (без commits).
