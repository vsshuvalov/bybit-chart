# 24-72h Soak Test (Roadmap Этап 4.4)

## Overview

Soak test проверяет stability 4-process architecture в течение 24-72 часов под реальной нагрузкой.

## Acceptance Criteria (Roadmap §19 Этап 4)

✅ **All processes running**: Все 4 процесса работают без crashes  
✅ **Memory leaks**: < 10% RSS growth за 24h  
✅ **CPU drift**: < 5% deviation от baseline  
✅ **Disk growth**: в пределах 2× baseline (92 MB/24h × 2 = 184 MB/24h)  
✅ **Gap rate**: < 0.1%  
✅ **Crash recovery**: kill/restart проходит успешно  
✅ **Metrics baseline**: CPU/RAM/disk/latency percentiles documented  

## Usage

### 1. Start soak test

```bash
# 24h test
python3 tests/soak/soak_test.py start --duration 24h

# 72h test
python3 tests/soak/soak_test.py start --duration 72h

# Custom output dir
python3 tests/soak/soak_test.py start --duration 24h --output-dir /path/to/results
```

### 2. Monitor progress

Скрипт выводит статус каждую минуту:

```
[2.5h / 24h] Snapshots: 150, Crashes: 0, Remaining: 21.5h
```

Snapshots сохраняются каждые 60 секунд в `tests/soak/results/`.

### 3. Generate report

После завершения теста (или в любой момент):

```bash
python3 tests/soak/soak_test.py report --output-dir tests/soak/results
```

Output:
```json
{
  "verdict": "PASS",
  "processes": {
    "collector": {
      "memory_leak": {
        "status": "pass",
        "growth_percent": 3.2,
        "threshold_percent": 10
      }
    },
    ...
  },
  "system": {
    "disk_growth": {
      "status": "pass",
      "growth_per_24h_mb": 95.3,
      "max_acceptable_mb_per_day": 184
    }
  },
  "crashes": []
}
```

### 4. Stop test early

Press `Ctrl+C` — snapshots будут сохранены автоматически.

## What is Monitored

### Per-Process Metrics

Каждые 60 секунд для каждого процесса:
- **CPU percent**: текущее использование CPU
- **Memory RSS**: resident set size (physical memory)
- **Memory VMS**: virtual memory size
- **Threads**: количество threads
- **File descriptors**: открытых FDs

### System Metrics

Каждые 60 секунд:
- **Disk usage**: total used в data dir
- **Disk free**: available space
- **Total memory**: system RAM
- **Available memory**: free RAM

### Events

- **Crashes**: когда процесс умирает
- **Restarts**: когда supervisor перезапускает процесс

## Output Files

```
tests/soak/results/
├── config.json                 # Test configuration
├── collector_snapshots.json    # Collector metrics over time
├── orderflow_snapshots.json    # Orderflow metrics over time
├── analytics_snapshots.json    # Analytics metrics over time
├── api_snapshots.json          # API metrics over time
├── system_snapshots.json       # System metrics over time
├── crashes.json                # Crash log
└── acceptance_report.json      # Final acceptance report
```

## Analysis

### Memory Leak Detection

Сравнивает first RSS с last RSS:

```python
growth_percent = (last_rss - first_rss) / first_rss * 100
```

**Pass criteria**: `growth_percent < 10%` за 24h

### Disk Growth

Измеряет рост disk usage и экстраполирует на 24h:

```python
growth_per_24h = (last_usage - first_usage) / duration_hours * 24
```

**Pass criteria**: `growth_per_24h < 184 MB` (2× baseline)

### CPU Drift

(TODO) Проверяет что CPU usage стабилен, нет постепенного роста.

**Pass criteria**: `std_dev(cpu_percent) < 5%`

## Running in Production

### Background execution

```bash
# Start in background
nohup python3 tests/soak/soak_test.py start --duration 72h > soak.log 2>&1 &

# Monitor
tail -f soak.log

# Generate report later
python3 tests/soak/soak_test.py report
```

### With systemd

Можно создать systemd unit для automated soak tests:

```ini
[Unit]
Description=Bybit Chart 24h Soak Test

[Service]
Type=simple
WorkingDirectory=/opt/bybit-chart
ExecStart=/opt/bybit-chart/.venv/bin/python3 tests/soak/soak_test.py start --duration 24h
```

### With cron (weekly)

```cron
# Run soak test every Sunday at 00:00
0 0 * * 0 cd /opt/bybit-chart && python3 tests/soak/soak_test.py start --duration 24h
```

## Interpreting Results

### PASS

All criteria met:
- No excessive memory growth
- Disk growth в пределах baseline × 2
- < 5 crashes (manual testing allowed)

**Action**: Proceed to next Roadmap stage.

### FAIL: Memory Leak

**Symptoms:**
```json
"memory_leak": {
  "status": "fail",
  "growth_percent": 25.3,
  "threshold_percent": 10
}
```

**Actions:**
1. Check logs для memory allocation patterns
2. Use memory profiler: `python3 -m memory_profiler workers/collector_worker.py`
3. Look for:
   - Unbounded caches
   - Event buffers without size limits
   - Circular references
   - File handles not closed

### FAIL: Disk Growth

**Symptoms:**
```json
"disk_growth": {
  "status": "fail",
  "growth_per_24h_mb": 250,
  "max_acceptable_mb_per_day": 184
}
```

**Actions:**
1. Check WAL commit frequency
2. Check Parquet compression settings
3. Check log rotation
4. Check if maintenance worker running

### FAIL: Crashes

**Symptoms:**
```json
"crashes": [
  {"timestamp": 1234567890, "process": "collector", "error": "..."}
]
```

**Actions:**
1. Check crash logs: `/tmp/bybit-*.log`
2. Identify root cause
3. Fix bug and re-run soak test

## Best Practices

1. **Run on production-like hardware** — same CPU/RAM/disk
2. **Use real data** — не test fixtures, real WebSocket feed
3. **Don't interfere** — minimal manual intervention во время теста
4. **Monitor externally** — используй Prometheus/Grafana для visualization
5. **Document baseline** — save first successful soak test as baseline
6. **Run regularly** — weekly или перед каждым release

## Integration with CI/CD

Можно интегрировать в CI pipeline:

```yaml
# .github/workflows/soak-test.yml
name: Weekly Soak Test

on:
  schedule:
    - cron: '0 0 * * 0'  # Every Sunday

jobs:
  soak-test:
    runs-on: ubuntu-latest
    timeout-minutes: 1500  # 25h
    steps:
      - uses: actions/checkout@v3
      - name: Start workers
        run: python3 workers/supervisor.py start
      - name: Run soak test
        run: python3 tests/soak/soak_test.py start --duration 24h
      - name: Generate report
        run: python3 tests/soak/soak_test.py report
      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: soak-test-results
          path: tests/soak/results/
```

## Troubleshooting

### psutil.NoSuchProcess

**Problem**: Process not found during monitoring

**Solution**: Normal если process crashed. Check crash log.

### Insufficient data

**Problem**: `"status": "insufficient_data"` в report

**Solution**: Test был слишком короткий или процессы не были запущены.

### Disk full

**Problem**: Soak test заполнил disk

**Solution**:
1. Stop test: `Ctrl+C`
2. Cleanup: `rm -rf data/*/wal/*` (old WAL segments)
3. Increase disk или shorten test duration

## Next Steps

После PASS soak test:

1. **Document baseline**: save metrics как reference
2. **Update ADR**: утвердить 4-process architecture
3. **Production deployment**: deploy на production hardware
4. **Roadmap Этап 5**: Continue with next stage
