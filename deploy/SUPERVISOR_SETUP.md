# Process Supervisor для bybit-chart (Этап 4.3)

## Overview

Process supervisor управляет всеми 4 workers в правильном порядке с health monitoring и auto-restart.

## Architecture

```
Supervisor
├─ collector-worker (запускается первым)
├─ orderflow-worker (после collector готов)
├─ analytics-worker (после orderflow готов)
└─ api-server (запускается последним)
```

## Features

- **Dependency ordering**: workers запускаются в правильной последовательности
- **Health monitoring**: UDS health checks каждые 10 секунд
- **Auto-restart**: автоматический restart при сбоях (max 5 restarts/5min)
- **Graceful shutdown**: SIGTERM → wait 10s → SIGKILL если нужно
- **Log aggregation**: все логи в `/tmp/bybit-*.log`
- **Status reporting**: JSON status всех процессов

## Usage

### Development (local)

```bash
# Start all workers
python3 workers/supervisor.py start

# Stop all workers
python3 workers/supervisor.py stop

# Restart all workers
python3 workers/supervisor.py restart

# Check status
python3 workers/supervisor.py status
```

### Production (systemd)

```bash
# Install systemd unit
sudo cp deploy/systemd/bybit-supervisor.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable on boot
sudo systemctl enable bybit-supervisor

# Start
sudo systemctl start bybit-supervisor

# Status
sudo systemctl status bybit-supervisor

# Logs
sudo journalctl -u bybit-supervisor -f

# Stop
sudo systemctl stop bybit-supervisor
```

## Process Management

### Startup sequence

1. **Collector** запускается первым (30s timeout)
2. **Orderflow** запускается после collector ready (30s timeout)
3. **Analytics** запускается после orderflow ready (30s timeout)
4. **API** запускается последним (30s timeout)

Каждый worker ждёт пока UDS socket появится и health check проходит.

### Shutdown sequence

Reverse order: API → Analytics → Orderflow → Collector

1. Send SIGTERM
2. Wait 10 seconds
3. Send SIGKILL if still running

### Auto-restart

Supervisor автоматически перезапускает crashed/unhealthy workers с rate limiting:
- Max 5 restarts в течение 5 минут
- После превышения лимита worker остаётся stopped
- Rate limit сбрасывается через 5 минут

### Health checks

Supervisor проверяет health каждые 10 секунд:

1. Process alive? (`poll()`)
2. UDS socket exists?
3. UDS health check response = "healthy"?

Если любая проверка fails → process unhealthy → auto-restart.

## Configuration

Редактировать `workers/supervisor.py`:

```python
ProcessConfig(
    name="collector",
    command=["python3", "workers/collector_worker.py"],
    socket_path=Path("/tmp/bybit-collector.sock"),
    log_path=Path("/tmp/bybit-collector.log"),
    startup_timeout=30,           # seconds to wait for ready
    health_check_interval=10,     # health check frequency
    restart_on_failure=True,      # enable auto-restart
    max_restarts=5,               # max restarts in window
    restart_window=300,           # restart rate limit window (5min)
)
```

## Logs

Логи всех workers:
```bash
tail -f /tmp/bybit-collector.log
tail -f /tmp/bybit-orderflow.log
tail -f /tmp/bybit-analytics.log
tail -f /tmp/bybit-api.log
```

Supervisor logs (systemd):
```bash
sudo journalctl -u bybit-supervisor -f
```

## Status JSON

```bash
$ python3 workers/supervisor.py status
{
  "collector": {
    "state": "running",
    "pid": 12345,
    "restarts": 0
  },
  "orderflow": {
    "state": "running",
    "pid": 12346,
    "restarts": 0
  },
  "analytics": {
    "state": "running",
    "pid": 12347,
    "restarts": 1
  },
  "api": {
    "state": "running",
    "pid": 12348,
    "restarts": 0
  }
}
```

States:
- `stopped`: процесс не запущен
- `starting`: процесс запускается (waiting for ready)
- `running`: процесс работает и healthy
- `unhealthy`: процесс запущен но health check fails
- `stopping`: процесс останавливается
- `crashed`: процесс умер unexpectedly

## Troubleshooting

### Worker не стартует

**Проблема:** Worker fails to start или crashes immediately

**Решение:**
1. Проверить logs: `tail -100 /tmp/bybit-<worker>.log`
2. Проверить dependencies: нужные libraries установлены?
3. Проверить permissions: worker может писать в data dir?
4. Запустить worker вручную: `python3 workers/<worker>_worker.py`

### Worker restarts слишком часто

**Проблема:** Worker constantly restarting, hit rate limit

**Решение:**
1. Проверить logs для root cause
2. Исправить проблему (bug, config, resources)
3. Увеличить `startup_timeout` если worker медленно запускается
4. Увеличить `max_restarts` если нужно больше попыток

### Health check fails но process работает

**Проблема:** Supervisor считает worker unhealthy хотя он работает

**Решение:**
1. Проверить UDS socket: `ls -la /tmp/bybit-*.sock`
2. Тест health check вручную:
   ```bash
   echo '{"type":"health"}' | socat - UNIX-CONNECT:/tmp/bybit-collector.sock
   ```
3. Увеличить `health_check_interval` если checks слишком частые
4. Проверить что worker реализует health check handler

### Supervisor не останавливает workers

**Проблема:** Workers продолжают работать после `supervisor.py stop`

**Решение:**
1. Проверить что workers handle SIGTERM gracefully
2. Force stop: `pkill -9 -f "workers/.*_worker.py"`
3. Cleanup sockets: `rm -f /tmp/bybit-*.sock`

## Best Practices

1. **Always use supervisor в production** — не запускайте workers вручную
2. **Monitor supervisor logs** — supervisor logs содержат важную диагностику
3. **Set up alerting** — alert если worker restarts слишком часто
4. **Regular log rotation** — `/tmp/bybit-*.log` могут расти большими
5. **Test restart scenarios** — убедитесь что restart работает корректно

## Integration with systemd

Для production используйте systemd для управления supervisor:

```bash
# Start on boot
sudo systemctl enable bybit-supervisor

# Start/stop/restart
sudo systemctl start bybit-supervisor
sudo systemctl stop bybit-supervisor
sudo systemctl restart bybit-supervisor

# Status
sudo systemctl status bybit-supervisor

# Logs
sudo journalctl -u bybit-supervisor -f --since today
```

Systemd перезапустит supervisor если он упадёт (`Restart=always`).

## Alternative: Individual systemd units

Вместо supervisor можно использовать отдельные systemd units для каждого worker:

```bash
# Start all
sudo systemctl start bybit-collector bybit-orderflow bybit-analytics bybit-api

# Stop all
sudo systemctl stop bybit-collector bybit-orderflow bybit-analytics bybit-api
```

Но supervisor проще для development и даёт лучший контроль над dependency ordering.
