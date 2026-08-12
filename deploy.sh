#!/bin/bash
#
# Quick deploy script для Bybit Order Flow Platform
#
# Usage:
#   ./deploy.sh          # Deploy to current directory
#   ./deploy.sh /opt/bybit-chart  # Deploy to specific path
#

set -e

DEPLOY_DIR="${1:-.}"
cd "$DEPLOY_DIR"

echo "=== Bybit Order Flow Platform Deployment ==="
echo "Deploy directory: $(pwd)"
echo ""

# 1. Check prerequisites
echo "[1/6] Checking prerequisites..."
command -v python3 >/dev/null 2>&1 || { echo "Python 3 required"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm required"; exit 1; }
echo "✓ Prerequisites OK"

# 2. Pull latest code
echo ""
echo "[2/6] Pulling latest code..."
if [ -d .git ]; then
    git pull origin main
    COMMIT=$(git rev-parse --short HEAD)
    echo "✓ Updated to commit $COMMIT"
else
    echo "⚠ Not a git repo, skipping pull"
fi

# 3. Setup Python environment
echo ""
echo "[3/6] Setting up Python environment..."
if [ ! -d .venv ]; then
    python3 -m venv .venv
    echo "✓ Created virtual environment"
fi
source .venv/bin/activate
pip install -q -r requirements.txt
echo "✓ Python dependencies installed"

# 4. Build frontend
echo ""
echo "[4/6] Building frontend..."
cd web
npm install --silent
npm run build
cd ..
echo "✓ Frontend built to web/dist/"

# 5. Check API health
echo ""
echo "[5/6] Starting API server..."
pkill -f "uvicorn packages.api.app" || true
sleep 1
python -m uvicorn packages.api.app:app --host 127.0.0.1 --port 8000 > /tmp/bybit-api.log 2>&1 &
API_PID=$!
echo "✓ API started (PID: $API_PID)"

sleep 3
if curl -s http://localhost:8000/health > /dev/null; then
    echo "✓ API health check passed"
else
    echo "✗ API health check failed"
    tail -20 /tmp/bybit-api.log
    exit 1
fi

# 6. Summary
echo ""
echo "[6/6] Deployment complete!"
echo ""
echo "Services:"
echo "  API:      http://localhost:8000"
echo "  Health:   http://localhost:8000/health"
echo "  Metrics:  http://localhost:8000/metrics"
echo ""
echo "Frontend build: web/dist/"
echo ""
echo "Next steps:"
echo "  1. Configure Nginx to serve web/dist/ and proxy /api to :8000"
echo "  2. Setup systemd service (see DEPLOY.md)"
echo "  3. Enable HTTPS with certbot"
echo ""
echo "API logs: tail -f /tmp/bybit-api.log"
