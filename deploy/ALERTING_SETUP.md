# Alerting Rules для bybit-chart (Этап 5.1.4)

## Alert Categories

### 1. Process Health (`processes.yml`)
- **CollectorProcessDown**: Collector не запущен (critical, 1min)
- **AnalyticsProcessDown**: Analytics не запущен (warning, 2min)
- **OrderflowProcessDown**: Orderflow не запущен (critical, 1min)
- **MaintenanceProcessDown**: Maintenance не запущен (warning, 5min)
- **APIProcessDown**: API не запущен (critical, 30sec)
- **MultipleProcessesDown**: < 3 процесса работают (critical, 1min)

### 2. Collector (`collector.yml`)
- **WebSocketDisconnected**: WS connection lost (critical, 30sec)
- **WebSocketReconnectsHigh**: Частые reconnects (warning, 3min)
- **TradeIngestionStopped**: Trades не поступают (critical, 3min)
- **WALWriteLatencyHigh**: WAL p95 > 100ms (warning, 3min)
- **WALFsyncLatencyHigh**: WAL fsync p95 > 500ms (critical, 3min)
- **IPCDropRateHigh**: >5% IPC messages dropped (warning, 2min)
- **FencingConflictsDetected**: WriterLease conflicts (warning, 1min)

### 3. Orderflow (`orderflow.yml`)
- **BookStateNotReady**: BookState not ready >5min (warning)
- **BookStateGap**: Sequence gap detected (critical, 1min)
- **BookGapsRateHigh**: >0.5 gaps/sec (warning, 3min)
- **EventProcessingLatencyHigh**: p95 > 50ms (warning, 3min)
- **RegimeConfidenceLow**: Confidence <30% (info, 10min)
- **SweepsRateAnomalous**: >10 sweeps/sec (warning, 5min)

### 4. Maintenance (`maintenance.yml`)
- **WALLagHigh**: WAL lag >5 minutes (warning, 5min)
- **WALLagCritical**: WAL lag >30 minutes (critical, 5min)
- **DiskUsageHigh**: >80GB used (warning, 10min)
- **DiskUsageCritical**: >100GB used (critical, 5min)
- **SegmentSizeTooLarge**: Segment >1GB (warning, 10min)
- **SegmentCommitLatencyHigh**: Commit p95 >30sec (warning, 10min)

### 5. API (`api.yml`)
- **APIErrorRateHigh**: >5% error rate (warning, 3min)
- **APIErrorRateCritical**: >20% error rate (critical, 1min)
- **APILatencyHigh**: p95 >1sec (warning, 5min)
- **APILatencyCritical**: p95 >5sec (critical, 2min)
- **IPCClientTimeoutsHigh**: >0.1 timeouts/sec (warning, 3min)
- **WebSocketConnectionsHigh**: >100 connections (warning, 5min)

## Установка

### 1. Установить Alertmanager

**macOS (Homebrew):**
```bash
brew install alertmanager
```

**Ubuntu/Debian:**
```bash
sudo apt-get install -y prometheus-alertmanager
```

**Manual install:**
```bash
cd /tmp
wget https://github.com/prometheus/alertmanager/releases/download/v0.26.0/alertmanager-0.26.0.linux-amd64.tar.gz
tar xvfz alertmanager-*.tar.gz
sudo mv alertmanager-*/alertmanager /usr/local/bin/
sudo mv alertmanager-*/amtool /usr/local/bin/
sudo mkdir -p /etc/alertmanager
```

### 2. Скопировать конфигурацию

```bash
# Alertmanager config
sudo cp deploy/alertmanager.yml /etc/alertmanager/alertmanager.yml

# Email templates
sudo mkdir -p /etc/alertmanager/templates
sudo cp deploy/alertmanager/templates/email.tmpl /etc/alertmanager/templates/

# Alert rules для Prometheus
sudo cp deploy/prometheus/alerts/*.yml /etc/prometheus/alerts/
```

### 3. Обновить Prometheus config

В `/etc/prometheus/prometheus.yml` должно быть:

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - localhost:9093

rule_files:
  - "alerts/*.yml"
```

Перезапустить Prometheus:
```bash
sudo systemctl restart prometheus
```

### 4. Настроить notification channels

#### Email (SMTP)

Отредактировать `alertmanager.yml`:
```yaml
global:
  smtp_smarthost: 'smtp.gmail.com:587'
  smtp_from: 'alerts@your-domain.com'
  smtp_auth_username: 'your-email@gmail.com'
  smtp_auth_password: 'your-app-password'  # Gmail App Password
```

#### Slack

1. Создать Incoming Webhook: https://api.slack.com/messaging/webhooks
2. Добавить в `alertmanager.yml`:
```yaml
slack_configs:
  - api_url: 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK'
    channel: '#alerts'
