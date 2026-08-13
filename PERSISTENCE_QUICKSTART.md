# Quick Start: Server Persistence

## 1. Apply Database Migration (5 minutes)

```bash
ssh root@83.147.234.167

# Apply migration
sudo -u postgres psql -d bybit_platform -f /opt/bybit-chart/deploy/postgresql/002_drawings_schema.sql

# Verify
sudo -u postgres psql -d bybit_platform -c "\dt drawings workspaces"
```

Expected output:
```
             List of relations
 Schema |        Name        | Type  |    Owner    
--------+--------------------+-------+-------------
 public | drawings           | table | bybit_user
 public | workspaces         | table | bybit_user
 public | workspace_drawings | table | bybit_user
```

---

## 2. Install Dependencies (2 minutes)

```bash
# На сервере
ssh root@83.147.234.167
cd /opt/bybit-chart
.venv/bin/pip install asyncpg==0.29.0

# Verify
.venv/bin/python -c "import asyncpg; print('OK')"
```

---

## 3. Deploy Updated Code (5 minutes)

```bash
# Локально: commit и push
cd /Users/vs/Desktop/bybit-chart
git add .
git commit -m "Add server persistence for drawings/workspaces (Roadmap §11.3, §11.7)"
git push origin main

# На сервере: pull и restart
ssh root@83.147.234.167
cd /opt/bybit-chart
git pull origin main
systemctl restart bybit-api

# Check logs
journalctl -u bybit-api -n 30 --no-pager | grep -i "persistence\|postgresql"
```

Expected log:
```
PostgreSQL pool created: bybit_platform@localhost:5432
PostgreSQL persistence initialized
Persistence router registered: /api/v1/drawings, /api/v1/workspaces
```

---

## 4. Test API (2 minutes)

```bash
# Create test drawing
curl -X POST http://83.147.234.167/api/v1/drawings \
  -H "Content-Type: application/json" \
  -d '{
    "type": "horizontal",
    "symbol": "BTCUSDT",
    "points": [{"timestamp_us": 1697000000000000, "price_ticks": 50000}],
    "style": {"color": "#00ff00", "width": 2}
  }'

# List drawings
curl http://83.147.234.167/api/v1/drawings?symbol=BTCUSDT

# Create test workspace
curl -X POST http://83.147.234.167/api/v1/workspaces \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Workspace",
    "symbol": "BTCUSDT",
    "timeframe": "15m",
    "layout": {},
    "indicators": []
  }'

# List workspaces
curl http://83.147.234.167/api/v1/workspaces
```

Expected response:
```json
{
  "id": "uuid",
  "type": "horizontal",
  "symbol": "BTCUSDT",
  "points": [...],
  "style": {...},
  "locked": false,
  "hidden": false,
  "created_at": "2026-08-13T...",
  "updated_at": "2026-08-13T..."
}
```

---

## 5. Frontend Integration (5 minutes)

```bash
# Локально: test frontend
cd /Users/vs/Desktop/bybit-chart/web
npm run dev

# Open browser
open http://localhost:5173
```

**Browser console test:**
```javascript
// Test API client
import { listDrawings, createDrawing } from './src/api/persistence'

// List drawings
const result = await listDrawings('BTCUSDT')
console.log('Drawings:', result)

// Create drawing
const drawing = await createDrawing({
  type: 'trendline',
  symbol: 'BTCUSDT',
  points: [
    { timestamp_us: 1697000000000000, price_ticks: 50000 },
    { timestamp_us: 1697001000000000, price_ticks: 51000 }
  ],
  style: { color: '#ff0000', width: 2 }
})
console.log('Created:', drawing)
```

---

## ✅ Success Criteria

- ✅ PostgreSQL tables created (drawings, workspaces, workspace_drawings)
- ✅ API service started без errors
- ✅ Persistence log: "PostgreSQL persistence initialized"
- ✅ POST /api/v1/drawings → 201 Created
- ✅ GET /api/v1/drawings?symbol=BTCUSDT → 200 OK
- ✅ Frontend hooks работают без errors

---

## 🚨 Troubleshooting

### API не запускается

**Check logs:**
```bash
journalctl -u bybit-api -n 50
```

**Common issues:**
- Port 8000 occupied → kill manual process
- PostgreSQL not running → `systemctl start postgresql`
- asyncpg not installed → `pip install asyncpg`

### Migration failed

```bash
# Check PostgreSQL
sudo -u postgres psql -d bybit_platform -c "SELECT version();"

# Re-apply migration
sudo -u postgres psql -d bybit_platform -f /opt/bybit-chart/deploy/postgresql/002_drawings_schema.sql
```

### API returns 500

```bash
# Check persistence initialization
journalctl -u bybit-api | grep "PostgreSQL persistence"

# If failed: check credentials
sudo -u bybit psql -d bybit_platform -c "SELECT 1;"
```

---

**Total time:** ~20 minutes  
**Status:** Ready for production
