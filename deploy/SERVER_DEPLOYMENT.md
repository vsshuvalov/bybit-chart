# Server Deployment Guide — Bybit Collector (recorder-only)

**Цель:** развернуть минимальный сборщик данных на firstbyte.ru для начала круглосуточного сбора невосполнимых рыночных данных.

**Scope:** только публичные данные, без API-ключей, без торговли, без PostgreSQL.

**Hardware:** 8 vCPU, 8 GB RAM (firstbyte.ru)  
**OS target:** Ubuntu 24.04 LTS, x86_64, ext4  
**Roadmap stage:** готовность к Этапу 2–4 (collector + analytics + API + maintenance)

---

## Предварительные требования

### На сервере (провайдер должен предоставить):

- ✅ Ubuntu 24.04 LTS, x86_64
- ✅ ext4 filesystem (не btrfs, не ZFS)
- ✅ root или sudo доступ
- ✅ интернет-соединение к Bybit API (проверить geo-блокировку)
- ✅ NTP синхронизация включена (обязательно по §18.1)

### Проверки после получения доступа:

```bash
# OS и архитектура
uname -a  # должно содержать x86_64 и Linux

# Python версия
python3 --version  # ожидается 3.12+ (рекомендовано 3.13.7)

# Filesystem
df -Th  # проверить тип ФС (ext4) и свободное место (>150 GB)

# NTP
timedatectl status  # NTP service: active

# Доступ к Bybit
curl -I https://api.bybit.com/v5/market/time  # должен вернуть 200 OK
```

---

## Этап 1: Создание пользователя и структуры

```bash
# Создать непривилегированного пользователя
sudo useradd -r -m -d /opt/bybit-chart -s /bin/bash bybit

# Создать структуру каталогов
sudo -u bybit mkdir -p /opt/bybit-chart/{data,logs,.venv}

# Установить владельца
sudo chown -R bybit:bybit /opt/bybit-chart
```

---

## Этап 2: Перенос кода

### Вариант A: Git clone (рекомендуется)

Сначала создать GitHub remote (решает P1-S1-007):

```bash
# На локальной машине
cd /Users/vs/Desktop/bybit-chart
git remote add origin https://github.com/<username>/bybit-chart.git
git push -u origin main

# На сервере
sudo -u bybit git clone https://github.com/<username>/bybit-chart.git /opt/bybit-chart/repo
sudo -u bybit ln -s /opt/bybit-chart/repo/* /opt/bybit-chart/
```

### Вариант B: rsync (временное решение)

```bash
# На локальной машине
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' \
    /Users/vs/Desktop/bybit-chart/ user@firstbyte.ru:/tmp/bybit-chart/

# На сервере
sudo mv /tmp/bybit-chart/* /opt/bybit-chart/
sudo chown -R bybit:bybit /opt/bybit-chart
```

---

## Этап 3: Зависимости

```bash
# Установить Python 3.13 (если не установлен)
sudo apt update
sudo apt install -y python3.13 python3.13-venv python3.13-dev

# Создать venv как пользователь bybit
sudo -u bybit python3.13 -m venv /opt/bybit-chart/.venv

# Установить зависимости из lock (P1-S1-003)
# WARNING: используем development lock с darwin-arm64, Linux lock ещё не снят
sudo -u bybit /opt/bybit-chart/.venv/bin/pip install --require-hashes \
    -r /opt/bybit-chart/deploy/dependencies/darwin-arm64/requirements.lock

# Альтернатива (если lock несовместим): установить из requirements.in
sudo -u bybit /opt/bybit-chart/.venv/bin/pip install \
    -r /opt/bybit-chart/deploy/dependencies/requirements.in
```

**ВАЖНО:** Darwin lock может быть несовместим с Linux. Если установка падает:

```bash
# Снять Linux lock вручную на сервере (закрывает P1-S1-006)
cd /opt/bybit-chart
sudo -u bybit .venv/bin/python deploy/gen_dependency_artifacts.py \
    --role production \
    --platform linux-x86_64
```

---

## Этап 4: Проверка работоспособности

