# Workers — Multi-process Architecture

**Roadmap §3:** Изолированные процессы для crash isolation и independent scaling.

## Architecture

```
┌─────────────────────────────────────┐
│         supervisor.py               │
│  Process management & monitoring    │
└──────────────┬──────────────────────┘
               ↓ manages
┌──────────────────────────────────────────────────┐
│  collector_worker.py                             │
│  WebSocket → WAL → Parquet                       │
│  Publishes events via IPC                        │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│  analytics_worker.py                             │
│  Parquet → Analytics (Delta, CVD, VWAP, etc.)    │
│  Subscribes to IPC events                        │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│  api_server.py                                   │
│  REST API + WebSocket                            │
│  Requests data from analytics via IPC            │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│  maintenance_worker.py (TODO)                    │
│  WAL → Parquet + cleanup                         │
└──────────────────────────────────────────────────┘
```

## IPC Communication

**Unix Domain Sockets:**
- `/tmp/bybit-collector.sock` — collector worker
- `/tmp/bybit-analytics.sock` — analytics worker (TODO)
- `/tmp/bybit-api.sock` — API server (TODO)
- `/tmp/bybit-maintenance.sock` — maintenance worker (TODO)

**Process Registry:**
- `/tmp/bybit-registry/` — process discovery
  - `collector.socket` → socket path
  - `analytics.socket` → socket path
  - `api.socket` → socket path

## Quick Start

### Option 1: Supervisor (Recommended)

```bash
# Start all workers via supervisor
python workers/supervisor.py
```

Supervisor will:
- Start collector worker
- Monitor health via IPC
- Restart on crashes (up to 5 times)
- Graceful shutdown on SIGTERM

### Option 2: Manual (Development)

```bash
# Terminal 1: Start collector worker
python workers/collector_worker.py data BTCUSDT,ETHUSDT,XRPUSDT

# Terminal 2: Start analytics worker
python workers/analytics_worker.py data

# Terminal 3: Start API server
python workers/api_server.py
```

## Worker Details

### collector_worker.py

**Purpose:** Collect data from Bybit WebSocket

**Responsibilities:**
- Subscribe to public trades + L50 book
- Write to WAL
- Publish events via IPC
- Health checks via UDS

**Arguments:**
- `data_dir` — data directory (default: `data/`)
- `symbols` — comma-separated list (default: `BTCUSDT,ETHUSDT,XRPUSDT`)

**IPC Messages:**
- Publishes: `event` — new trade/book update
- Handles: `health` — health check request
- Handles: `request` — get_symbols, get_stats

**Health Check:**
```python
from packages.ipc import UDSClient, IPCMessage
from pathlib import Path

client = UDSClient(Path("/tmp/bybit-collector.sock"), "test")
await client.connect()

health_msg = IPCMessage(
    message_type="health",
    payload={},
    source="test",
)

response = await client.send_message(health_msg)
print(response.payload)
# {"status": "healthy", "process": "collector-worker", "symbols": [...]}
```

### analytics_worker.py

**Purpose:** Calculate analytics indicators

**Responsibilities:**
- Read Parquet segments (read-only)
- Calculate Delta, CVD, VWAP, Volume Profile
- Handle IPC requests from API
- Subscribe to IPC events from collector
- Cache engines per symbol

**Arguments:**
- `data_dir` — data directory (default: `data/`)

**IPC Messages:**
- Handles: `health` — health check request
- Handles: `request` — get_delta, get_vwap, get_volume_profile, get_symbols
- Handles: `event` — new_segment notification (invalidate cache)

**Request Examples:**
```python
# Get Delta
request = IPCMessage(
    message_type="request",
    payload={
        "type": "get_delta",
        "symbol": "BTCUSDT",
        "start_ts": 1234567890000000,
        "end_ts": 1234567900000000,
        "interval_us": 60_000_000,  # 1 minute
    },
    source="api",
)

response = await client.send_message(request)
# {"bars": [...], "count": 10}

# Get VWAP
request = IPCMessage(
    message_type="request",
    payload={
        "type": "get_vwap",
        "symbol": "BTCUSDT",
        "start_ts": 1234567890000000,
        "end_ts": 1234567900000000,
        "interval_us": 60_000_000,
    },
    source="api",
)

# Get Volume Profile
request = IPCMessage(
    message_type="request",
    payload={
        "type": "get_volume_profile",
        "symbol": "BTCUSDT",
        "start_ts": 1234567890000000,
        "end_ts": 1234567900000000,
        "price_tick": 0.01,
    },
    source="api",
)
```

