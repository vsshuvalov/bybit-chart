# PostgreSQL setup for Bybit platform
# Roadmap ADR-005: PostgreSQL для транзакционных и пользовательских данных
# Блокирует: P1-S1-009 (PostgreSQL migrations)

## Scope

PostgreSQL используется для:
- Workspace/user preferences (§11)
- Audit records (§18.2 RBAC, execution log)
- Execution metadata (orders, fills, positions) — Этап 9
- Strategy state и promotion records — Этап 10
- ML experiment registry — Этап 11

**Не используется для:** raw events (WAL/Parquet), derived analytics (тоже Parquet).

## Installation (Ubuntu 24.04)

```bash
# Установить PostgreSQL 16
sudo apt update
sudo apt install -y postgresql-16 postgresql-client-16

# Проверить запуск
sudo systemctl status postgresql

# Создать базу и пользователя
sudo -u postgres psql <<EOF
CREATE DATABASE bybit_platform;
CREATE USER bybit WITH PASSWORD 'change_me_in_production';
GRANT ALL PRIVILEGES ON DATABASE bybit_platform TO bybit;
ALTER DATABASE bybit_platform OWNER TO bybit;
\q
EOF
```

## Configuration

```bash
# /etc/postgresql/16/main/postgresql.conf

# Memory (для 8 GB RAM server)
shared_buffers = 2GB                # 25% RAM
effective_cache_size = 6GB          # 75% RAM
maintenance_work_mem = 512MB
work_mem = 16MB

# Connections
max_connections = 100

# WAL (durability)
wal_level = replica
fsync = on                          # КРИТИЧНО — не отключать
synchronous_commit = on
wal_buffers = 16MB

# Checkpoints
checkpoint_timeout = 10min
checkpoint_completion_target = 0.9

# Logging
log_destination = 'stderr'
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d.log'
log_statement = 'mod'               # log INSERT/UPDATE/DELETE
log_line_prefix = '%m [%p] %u@%d '
```

После изменений:

```bash
sudo systemctl restart postgresql
```

## Connection string

Для приложения (environment variable):

```bash
DATABASE_URL="postgresql://bybit:change_me_in_production@localhost:5432/bybit_platform"
```

Или в конфиге:

```yaml
database:
  host: localhost
  port: 5432
  database: bybit_platform
  user: bybit
  password: ${DB_PASSWORD}  # из secrets, не из git
```

## Security

```bash
# Ограничить доступ только с localhost
# /etc/postgresql/16/main/pg_hba.conf
# TYPE  DATABASE        USER            ADDRESS         METHOD
local   bybit_platform  bybit                           scram-sha-256
host    bybit_platform  bybit           127.0.0.1/32    scram-sha-256
host    bybit_platform  bybit           ::1/128         scram-sha-256

# Запретить remote access
sudo systemctl restart postgresql
```

## Backup (§18.5)

```bash
# Создать скрипт бэкапа
sudo tee /usr/local/bin/backup-postgres.sh > /dev/null <<'EOF'
#!/bin/bash
set -e

BACKUP_DIR="/opt/bybit-chart/backups/postgres"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/bybit_platform_${DATE}.sql.gz"

mkdir -p "$BACKUP_DIR"

# pg_dump с gzip
sudo -u postgres pg_dump bybit_platform | gzip > "$BACKUP_FILE"

# Ротация: хранить последние 7 дней
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +7 -delete

echo "Backup completed: $BACKUP_FILE"
EOF

sudo chmod +x /usr/local/bin/backup-postgres.sh

# Добавить в cron (каждый день в 3:00)
sudo crontab -e
# 0 3 * * * /usr/local/bin/backup-postgres.sh >> /var/log/postgres-backup.log 2>&1
```

## Migrations

**TODO (P1-S1-009):** создать initial schema и migration tool.

Предварительная структура:

```sql
-- Workspaces (§11)
CREATE TABLE workspaces (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    layout_json JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Audit log (§18.2)
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    user_id INTEGER,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100),
    resource_id VARCHAR(255),
    details JSONB,
    ip_address INET
);

CREATE INDEX idx_audit_timestamp ON audit_log(timestamp DESC);
CREATE INDEX idx_audit_user ON audit_log(user_id);

-- Execution orders (Этап 9)
CREATE TABLE orders (
    order_id VARCHAR(100) PRIMARY KEY,
    client_order_id VARCHAR(100),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    order_type VARCHAR(20) NOT NULL,
    qty DECIMAL(20, 8),
    price DECIMAL(20, 8),
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    metadata JSONB
);

CREATE INDEX idx_orders_symbol ON orders(symbol);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created ON orders(created_at DESC);
```

## Health check

```bash
# Проверить подключение
psql "postgresql://bybit:change_me_in_production@localhost:5432/bybit_platform" -c "SELECT version();"

# Проверить размер БД
psql "postgresql://bybit:change_me_in_production@localhost:5432/bybit_platform" -c "\l+"

# Проверить активные соединения
sudo -u postgres psql -c "SELECT count(*) FROM pg_stat_activity WHERE datname='bybit_platform';"
```

## Troubleshooting

### Не удаётся подключиться

```bash
# Проверить запуск
sudo systemctl status postgresql

# Проверить логи
sudo tail -f /var/log/postgresql/postgresql-16-main.log

# Проверить порт
sudo netstat -tlnp | grep 5432
```

### Медленные запросы

```bash
# Включить логирование медленных запросов
# postgresql.conf:
log_min_duration_statement = 1000  # log queries > 1s

sudo systemctl restart postgresql
```

## Next steps

После настройки PostgreSQL:

1. ✅ Закрыть ADR-005
2. ✅ Разблокировать P1-S1-009 (migrations)
3. ⏳ Реализовать initial schema
4. ⏳ Интегрировать в application startup
