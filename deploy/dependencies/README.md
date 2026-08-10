# Dependency artifacts по платформам

**Источник:** Roadmap §4 (lock-файл и SBOM обязательны), §20.1 (release
artifact содержит dependency lock), ADR-012 (разделение хостов).

## Раскладка

```
deploy/dependencies/
  darwin-arm64/          РОЛЬ: development   ← есть
    requirements.lock
    sbom.cyclonedx.json
  linux-<arch>/          РОЛЬ: production    ← НЕ СНЯТ (P1-S1-006)
    requirements.lock
    sbom.cyclonedx.json
```

Каталог называется по платформе: `<system>-<machine>` в нижнем регистре
(`darwin-arm64`, `linux-x86_64`, `linux-aarch64`). Верификатор выбирает lock
по текущей платформе, поэтому имя каталога обязано совпадать с шапкой файла —
это проверяется тестом.

## Роли

| Роль | Платформа | Назначение |
|---|---|---|
| `development` | macOS / Darwin arm64 | локальная разработка; **не** release artifact |
| `production` | Linux + `systemd` | release artifact |

Роль объявлена в шапке lock (`# РОЛЬ:`) и в SBOM
(`bybit:artifact_role`, `bybit:release_artifact`).

## Правила

1. **macOS-lock никогда не используется как Linux release artifact.**
   Проверяется механически: генератор отказывает на `--role production` под
   Darwin, а `verify_dependencies.py --release` отвергает роль
   `development`.
2. **Lock другой платформы не правится вручную.** Состав транзитивных
   зависимостей и колёса зависят от платформы; отредактированный файл не
   соответствует ни одному окружению, на котором проходили тесты.
   Linux-lock снимается в чистом Linux-окружении.
3. **Прямые зависимости общие** — один `requirements.in` в корне. По
   платформам расходятся только разрешённый состав и хеши.
4. **Lock снимается с окружения, на котором прошли тесты**, а не с нового
   разрешения зависимостей. Проверено на этом проекте: свежее разрешение
   `pydantic==2.11.1 pytest==8.3.5` выбирает `typing-inspection 0.4.3`,
   тогда как зелёное окружение содержит `0.4.2`.

## Команды

```bash
# Снять артефакты для текущей платформы (нужна сеть: хеши берутся с PyPI)
python3 deploy/gen_dependency_artifacts.py

# Не устарели ли артефакты относительно окружения (нужна сеть; ничего не пишет).
# Сравнивается состав, а не только наличие файлов; время генерации и
# serialNumber SBOM игнорируются как волатильные.
python3 deploy/gen_dependency_artifacts.py --check

# Проверить соответствие окружения (offline)
python3 deploy/verify_dependencies.py

# Целевой хост: расхождение платформы — ошибка
python3 deploy/verify_dependencies.py --strict-platform

# Release gate: нужна роль production и точное совпадение платформы
python3 deploy/verify_dependencies.py --release

# dev-CI на платформе без lock: PENDING вместо ошибки
python3 deploy/verify_dependencies.py --pending-ok

# Воспроизвести зафиксированный состав
pip install --require-hashes -r deploy/dependencies/<tag>/requirements.lock
```

## Порядок снятия Linux-артефактов (P1-S1-006)

Блокируется OPEN-005: архитектура production-хоста (x86_64 vs arm64) и
точная версия Python не утверждены.

```bash
# в чистом Linux-окружении утверждённой архитектуры и версии Python
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.in
pytest -q                                    # обязателен зелёный прогон
pytest tests/fault -v                        # WAL, fsync, atomic rename, recovery
python3 deploy/gen_dependency_artifacts.py --role production
python3 deploy/verify_dependencies.py --release
```

До этого production release заблокирован: `--release` падает по существу.