```

#### PagerDuty

1. Создать Service Integration: https://support.pagerduty.com/docs/services-and-integrations
2. Добавить в `alertmanager.yml`:
```yaml
pagerduty_configs:
  - service_key: 'your-pagerduty-integration-key'
```

### 5. Запустить Alertmanager

**Development (local):**
```bash
alertmanager --config.file=deploy/alertmanager.yml --storage.path=/tmp/alertmanager-data
```

**Production (systemd):**
```bash
sudo systemctl enable alertmanager
sudo systemctl start alertmanager
sudo systemctl status alertmanager
```

## Проверка

### 1. Alertmanager UI

Открыть: http://localhost:9093

- **Alerts**: текущие активные alerts
- **Silences**: временное отключение alerts
- **Status**: конфигурация и статус receivers

### 2. Prometheus Alerts

Открыть: http://localhost:9090/alerts

Должны быть видны все alert rules из `alerts/*.yml`

**Статусы:**
- **Inactive**: условие не выполнено
- **Pending**: условие выполнено, но `for` duration ещё не истёк
- **Firing**: alert активен и отправлен в Alertmanager

### 3. Тестовый alert

Вручную остановить collector:
```bash
sudo systemctl stop bybit-collector
```

Через 1 минуту должен сработать `CollectorProcessDown` alert.

### 4. Проверить notification

```bash
# Проверить Alertmanager logs
sudo journalctl -u alertmanager -f

# Проверить что alert был отправлен
curl http://localhost:9093/api/v2/alerts
```

## Silence alerts

Временно отключить alerts (например, во время maintenance):

**Через UI:**
1. http://localhost:9093/#/silences
2. New Silence
3. Выбрать matcher (например: `alertname="CollectorProcessDown"`)
4. Установить duration
5. Create

**Через CLI:**
```bash
# Silence all alerts на 1 час
amtool silence add alertname=~".+" --duration=1h --comment="Maintenance window"

# Silence конкретный alert
amtool silence add alertname="CollectorProcessDown" --duration=30m

# Silence по component
amtool silence add component="collector" --duration=1h

# List active silences
amtool silence query

# Expire silence
amtool silence expire <silence-id>
```

## Tuning alert thresholds

Если alerts слишком шумные или наоборот не срабатывают:

### 1. Adjust thresholds

Отредактировать `deploy/prometheus/alerts/*.yml`:

```yaml
# Было: срабатывает при >5 trades/sec
expr: rate(collector_trades_received_total[5m]) < 5

# Стало: срабатывает при >1 trade/sec
expr: rate(collector_trades_received_total[5m]) < 1
```

### 2. Adjust `for` duration

```yaml
# Было: срабатывает после 3 минут
for: 3m

# Стало: срабатывает после 1 минуты
for: 1m
```

### 3. Change severity

```yaml
# Было: warning
severity: warning

# Стало: info (меньше notifications)
severity: info
```

Перезагрузить Prometheus:
```bash
sudo systemctl reload prometheus
```

## Troubleshooting

### Alerts не отправляются

**Проблема:** Alerts видны в Prometheus, но не приходят notifications

**Решение:**
1. Проверить что Alertmanager запущен: `systemctl status alertmanager`
2. Проверить Prometheus → Alertmanager connection: http://localhost:9090/targets
3. Проверить Alertmanager logs: `sudo journalctl -u alertmanager -f`
4. Проверить SMTP credentials в `alertmanager.yml`

### Email не приходят

**Проблема:** Alertmanager logs показывают "550 Authentication required"

**Решение для Gmail:**
1. Включить 2FA: https://myaccount.google.com/security
2. Создать App Password: https://myaccount.google.com/apppasswords
3. Использовать App Password в `smtp_auth_password`

### Слишком много alerts

**Проблема:** Alert fatigue — слишком много уведомлений

**Решение:**
1. Увеличить `for` duration для non-critical alerts
2. Увеличить `repeat_interval` в `alertmanager.yml`
3. Использовать `inhibit_rules` чтобы подавить redundant alerts
4. Понизить severity некоторых alerts (warning → info)

### Alerts срабатывают ложно

**Проблема:** Alerts срабатывают когда проблем нет

**Решение:**
1. Увеличить thresholds в alert rules
2. Увеличить `for` duration (дать больше времени на восстановление)
3. Использовать `avg_over_time()` или `max_over_time()` вместо `rate()`

## Best Practices

1. **Actionable alerts only**: Каждый alert должен требовать конкретного действия
2. **Clear runbooks**: В `annotations.description` указывать что делать
3. **Severity discipline**: Critical = нужно проснуться ночью, Warning = проверить утром
4. **Test alerts**: Регулярно проверять что alerts работают
5. **Review & tune**: Пересматривать thresholds на основе false positives
6. **Document silences**: Всегда указывать reason при создании silence

## Следующие шаги

1. **Этап 5.2:** Distributed tracing (Jaeger)
2. **Этап 5.3:** Performance optimization
3. **Runbooks:** Создать документацию с действиями для каждого alert