```bash
# Запустить тесты на Linux (P1-S1-007 acceptance criterion)
sudo -u bybit /opt/bybit-chart/.venv/bin/python -m pytest -q

# Проверить fault tests отдельно
sudo -u bybit /opt/bybit-chart/.venv/bin/python -m pytest tests/fault -v

# Короткий прогон collector (30 секунд)
sudo -u bybit /opt/bybit-chart/.venv/bin/python \
    examples/multi_symbol_demo.py --duration 30 --symbols BTCUSDT

# Проверить, что data/ начал заполняться
ls -lh /opt/bybit-chart/data/
```

Ожидаемый результат:
- ✅ Тесты зелёные (672 passed, 7 skipped или близко)
- ✅ `data/` содержит WAL-файлы или Parquet-сегменты
- ✅ Нет ошибок подключения к Bybit

---

## Этап 5: systemd unit

```bash
# Скопировать unit file
sudo cp /opt/bybit-chart/deploy/systemd/bybit-collector.service \
    /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable (запуск при загрузке)
sudo systemctl enable bybit-collector

# Start
sudo systemctl start bybit-collector

# Проверить статус
sudo systemctl status bybit-collector

# Смотреть логи в реальном времени
sudo journalctl -u bybit-collector -f
```

---

## Этап 6: Мониторинг и алармы

### Disk space alarm (критично!)

Roadmap §6.8 требует 25–30% свободного места. При 3 GB RAM compaction будет медленным, диск заполнится быстрее.

```bash
# Создать скрипт проверки диска
sudo tee /usr/local/bin/check-disk-reserve.sh > /dev/null <<'EOF'
#!/bin/bash
THRESHOLD=30
USAGE=$(df /opt/bybit-chart/data | tail -1 | awk '{print $(NF-1)}' | sed 's/%//')
FREE=$((100 - USAGE))

if [ "$FREE" -lt "$THRESHOLD" ]; then
    echo "ALARM: Disk reserve below ${THRESHOLD}% (current: ${FREE}% free)" >&2
    # Отправить алерт (настроить по факту)
    # curl -X POST <webhook_url> -d "disk_low=${FREE}%"
    exit 1
fi
echo "OK: Disk reserve ${FREE}% free"
EOF

sudo chmod +x /usr/local/bin/check-disk-reserve.sh

# Добавить в cron (каждые 15 минут)
sudo crontab -e
# Добавить строку:
# */15 * * * * /usr/local/bin/check-disk-reserve.sh || logger -t disk-alarm "LOW DISK"
```

### Health check

```bash
# Проверить, что collector пишет данные
sudo -u bybit find /opt/bybit-chart/data -type f -mmin -5 | head -5

# Если пусто — проблема
```

### Log rotation

```bash
# journald автоматически ротирует логи, но стоит ограничить размер
sudo tee /etc/systemd/journald.conf.d/bybit.conf > /dev/null <<EOF
[Journal]
SystemMaxUse=500M
SystemMaxFileSize=100M
EOF

sudo systemctl restart systemd-journald
```

---

## Этап 7: 72-часовой замер (Roadmap §6.8)

После 72 часов работы снять метрики:

```bash
# Скрипт замера ёмкости
sudo -u bybit tee /opt/bybit-chart/measure_capacity.sh > /dev/null <<'EOF'
#!/bin/bash
set -e

DATA_DIR="/opt/bybit-chart/data"
DURATION_HOURS=72

echo "=== Capacity Measurement (${DURATION_HOURS}h) ==="
echo "Started: $(date -d '72 hours ago' '+%Y-%m-%d %H:%M:%S')"
echo "Ended: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Общий размер data/
TOTAL_MB=$(du -sm "$DATA_DIR" | awk '{print $1}')
echo "Total data size: ${TOTAL_MB} MB"

# Размер по символам
for symbol in BTCUSDT ETHUSDT XRPUSDT; do
    SIZE=$(find "$DATA_DIR" -path "*${symbol}*" -type f -exec du -cb {} + 2>/dev/null | tail -1 | awk '{print $1}')
    SIZE_MB=$((SIZE / 1024 / 1024))
    echo "  ${symbol}: ${SIZE_MB} MB"
done

# Bytes per hour
BYTES_PER_HOUR=$((TOTAL_MB * 1024 * 1024 / DURATION_HOURS))
MB_PER_HOUR=$((BYTES_PER_HOUR / 1024 / 1024))
GB_PER_DAY=$(echo "scale=2; $MB_PER_HOUR * 24 / 1024" | bc)

echo ""
echo "Rate: ${MB_PER_HOUR} MB/hour (${GB_PER_DAY} GB/day)"

# Экстраполяция на 30 суток
GB_30D=$(echo "scale=1; $GB_PER_DAY * 30" | bc)
WITH_RESERVE=$(echo "scale=0; $GB_30D * 1.4" | bc)  # +40% (derived + reserve)

echo ""
echo "=== Capacity Estimate ==="
echo "30-day retention (raw + derived): ${GB_30D} GB"
echo "With 30% reserve: ${WITH_RESERVE} GB"
echo ""
echo "Recommended disk: $(( (WITH_RESERVE / 100 + 1) * 100 )) GB NVMe"
EOF

chmod +x /opt/bybit-chart/measure_capacity.sh

# Запустить через 72 часа
echo "/opt/bybit-chart/measure_capacity.sh > /opt/bybit-chart/capacity_report.txt" | \
    at now + 72 hours
```