**Health Check:**
```python
client = UDSClient(Path("/tmp/bybit-analytics.sock"), "test")
response = await client.send_message(health_msg)
# {"status": "healthy", "process": "analytics-worker", "cached_engines": {...}}
```

### api_server.py

**Purpose:** REST API + WebSocket server

**Responsibilities:**
- Serve REST API endpoints
- WebSocket real-time updates
- IPC requests to analytics worker for data
- Prometheus metrics export
- Health checks

**Arguments:**
- No arguments (configured in code: host=127.0.0.1, port=8000)

**Endpoints:**
- `GET /health` — health check
- `GET /metrics` — Prometheus metrics
- `GET /api/v1/symbols` — available symbols (via IPC)
- `GET /api/v1/delta` — Delta bars (via IPC)

**IPC Communication:**
- Connects to analytics worker at startup
- Sends request messages
- Receives response messages
- Request timeout: 10s (analytics queries), 5s (symbols)

**Architecture:**
```
HTTP Client → API Server → IPC request → Analytics Worker
                                      ← IPC response
```

**Health Check:**
```bash
curl http://127.0.0.1:8000/health
# {
#   "status": "healthy",
#   "service": "bybit-chart-api-server",
#   "version": "2.0.0",
#   "analytics": "healthy"
# }
```

**API Example:**
```bash
# Get symbols
curl http://127.0.0.1:8000/api/v1/symbols

# Get Delta
curl "http://127.0.0.1:8000/api/v1/delta?symbol=BTCUSDT&start_ts=1234567890000000&end_ts=1234567900000000&interval=1m"
```

## Benefits (Roadmap §3)

✅ **Crash Isolation**
- Analytics crash → collector continues collecting data
- No data loss due to component failures

✅ **Independent Restart**
- Restart analytics without stopping collector
- Zero data collection downtime

✅ **Resource Isolation**
- Each process has own memory limit
- No memory leaks in one process affect others

✅ **Hot Reload**
- Update analytics code without losing WebSocket connection
- Deploy without downtime

✅ **Independent Scaling**
- Scale analytics workers horizontally
- Collector remains single instance per symbol

## Monitoring

### Check Process Status

```bash
# Via supervisor status API (TODO)
curl http://localhost:8000/supervisor/status

# Via IPC health checks
python -c "
import asyncio
from packages.ipc import UDSClient, IPCMessage
from pathlib import Path

async def check():
    client = UDSClient(Path('/tmp/bybit-collector.sock'), 'monitor')
    await client.connect()
    msg = IPCMessage(message_type='health', payload={}, source='monitor')
    response = await client.send_message(msg)
    print(response.payload)
    await client.close()

asyncio.run(check())
"
```

### Logs

Each worker logs to stdout/stderr. Supervisor captures logs.

```bash
# Collector logs
tail -f /var/log/bybit-chart/collector.log

# Supervisor logs
tail -f /var/log/bybit-chart/supervisor.log
```

## Troubleshooting

**Worker не запускается:**
```bash
# Check socket permissions
ls -la /tmp/bybit-*.sock

# Check registry
ls -la /tmp/bybit-registry/

# Clean up stale sockets
rm /tmp/bybit-*.sock
rm -rf /tmp/bybit-registry/
```

**Health check timeout:**
- Worker может быть overloaded
- Check CPU/memory usage
- Increase health check timeout in supervisor

**Worker keeps restarting:**
- Check logs for errors
- Verify data directory exists and is writable
- Check network connectivity (for collector)

## Production Deployment

### systemd Service

```ini
[Unit]
Description=Bybit Chart Supervisor
After=network.target

[Service]
Type=simple
User=bybit
WorkingDirectory=/opt/bybit-chart
ExecStart=/opt/bybit-chart/.venv/bin/python workers/supervisor.py
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

### Docker Compose (TODO)

```yaml
services:
  collector:
    build: .
    command: python workers/collector_worker.py
    volumes:
      - ./data:/data
      - /tmp/bybit-registry:/tmp/bybit-registry

  analytics:
    build: .
    command: python workers/analytics_worker.py
    volumes:
      - ./data:/data:ro
      - /tmp/bybit-registry:/tmp/bybit-registry
```

## Next Steps

- [ ] Implement analytics_worker.py
- [ ] Implement api_server.py refactored для IPC
- [ ] Implement maintenance_worker.py
- [ ] Add metrics export from supervisor
- [ ] Add log aggregation
- [ ] Add distributed tracing (OpenTelemetry)
