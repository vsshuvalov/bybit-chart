# Prometheus Setup для bybit-chart (Этап 5.1.2)

## Архитектура

```
Prometheus (port 9090)
    ↓ scrape
    ├─ api-server:8000/metrics (HTTP, native FastAPI)
    ├─ metrics-exporter:9100/metrics → collector UDS
    ├─ metrics-exporter:9101/metrics → analytics UDS
    ├─ metrics-exporter:9102/metrics → orderflow UDS
    ├─ metrics-exporter:9103/metrics → maintenance UDS
    └─ node-exporter:9104/metrics (system metrics)
```

## Установка

### 1. Установить Prometheus

**macOS (Homebrew):**
```bash
brew install prometheus
```

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y prometheus
```

**Manual install:**
```bash
cd /tmp
wget https://github.com/prometheus/prometheus/releases/download/v2.45.0/prometheus-2.45.0.linux-amd64.tar.gz
tar xvfz prometheus-*.tar.gz
sudo mv prometheus-*/prometheus /usr/local/bin/
sudo mv prometheus-*/promtool /usr/local/bin/
sudo mkdir -p /etc/prometheus /var/lib/prometheus
```

### 2. Установить Node Exporter (опционально, для system metrics)

```bash
# Ubuntu/Debian
sudo apt-get install -y prometheus-node-exporter

# macOS
brew install node_exporter
```

### 3. Скопировать конфигурацию

```bash
sudo cp deploy/prometheus.yml /etc/prometheus/prometheus.yml
sudo mkdir -p /etc/prometheus/alerts  # для alerting rules (Этап 5.1.4)
```

### 4. Запустить metrics-exporter

```bash
# Development (local)
python3 workers/metrics_exporter.py

# Production (systemd)
sudo cp deploy/systemd/bybit-metrics-exporter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bybit-metrics-exporter
sudo systemctl start bybit-metrics-exporter
sudo systemctl status bybit-metrics-exporter
```

### 5. Запустить Prometheus

**Development (local):**
```bash
prometheus --config.file=deploy/prometheus.yml --storage.tsdb.path=/tmp/prometheus-data
```

**Production (systemd):**
```bash
# Edit systemd service if needed
sudo systemctl enable prometheus
sudo systemctl start prometheus
sudo systemctl status prometheus
```

## Проверка

### 1. Проверить metrics exporters

```bash
# API server (native)
curl http://localhost:8000/metrics

# Collector (через exporter)
curl http://localhost:9100/metrics

# Analytics
curl http://localhost:9101/metrics

# Orderflow
curl http://localhost:9102/metrics

# Maintenance
curl http://localhost:9103/metrics
```

### 2. Prometheus UI

Открыть в браузере: http://localhost:9090

**Targets:** http://localhost:9090/targets — должны быть UP все endpoints

**Metrics browser:** http://localhost:9090/graph

Примеры запросов:
```promql
# Collector: trades per second
rate(collector_trades_received_total[1m])

# Orderflow: book gaps
rate(orderflow_book_gaps_detected_total[5m])

# Analytics: query latency (p95)
histogram_quantile(0.95, rate(analytics_query_latency_seconds_bucket[5m]))

# API: request rate
rate(api_http_requests_total[1m])

# Maintenance: WAL lag
maintenance_wal_lag_seconds
```

## Troubleshooting

### Workers не отвечают на metrics_exporter

**Проблема:** `# ERROR: collector-worker socket not found`

**Решение:**
1. Проверить что worker запущен: `systemctl status bybit-collector`
2. Проверить что UDS socket существует: `ls -la /tmp/bybit-collector.sock`
3. Проверить права доступа: socket должен быть readable для metrics-exporter user

### Prometheus не может scrape targets

**Проблема:** Targets показывают DOWN в UI

**Решение:**
1. Проверить что порты открыты: `netstat -tulpn | grep -E '8000|910[0-3]'`
2. Проверить firewall: `sudo ufw status` (Ubuntu) или `sudo firewall-cmd --list-all` (CentOS)
3. Проверить логи Prometheus: `sudo journalctl -u prometheus -f`

### Метрики пустые или нулевые

**Проблема:** Метрики экспортируются, но все значения = 0

**Решение:**
1. Проверить что workers обрабатывают данные: `systemctl status bybit-collector`
2. Проверить логи workers: `sudo journalctl -u bybit-collector -n 100`
3. Проверить что WebSocket подключён: проверить `collector_ws_connections_active` gauge

## Production рекомендации

### Retention

По умолчанию Prometheus хранит данные 15 дней. Для production:

```bash
# В systemd service или command line
--storage.tsdb.retention.time=30d
--storage.tsdb.retention.size=50GB
```

### Resource limits

**CPU:** 2-4 cores для ~100K samples/sec  
**RAM:** 4-8GB для 30 дней retention  
**Disk:** ~1GB/day для ~100 targets × 50 metrics

### High availability

Для HA setup используйте:
- **Prometheus Federation** (несколько Prometheus серверов)
- **Thanos** (долгосрочное хранение + global query view)
- **Cortex** (multi-tenant Prometheus as a Service)

## Следующие шаги

1. **Этап 5.1.3:** Grafana dashboards (визуализация метрик)
2. **Этап 5.1.4:** Alerting rules (уведомления при проблемах)
3. **Этап 5.3:** Performance optimization на основе метрик
