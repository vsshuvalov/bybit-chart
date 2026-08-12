#!/bin/bash
# Stop all 4 workers

set -e

PID_FILE="/tmp/bybit-workers.pids"

if [ ! -f "$PID_FILE" ]; then
    echo "PID file not found: $PID_FILE"
    echo "Workers may not be running or were started manually."
    exit 1
fi

echo "Stopping all bybit-chart workers..."

while read -r pid; do
    if ps -p "$pid" > /dev/null 2>&1; then
        echo "  Stopping PID $pid..."
        kill "$pid"
    else
        echo "  PID $pid not running"
    fi
done < "$PID_FILE"

sleep 2

# Force kill if still running
while read -r pid; do
    if ps -p "$pid" > /dev/null 2>&1; then
        echo "  Force killing PID $pid..."
        kill -9 "$pid"
    fi
done < "$PID_FILE"

rm -f "$PID_FILE"
echo ""
echo "All workers stopped."