---

## Известные ограничения текущей версии

❌ **Не реализовано (будет в Этапе 2-4):**
- Writer lease / fencing token
- Non-blocking IPC к analytics
- PostgreSQL
- L50/L1000/ticker/allLiquidation feeds (только publicTrade + orderbook.200)
- Cutover/rollback protocol
- Health endpoint

✅ **8 vCPU + 8 GB RAM — достаточно для полного stack:**
- Collector: ~500-800 MB
- PostgreSQL: ~1-2 GB (shared_buffers + connections)
- Analytics worker: ~1-2 GB (PyArrow batches + orderbook L1000)
- API gateway: ~500 MB
- Maintenance worker: ~500 MB (запускается по расписанию)
- OS + buffers: ~1-2 GB
- **Итого: ~5-7 GB в пике, запас 1-3 GB**

**Возможности с текущим железом:**
- ✅ Круглосуточный сбор всех трёх символов
- ✅ PostgreSQL для workspace/audit/execution metadata (ADR-005)
- ✅ Concurrent-load gate: 3× replay + API + Pine + optimizer одновременно (§18.4)
- ✅ Full analytics stack (Delta, CVD, VWAP, Volume Profile, OBI)
- ⚠️ L1000/RPI — возможно, но с мониторингом RAM (может потребовать swap или ограничение symbols)

**Что остаётся на макбуке:**
- Frontend development (браузер удобнее локально)
- ML research jobs (пока не нужны на сервере)
- Backtesting experiments

---

## Troubleshooting

### Collector падает с OOM

```bash
# Проверить память
free -h
sudo journalctl -u bybit-collector | grep -i "killed\|oom"

# Временное решение: уменьшить symbols до одного
# В /etc/systemd/system/bybit-collector.service:
# ExecStart=... --symbols BTCUSDT
sudo systemctl daemon-reload
sudo systemctl restart bybit-collector
```

### Нет подключения к Bybit

```bash
# Проверить DNS и routing
ping -c 3 api.bybit.com
curl -v https://api.bybit.com/v5/market/time

# Проверить firewall
sudo ufw status
```

### Диск заполнился

```bash
# Экстренная очистка (только если критично!)
# ВНИМАНИЕ: теряются старые данные
sudo systemctl stop bybit-collector
sudo -u bybit find /opt/bybit-chart/data -type f -mtime +7 -delete
sudo systemctl start bybit-collector
```

---

## Следующие шаги

После успешного развёртывания:

1. ✅ **Закрыть OPEN-005** — фактическая архитектура: x86_64, Ubuntu 24.04, Python 3.13.x
2. ✅ **P1-S1-006** — снять Linux lock после успешного `pytest -q` на сервере
3. ✅ **P1-S1-007** (частично) — первый прогон на Linux (без GitHub Actions пока)
4. ⏳ **72h soak** — дождаться capacity report
5. ⏳ **Capacity ADR** — на основе замера решить про апгрейд железа
6. ⏳ **Roadmap Этап 2** — реализовать полноценный изолированный collector с IPC

---

**Контакты для вопросов:** этот документ обновляется по мере развёртывания.
