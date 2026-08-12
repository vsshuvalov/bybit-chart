#!/bin/bash
# Start all 4 workers для 4-process architecture (Roadmap Этап 4)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Starting 4-process bybit-chart architecture..."
echo "Project root: $PROJECT_ROOT"

# Cleanup old sockets
rm -f /tmp/bybit-*.sock

# Start processes in background
echo ""
echo "[1/4] Starting collector-worker..."
python3 "$PROJECT_ROOT/workers/collector_worker.py" > /tmp/bybit-collector.log 2>&1 &
COLLECTOR_PID=$!
echo "  PID: $COLLECTOR_PID"

sleep 2

echo ""
echo "[2/4] Starting orderflow-worker..."
python3 "$PROJECT_ROOT/workers/orderflow_worker.py" > /tmp/bybit-orderflow.log 2>&1 &
ORDERFLOW_PID=$!
echo "  PID: $ORDERFLOW_PID"

sleep 2

echo ""
echo "[3/4] Starting analytics-worker..."
python3 "$PROJECT_ROOT/workers/analytics_worker.py" > /tmp/bybit-analytics.log 2>&1 &
ANALYTICS_PID=$!
echo "  PID: $ANALYTICS_PID"

sleep 2

echo ""
echo "[4/4] Starting API server..."
cd "$PROJECT_ROOT"
python3 -m uvicorn packages.api.app:app --host 0.0.0.0 --port 8000 > /tmp/bybit-api.log 2>&1 &
API_PID=$!
echo "  PID: $API_PID"

sleep 3

echo ""
echo "All workers started!"
echo ""
echo "PIDs:"
echo "  collector: $COLLECTOR_PID"
echo "  orderflow: $ORDERFLOW_PID"
echo "  analytics: $ANALYTICS_PID"
echo "  api:       $API_PID"
echo ""
echo "Logs:"
echo "  tail -f /tmp/bybit-collector.log"
echo "  tail -f /tmp/bybit-orderflow.log"
echo "  tail -f /tmp/bybit-analytics.log"
echo "  tail -f /tmp/bybit-api.log"
echo ""
echo "To stop all:"
echo "  kill $COLLECTOR_PID $ORDERFLOW_PID $ANALYTICS_PID $API_PID"
echo ""
echo "API: http://localhost:8000"
echo "Metrics: http://localhost:8000/metrics"
echo ""

# Save PIDs to file
echo "$COLLECTOR_PID" > /tmp/bybit-workers.pids
echo "$ORDERFLOW_PID" >> /tmp/bybit-workers.pids
echo "$ANALYTICS_PID" >> /tmp/bybit-workers.pids
echo "$API_PID" >> /tmp/bybit-workers.pids

echo "PIDs saved to /tmp/bybit-workers.pids"
