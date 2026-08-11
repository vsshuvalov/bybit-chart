#!/bin/bash
# Capacity measurement script — Roadmap §6.8 requirement
# Запускать после 72 часов непрерывного сбора данных

set -e

DATA_DIR="${1:-/opt/bybit-chart/data}"
DURATION_HOURS="${2:-72}"

if [ ! -d "$DATA_DIR" ]; then
    echo "ERROR: Data directory not found: $DATA_DIR" >&2
    exit 1
fi

echo "========================================="
echo "Bybit Collector Capacity Measurement"
echo "Roadmap §6.8 — 72-hour baseline"
echo "========================================="
echo ""
echo "Measurement window: ${DURATION_HOURS} hours"
echo "Started: $(date -d "${DURATION_HOURS} hours ago" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -v-${DURATION_HOURS}H '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo 'N/A')"
echo "Ended: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Общий размер data/
TOTAL_BYTES=$(du -sb "$DATA_DIR" 2>/dev/null | awk '{print $1}')
TOTAL_MB=$((TOTAL_BYTES / 1024 / 1024))
TOTAL_GB=$(echo "scale=2; $TOTAL_MB / 1024" | bc)

echo "=== Total Data Volume ==="
echo "Total size: ${TOTAL_MB} MB (${TOTAL_GB} GB)"
echo ""

# Breakdown по символам
echo "=== Per-Symbol Breakdown ==="
for symbol in BTCUSDT ETHUSDT XRPUSDT; do
    SIZE=$(find "$DATA_DIR" -path "*${symbol}*" -type f -exec du -cb {} + 2>/dev/null | tail -1 | awk '{print $1}' || echo 0)
    SIZE_MB=$((SIZE / 1024 / 1024))
    SIZE_GB=$(echo "scale=2; $SIZE_MB / 1024" | bc)
    echo "  ${symbol}: ${SIZE_MB} MB (${SIZE_GB} GB)"
done
echo ""

# Breakdown по типу события
echo "=== Per-EventType Breakdown ==="
for event_type in publicTrade orderbook; do
    SIZE=$(find "$DATA_DIR" -path "*${event_type}*" -type f -exec du -cb {} + 2>/dev/null | tail -1 | awk '{print $1}' || echo 0)
    SIZE_MB=$((SIZE / 1024 / 1024))
    echo "  ${event_type}: ${SIZE_MB} MB"
done
echo ""

# Файловая статистика
echo "=== File Statistics ==="
PARQUET_COUNT=$(find "$DATA_DIR" -name "*.parquet" -type f | wc -l)
WAL_COUNT=$(find "$DATA_DIR" -name "*.wal" -type f | wc -l)
MANIFEST_COUNT=$(find "$DATA_DIR" -name "manifest.json" -type f | wc -l)

echo "  Parquet files: ${PARQUET_COUNT}"
echo "  WAL files: ${WAL_COUNT}"
echo "  Manifests: ${MANIFEST_COUNT}"
echo ""

# Throughput calculation
BYTES_PER_HOUR=$((TOTAL_BYTES / DURATION_HOURS))
MB_PER_HOUR=$((BYTES_PER_HOUR / 1024 / 1024))
GB_PER_DAY=$(echo "scale=2; $MB_PER_HOUR * 24 / 1024" | bc)

echo "=== Throughput ==="
echo "Rate: ${MB_PER_HOUR} MB/hour"
echo "Rate: ${GB_PER_DAY} GB/day"
echo ""

# Compression ratio estimate
# (assumes raw JSON would be ~5x larger than Parquet)
RAW_ESTIMATE_GB=$(echo "scale=1; $GB_PER_DAY * 5" | bc)
COMPRESSION_RATIO=$(echo "scale=1; $RAW_ESTIMATE_GB / $GB_PER_DAY" | bc)

echo "=== Compression Efficiency ==="
echo "Estimated raw JSON: ~${RAW_ESTIMATE_GB} GB/day"
echo "Actual Parquet: ${GB_PER_DAY} GB/day"
echo "Compression ratio: ~${COMPRESSION_RATIO}x"
echo ""

# Capacity projections
echo "=== Capacity Projections ==="

# 30-day retention (raw committed)
GB_30D=$(echo "scale=1; $GB_PER_DAY * 30" | bc)
echo "30-day raw retention: ${GB_30D} GB"

# Add derived artifacts (estimate +50%)
GB_30D_WITH_DERIVED=$(echo "scale=1; $GB_30D * 1.5" | bc)
echo "With derived data (+50%): ${GB_30D_WITH_DERIVED} GB"

# Add WAL tail, .tmp, compaction (estimate +20%)
GB_30D_WITH_WORKING=$(echo "scale=1; $GB_30D_WITH_DERIVED * 1.2" | bc)
echo "With working space (+20%): ${GB_30D_WITH_WORKING} GB"

# Add 30% free reserve (Roadmap §6.8 requirement)
GB_30D_WITH_RESERVE=$(echo "scale=0; $GB_30D_WITH_WORKING * 1.43" | bc)  # 1/0.7 ≈ 1.43
echo "With 30% reserve (required): ${GB_30D_WITH_RESERVE} GB"

# Round up to next 50GB tier
RECOMMENDED_DISK=$(( (GB_30D_WITH_RESERVE / 50 + 1) * 50 ))

echo ""
echo "========================================="
echo "RECOMMENDATION"
echo "========================================="
echo "Minimum disk for 30-day retention: ${RECOMMENDED_DISK} GB NVMe"
echo ""
echo "Notes:"
echo "- This assumes current feed scope (publicTrade + orderbook.200)"
echo "- Adding L1000/RPI will increase by 2-3x (Roadmap §19 Этап 3)"
echo "- PostgreSQL requires additional space (estimate +10-20 GB)"
echo "- Backup volume should match data volume"
echo ""

# Feed scope detection
echo "=== Current Feed Scope ==="
LATEST_LOG=$(journalctl -u bybit-collector -n 1000 2>/dev/null | grep -i "subscribe\|orderbook\|publicTrade" | tail -5 || echo "N/A")
if [ "$LATEST_LOG" = "N/A" ]; then
    echo "  Unable to detect from journalctl"
    echo "  Manual check: sudo journalctl -u bybit-collector | grep subscribe"
else
    echo "$LATEST_LOG"
fi
echo ""

# Disk health check
echo "=== Current Disk Status ==="
df -h "$DATA_DIR" | tail -1 | awk '{print "  Used: " $3 " / " $2 " (" $5 ")"}'
FREE_PERCENT=$(df "$DATA_DIR" | tail -1 | awk '{print 100 - $5}' | sed 's/%//')
if [ "$FREE_PERCENT" -lt 30 ]; then
    echo "  ⚠️  WARNING: Free space below 30% threshold!"
else
    echo "  ✅ Disk reserve OK (${FREE_PERCENT}% free)"
fi
echo ""

echo "========================================="
echo "Report generated: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Save this output for Capacity ADR"
echo "========================================="
