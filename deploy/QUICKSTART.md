# Quick Start — Server Deployment Checklist

**Server:** firstbyte.ru, 8 vCPU, 8 GB RAM  
**Target:** Ubuntu 24.04 LTS, x86_64, ext4  
**Goal:** Круглосуточный collector + готовность к full stack

---

## Pre-flight checks (выполнить сразу после получения доступа)

```bash
# 1. OS и архитектура
uname -a  # ожидается: Linux ... x86_64

# 2. Python версия
python3 --version  # ожидается: 3.12+ (рекомендовано 3.13.7)

# 3. Filesystem и диск
df -Th  # проверить: ext4, >150 GB свободно

# 4. NTP
timedatectl status  # NTP service: active (ОБЯЗАТЕЛЬНО)

# 5. Доступ к Bybit
curl -I https://api.bybit.com/v5/market/time  # ожидается: HTTP/2 200
```

---

## Deployment (30-40 минут)

### 1. Системный пользователь

```bash
sudo useradd -r -m -d /opt/bybit-chart -s /bin/bash bybit
sudo mkdir -p /opt/bybit-chart/{data,logs,backups}
sudo chown -R bybit:bybit /opt/bybit-chart
```

### 2. Код (выбрать один вариант)

**A. Git clone (рекомендуется):**

```bash
# На локальной машине: создать GitHub repo и push
cd /Users/vs/Desktop/bybit-chart
git remote add origin https://github.com/<username>/bybit-chart.git
git push -u origin main

# На сервере: clone
sudo -u bybit git clone https://github.com/<username>/bybit-chart.git /opt/bybit-chart/repo
cd /opt/bybit-chart && sudo -u bybit ln -s repo/* .
```

**B. rsync (временно):**

```bash
# На локальной машине
rsync -avz --exclude='.git' --exclude='__pycache__' \
    /Users/vs/Desktop/bybit-chart/ user@server:/tmp/bybit-chart/

# На сервере
sudo mv /tmp/bybit-chart/* /opt/bybit-chart/
sudo chown -R bybit:bybit /opt/bybit-chart
```

### 3. Python + зависимости

```bash
# Установить Python 3.13
sudo apt update
sudo apt install -y python3.13 python3.13-venv python3.13-dev build-essential

# Создать venv
sudo -u bybit python3.13 -m venv /opt/bybit-chart/.venv

# Установить зависимости
cd /opt/bybit-chart
sudo -u bybit .venv/bin/pip install --upgrade pip
sudo -u bybit .venv/bin/pip install -r deploy/dependencies/requirements.in
```

### 4. PostgreSQL (опционально, для Этапов 9+)

```bash
# Установить
sudo apt install -y postgresql-16 postgresql-client-16

# Настроить (см. deploy/POSTGRESQL_SETUP.md)
sudo -u postgres psql <<EOF
CREATE DATABASE bybit_platform;
CREATE USER bybit WITH PASSWORD 'CHANGE_ME';
GRANT ALL PRIVILEGES ON DATABASE bybit_platform TO bybit;
\q
EOF
```

### 5. Тесты (ОБЯЗАТЕЛЬНО — закрывает P1-S1-006, P1-S1-007)

```bash
cd /opt/bybit-chart
sudo -u bybit .venv/bin/python -m pytest -q

# Ожидается: 672 passed, 7 skipped
# Если тесты зелёные → P1-S1-006 DONE (Linux lock доказан)
```

### 6. systemd unit

```bash
sudo cp /opt/bybit-chart/deploy/systemd/bybit-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bybit-collector
sudo systemctl start bybit-collector

# Проверка
sudo systemctl status bybit-collector
sudo journalctl -u bybit-collector -f
```

### 7. Disk alarm

```bash
# Создать скрипт
sudo tee /usr/local/bin/check-disk-reserve.sh > /dev/null <<'EOF'
#!/bin/bash
THRESHOLD=30
USAGE=$(df /opt/bybit-chart/data | tail -1 | awk '{print $(NF-1)}' | sed 's/%//')
FREE=$((100 - USAGE))
if [ "$FREE" -lt "$THRESHOLD" ]; then
    echo "ALARM: Disk ${FREE}% free (threshold ${THRESHOLD}%)" >&2
    logger -t disk-alarm "LOW DISK: ${FREE}% free"
    exit 1
fi
echo "OK: ${FREE}% free"
EOF

sudo chmod +x /usr/local/bin/check-disk-reserve.sh

# Добавить в cron (каждые 15 минут)
echo "*/15 * * * * /usr/local/bin/check-disk-reserve.sh" | sudo crontab -
```

---

## Verification (5 минут)

```bash
# 1. Collector работает
sudo systemctl status bybit-collector | grep "active (running)"

# 2. Данные пишутся
sudo -u bybit find /opt/bybit-chart/data -type f -mmin -5

# 3. Нет ошибок в логах
sudo journalctl -u bybit-collector -n 50 | grep -i error

# 4. Диск не заполнен
df -h /opt/bybit-chart/data

# 5. NTP работает
timedatectl | grep "System clock synchronized: yes"
```

---

## После 72 часов

```bash
# Запустить capacity measurement (Roadmap §6.8)
sudo -u bybit /opt/bybit-chart/deploy/measure_capacity.sh > capacity_report.txt

# Сохранить отчёт для Capacity ADR
cat capacity_report.txt
```

---

## Задачи, которые закрываются

- ✅ **OPEN-005** — архитектура зафиксирована: x86_64, Ubuntu 24.04, Python 3.13.x
- ✅ **P1-S1-006** — Linux lock снят после зелёных тестов
- ✅ **P1-S1-007** (частично) — Linux parity для pytest доказана, CI runner остаётся
- ✅ **Roadmap §6.8** — через 72h получаем capacity baseline

---

## Troubleshooting

**Collector падает с OOM:**
```bash
# Проверить память
free -h
sudo journalctl -u bybit-collector | grep -i "killed\|oom"

# При 8 GB это не должно происходить для 3 символов
# Если происходит — проверить утечки памяти
```

**Нет подключения к Bybit:**
```bash
curl -v https://api.bybit.com/v5/market/time
# Проверить geo-блокировку, firewall
```

**Тесты падают на Linux:**
```bash
# Проверить отличия в поведении fsync/filesystem
sudo -u bybit .venv/bin/python -m pytest tests/fault -v
# Сравнить с macOS результатами
```

---

## Next Steps

1. Дождаться 72 часов → capacity report
2. Принять ADR по retention и disk size
3. Реализовать Roadmap Этап 2: изолированный collector с IPC
4. Добавить L50/L1000/ticker/liquidation feeds
5. Развернуть PostgreSQL + migrations (P1-S1-009)
6. Изолировать analytics и API (Этап 4)
