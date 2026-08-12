# Grafana Dashboards для bybit-chart (Этап 5.1.3)

## Dashboards

### 1. Overview Dashboard (`overview.json`)
Общий мониторинг всех 5 процессов:
- Process health (все workers UP/DOWN)
- Trade ingestion rate
- Book events rate
- API request rate & errors
- WAL lag
- Book gaps
- Analytics query latency

### 2. Collector Dashboard (`collector.json`)
Детальный мониторинг collector-worker:
- WebSocket connection status
- WS reconnects & errors
- Trade/book ingestion rates
- WAL write latency (p50/p95/p99)
- IPC publish success rate
- Fencing conflicts

### 3. Orderflow Dashboard (`orderflow.json`)
Мониторинг orderflow detectors:
- BookState status (not_ready/syncing/ready/gap)
- Book snapshots/deltas processed
- Book gaps detected
- Detector events (sweeps/cascades/walls/absorption)
- Market regime confidence & changes
- Event processing latency

## Установка

### 1. Установить Grafana

**macOS (Homebrew):**
```bash
brew install grafana
```

**Ubuntu/Debian:**
```bash
sudo apt-get install -y software-properties-common
sudo add-apt-repository "deb https://packages.grafana.com/oss/deb stable main"
wget -q -O - https://packages.grafana.com/gpg.key | sudo apt-key add -
sudo apt-get update
sudo apt-get install grafana
```

**Manual install:**
```bash
cd /tmp
wget https://dl.grafana.com/oss/release/grafana-10.0.0.linux-amd64.tar.gz
tar -zxvf grafana-10.0.0.linux-amd64.tar.gz
sudo mv grafana-10.0.0 /opt/grafana
```

### 2. Скопировать provisioning config

```bash
# Datasource (Prometheus)
sudo mkdir -p /etc/grafana/provisioning/datasources
sudo cp deploy/grafana/provisioning/datasources/prometheus.yml /etc/grafana/provisioning/datasources/

# Dashboards
sudo mkdir -p /etc/grafana/provisioning/dashboards
sudo cp deploy/grafana/provisioning/dashboards/dashboards.yml /etc/grafana/provisioning/dashboards/
sudo cp deploy/grafana/dashboards/*.json /etc/grafana/provisioning/dashboards/
```

### 3. Запустить Grafana

**Development (local):**
```bash
grafana-server --config=/usr/local/etc/grafana/grafana.ini --homepath /usr/local/share/grafana
```

**Production (systemd):**
```bash
sudo systemctl enable grafana-server
sudo systemctl start grafana-server
sudo systemctl status grafana-server
```

### 4. Открыть UI

URL: http://localhost:3000

**Default credentials:**
- Username: `admin`
- Password: `admin` (будет запрошена смена при первом логине)

## Проверка

1. **Datasource:** Settings → Data Sources → Prometheus (должен быть зелёный)
2. **Dashboards:** Dashboards → Browse → "Bybit Chart - Overview"

## Ручная загрузка dashboards (если provisioning не работает)

1. Открыть Grafana UI: http://localhost:3000
2. Login (admin/admin)
3. Create → Import
4. Upload JSON file или paste JSON
5. Select Prometheus datasource
6. Import

Повторить для каждого dashboard:
- `deploy/grafana/dashboards/overview.json`
- `deploy/grafana/dashboards/collector.json`
- `deploy/grafana/dashboards/orderflow.json`

## Кастомизация

### Добавить новые панели

1. Открыть dashboard
2. Add panel → Add new panel
3. Выбрать metrics из Prometheus
4. Настроить visualization (graph/stat/gauge/table)
5. Save dashboard

### PromQL примеры

```promql
# Collector: trades per second (last 1min)
rate(collector_trades_received_total[1m])

# Orderflow: book gap rate (last 5min)
rate(orderflow_book_gaps_detected_total[5m])

# Analytics: p95 query latency
histogram_quantile(0.95, rate(analytics_query_latency_seconds_bucket[5m]))

# API: error rate %
rate(api_http_errors_total[1m]) / rate(api_http_requests_total[1m]) * 100

# Maintenance: WAL lag in minutes
maintenance_wal_lag_seconds / 60

# All processes up (should be 5)
sum(collector_process_up + analytics_process_up + orderflow_process_up + maintenance_process_up + api_process_up)
```

## Alerting

Grafana может отправлять alerts на основе метрик:

1. **Edit panel** → Alert tab
2. Create alert rule (например: "WAL lag > 5 minutes")
3. Configure notification channel (email/Slack/PagerDuty)

Примеры alert conditions:
- WAL lag > 300s (5 min)
- Book gap rate > 1/min
- Any process down (process_up == 0)
- API error rate > 5%
- WS disconnected (ws_connections_active == 0)

## Production рекомендации

### 1. Persistent storage

По умолчанию Grafana хранит dashboards в SQLite `/var/lib/grafana/grafana.db`

Для production используйте PostgreSQL или MySQL:

```ini
[database]
type = postgres
host = localhost:5432
name = grafana
user = grafana
password = <password>
```

### 2. Authentication

Настройте OAuth/LDAP вместо default admin/admin:

```ini
[auth.google]
enabled = true
client_id = <your-client-id>
client_secret = <your-client-secret>
scopes = https://www.googleapis.com/auth/userinfo.profile
auth_url = https://accounts.google.com/o/oauth2/auth
token_url = https://accounts.google.com/o/oauth2/token
```

### 3. High availability

Для HA setup используйте:
- Multiple Grafana instances за load balancer
- Shared database (PostgreSQL)
- Shared session storage (Redis)

### 4. Backup

Backup dashboards и datasources:

```bash
# Export all dashboards
curl -H "Authorization: Bearer <api-key>" \
  http://localhost:3000/api/search?query=& > dashboards.json

# Backup database
pg_dump grafana > grafana_backup.sql
```

## Troubleshooting

### Datasource не подключается

**Проблема:** "Bad Gateway" или "Connection refused" при проверке datasource

**Решение:**
1. Проверить что Prometheus запущен: `curl http://localhost:9090/api/v1/query?query=up`
2. Проверить Grafana logs: `sudo journalctl -u grafana-server -f`
3. Проверить firewall: `sudo ufw status`

### Dashboards не загружаются автоматически

**Проблема:** Provisioning не работает, dashboards не появляются

**Решение:**
1. Проверить пути в `dashboards.yml`: `path: /etc/grafana/provisioning/dashboards`
2. Проверить права доступа: `sudo chown -R grafana:grafana /etc/grafana/provisioning`
3. Перезапустить Grafana: `sudo systemctl restart grafana-server`
4. Проверить logs: `sudo tail -f /var/log/grafana/grafana.log`

### Метрики не отображаются

**Проблема:** Panels пустые или "No data"

**Решение:**
1. Проверить что Prometheus получает metrics: http://localhost:9090/targets
2. Проверить что query работает в Prometheus: http://localhost:9090/graph
3. Проверить time range в Grafana (может быть слишком узкий)
4. Проверить что datasource правильно настроен

## Следующие шаги

1. **Этап 5.1.4:** Alerting rules (Prometheus Alertmanager)
2. **Этап 5.2:** Distributed tracing (Jaeger/Tempo)
3. **Этап 5.3:** Performance optimization на основе метрик
