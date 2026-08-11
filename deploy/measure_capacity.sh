#!/bin/bash
# Capacity measurement script — Roadmap §6.8 requirement
# Запускать после 24 часов непрерывного сбора данных

set -e

# Сменить директорию чтобы избежать "Permission denied" при sudo -u bybit
cd /tmp

DATA_DIR="${1:-/opt/bybit-chart/data}"
DURATION_HOURS="${2:-24}"

if [ ! -d "$DATA_DIR" ]; then
    echo "ERROR: Data directory not found: $DATA_DIR" >&2
    exit 1
fi

echo "========================================="
echo "Bybit Collector Capacity Measurement"
echo "Roadmap §6.8 — ${DURATION_HOURS}-hour baseline"
echo "========================================="
echo ""
echo "Measurement window: ${DURATION_HOURS} hours"
echo "Ended: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Общий размер data/
TOTAL_BYTES=$(du -sb "$DATA_DIR" 2>/dev/null | awk '{print $1}')
TOTAL_MB=$((TOTAL_BYTES / 1024 / 1024))
TOTAL_GB=$(awk "BEGIN {printf \"%.2f\", $TOTAL_MB / 1024}")

echo "=== Total Data Volume ==="
echo "Total size: ${TOTAL_MB} MB (${TOTAL_GB} GB)"
echo ""

# Breakdown по символам
echo "=== Per-Symbol Breakdown ==="
for symbol in BTCUSDT ETHUSDT XRPUSDT; do
    SIZE=$(find "$DATA_DIR" -path "*${symbol}*" -type f 2>/dev/null | xargs du -cb 2>/dev/null | tail -1 | awk '{print $1}')
    SIZE="${SIZE:-0}"
    SIZE_MB=$((SIZE / 1024 / 1024))
    SIZE_GB=$(awk "BEGIN {printf \"%.2f\", $SIZE_MB / 1024}")
    echo "  ${symbol}: ${SIZE_MB} MB (${SIZE_GB} GB)"
done
echo ""

# Breakdown по типу события
echo "=== Per-EventType Breakdown ==="
for event_type in publicTrade orderbook; do
    SIZE=$(find "$DATA_DIR" -path "*${event_type}*" -type f 2>/dev/null | xargs du -cb 2>/dev/null | tail -1 | awk '{print $1}')
    SIZE="${SIZE:-0}"
    SIZE_MB=$((SIZE / 1024 / 1024))
    echo "  ${event_type}: ${SIZE_MB} MB"
done
echo ""

# Файловая статистика
echo "=== File Statistics ==="
PARQUET_COUNT=$(find "$DATA_DIR" -name "*.parquet" -type f 2>/dev/null | wc -l)
WAL_COUNT=$(find "$DATA_DIR" -name "*.wal" -type f 2>/dev/null | wc -l)
MANIFEST_COUNT=$(find "$DATA_DIR" -name "manifest.json" -type f 2>/dev/null | wc -l)

echo "  Parquet files: ${PARQUET_COUNT}"
echo "  WAL files: ${WAL_COUNT}"
echo "  Manifests: ${MANIFEST_COUNT}"
echo ""

# Throughput calculation
BYTES_PER_HOUR=$((TOTAL_BYTES / DURATION_HOURS))
MB_PER_HOUR=$((BYTES_PER_HOUR / 1024 / 1024))
GB_PER_DAY=$(awk "BEGIN {printf \"%.2f\", $MB_PER_HOUR * 24 / 1024}")

echo "=== Throughput ==="
echo "Rate: ${MB_PER_HOUR} MB/hour"
echo "Rate: ${GB_PER_DAY} GB/day"
echo ""

# Compression ratio estimate (~5x vs raw JSON)
RAW_ESTIMATE_GB=$(awk "BEGIN {printf \"%.1f\", $GB_PER_DAY * 5}")
echo "=== Compression Efficiency ==="
echo "Estimated raw JSON: ~${RAW_ESTIMATE_GB} GB/day"
echo "Actual Parquet: ${GB_PER_DAY} GB/day"
echo ""

# Capacity projections
echo "=== Capacity Projections ==="
GB_30D=$(awk "BEGIN {printf \"%.1f\", $GB_PER_DAY * 30}")
echo "30-day raw retention: ${GB_30D} GB"

GB_30D_WITH_DERIVED=$(awk "BEGIN {printf \"%.1f\", $GB_30D * 1.5}")
echo "With derived data (+50%): ${GB_30D_WITH_DERIVED} GB"

GB_30D_WITH_WORKING=$(awk "BEGIN {printf \"%.1f\", $GB_30D_WITH_DERIVED * 1.2}")
echo "With working space (+20%): ${GB_30D_WITH_WORKING} GB"

GB_30D_WITH_RESERVE=$(awk "BEGIN {printf \"%.0f\", $GB_30D_WITH_WORKING * 1.43}")
echo "With 30% reserve (required): ${GB_30D_WITH_RESERVE} GB"

# Округлить до ближайших 50 GB
RECOMMENDED_DISK=$(awk "BEGIN {x=$GB_30D_WITH_RESERVE; print int(x/50+1)*50}")
echo ""
echo "========================================="
echo "RECOMMENDATION"
echo "========================================="
echo "Minimum disk for 30-day retention: ${RECOMMENDED_DISK} GB NVMe"
echo ""
echo "Notes:"
echo "- This assumes current feed scope (publicTrade only)"
echo "- Adding orderbook feeds will increase by 3-5x"
echo "- Adding RPI/kline will increase by 1.5-2x"
echo "- PostgreSQL requires additional space (+10-20 GB)"
echo "- Backup volume should match data volume"
echo ""

# Feed scope
echo "=== Current Feed Scope ==="
journalctl -u bybit-collector@BTCUSDT -n 20 2>/dev/null | grep -i "subscribe\|publicTrade\|orderbook" | tail -5 || \
journalctl -u bybit-collector -n 20 2>/dev/null | grep -i "subscribe\|publicTrade\|orderbook" | tail -5 || \
  echo "  (journalctl not accessible — check manually)"
echo ""

# Disk health
echo "=== Current Disk Status ==="
df -h "$DATA_DIR" 2>/dev/null | tail -1 | awk '{print "  Used: " $3 " / " $2 " (" $5 " used, " $4 " free)"}'
FREE_PERCENT=$(df "$DATA_DIR" 2>/dev/null | tail -1 | awk '{gsub(/%/,"",$5); print 100 - $5}')
if [ -n "$FREE_PERCENT" ] && [ "$FREE_PERCENT" -lt 30 ]; then
    echo "  WARNING: Free space below 30% threshold!"
else
    echo "  Disk reserve OK (${FREE_PERCENT}% free)"
fi
echo ""

echo "========================================="
echo "Report generated: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Save this output for Capacity ADR-017"
echo "========================================="
