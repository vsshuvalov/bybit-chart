# Server Persistence — Drawings & Workspaces

**Status:** ✅ IMPLEMENTED (Roadmap §11.3, §11.7)  
**Date:** 2026-08-13  
**Version:** 1.0.0

---

## Overview

Server-side persistence для drawings и workspaces согласно roadmap requirements:

- ✅ **Server source of truth** — localStorage только для UI cache
- ✅ **schemaVersion tracking** — поддержка migrations
- ✅ **revision counter** — increments on every update
- ✅ **PostgreSQL storage** — JSONB для flexibility
- ✅ **REST API** — GET/POST/PUT/DELETE endpoints
- ✅ **Frontend hooks** — React Query + auto-save
- ✅ **Optimistic updates** — responsive UI

---

## Architecture

```
Frontend (React)
    ↓
React Hooks (usePersistence.ts)
    ↓
API Client (persistence.ts)
    ↓ HTTP
FastAPI (persistence_api.py)
    ↓
PostgreSQL Storage (persistence_postgresql.py)
    ↓
PostgreSQL (drawings, workspaces tables)
```

---

## Database Schema

### Tables

**drawings:**
- `drawing_id` UUID PRIMARY KEY
- `type` VARCHAR(50) — 14 drawing tools
- `symbol` VARCHAR(20)
- `workspace_id` UUID (FK)
- `points` JSONB — [{timestamp_us, price_ticks}, ...]
- `style` JSONB — {color, width, dash, ...}
- `locked` BOOLEAN
- `hidden` BOOLEAN
- `schema_version` INT — для migrations
- `revision` INT — increments on update
- `author` VARCHAR(100)
- `created_at`, `updated_at` TIMESTAMPTZ

**workspaces:**
- `workspace_id` UUID PRIMARY KEY
- `name` VARCHAR(255)
- `symbol` VARCHAR(20)
- `timeframe` VARCHAR(10)
- `layout` JSONB — panel visibility, sizes
- `indicators` JSONB — [{type, params, enabled}, ...]
- `schema_version` INT
- `revision` INT
- `author` VARCHAR(100)
- `is_default` BOOLEAN
- `created_at`, `updated_at` TIMESTAMPTZ

**workspace_drawings:**
- Many-to-many association
- `workspace_id`, `drawing_id` PRIMARY KEY
- `display_order` INT — z-order для rendering

---

## REST API Endpoints

### Drawings

```
GET    /api/v1/drawings?symbol={symbol}&include_hidden={bool}&workspace_id={uuid}
POST   /api/v1/drawings
GET    /api/v1/drawings/{drawing_id}
PUT    /api/v1/drawings/{drawing_id}
DELETE /api/v1/drawings/{drawing_id}
```

### Workspaces

```
GET    /api/v1/workspaces?author={author}
POST   /api/v1/workspaces
GET    /api/v1/workspaces/{workspace_id}
PUT    /api/v1/workspaces/{workspace_id}
DELETE /api/v1/workspaces/{workspace_id}
GET    /api/v1/workspaces/{workspace_id}/drawings
```

---

## Setup

### 1. Apply Database Migration

```bash
# На production сервере
ssh root@83.147.234.167

# Apply migration
sudo -u postgres psql -d bybit_platform -f /opt/bybit-chart/deploy/postgresql/002_drawings_schema.sql

# Verify tables
sudo -u postgres psql -d bybit_platform -c "\dt drawings workspaces workspace_drawings"
```

### 2. Install Python Dependencies

```bash
# Локально
cd /Users/vs/Desktop/bybit-chart
pip install -r requirements.txt

# На сервере
ssh root@83.147.234.167
cd /opt/bybit-chart
.venv/bin/pip install asyncpg==0.29.0
```

### 3. Configure PostgreSQL Connection

```bash
# Environment variables (optional, defaults to localhost)
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=bybit_platform
export POSTGRES_USER=bybit_user
export POSTGRES_PASSWORD=your_password  # или используйте .pgpass
```

### 4. Restart API Service

```bash
ssh root@83.147.234.167

# Restart API server
systemctl restart bybit-api

# Check logs
journalctl -u bybit-api -f
```

Expected log:
```
PostgreSQL pool created: bybit_platform@localhost:5432 (pool: 5-20)
PostgreSQL persistence initialized
Persistence router registered: /api/v1/drawings, /api/v1/workspaces
```

---

## Frontend Usage

### 1. Import API Client

```typescript
import {
  listDrawings,
  createDrawing,
  updateDrawing,
  deleteDrawing,
} from './api/persistence'
```

### 2. Use React Hooks

```typescript
import {
  useDrawings,
  useCreateDrawing,
  useUpdateDrawing,
  useAutoSaveDrawing,
} from './hooks/usePersistence'

function MyComponent() {
  // List drawings
  const { data, isLoading } = useDrawings('BTCUSDT')

  // Create drawing
  const createMutation = useCreateDrawing()
  const handleCreate = () => {
    createMutation.mutate({
      type: 'trendline',
      symbol: 'BTCUSDT',
      points: [
        { timestamp_us: 1234567890000000, price_ticks: 50000 },
        { timestamp_us: 1234567900000000, price_ticks: 51000 },
      ],
      style: { color: '#00ff00', width: 2 },
    })
  }

  // Update drawing (with optimistic update)
  const updateMutation = useUpdateDrawing()
  const handleUpdate = (drawingId: string) => {
    updateMutation.mutate({
      drawingId,
      updates: { locked: true },
    })
  }

  // Auto-save on changes (debounced)
  useAutoSaveDrawing(drawingId, { style: { color: '#ff0000' } }, 500)

  return <div>...</div>
}
```

### 3. Active Workspace Management

```typescript
import { useActiveWorkspace } from './hooks/usePersistence'

function WorkspaceManager() {
  const { workspace, updateLayout, updateIndicators, isSaving } =
    useActiveWorkspace('workspace-uuid')

  const handleLayoutChange = (newLayout: any) => {
    // Auto-saves after 1s debounce
    updateLayout(newLayout)
  }

  return (
    <div>
      <h1>{workspace?.name}</h1>
      {isSaving && <span>Saving...</span>}
    </div>
  )
}
```

---

## Testing

### 1. Backend Tests

```bash
# Test PostgreSQL persistence
pytest tests/api/test_persistence_postgresql.py -v

# Test API endpoints
pytest tests/api/test_persistence_api.py -v
```

### 2. Manual API Testing

```bash
# Create drawing
curl -X POST http://localhost:8000/api/v1/drawings \
  -H "Content-Type: application/json" \
  -d '{
    "type": "horizontal",
    "symbol": "BTCUSDT",
    "points": [{"timestamp_us": 1234567890000000, "price_ticks": 50000}],
    "style": {"color": "#ff0000", "width": 2}
  }'

# List drawings
curl http://localhost:8000/api/v1/drawings?symbol=BTCUSDT

# Create workspace
curl -X POST http://localhost:8000/api/v1/workspaces \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Workspace",
    "symbol": "BTCUSDT",
    "timeframe": "15m",
    "layout": {"leftToolbar": true, "rightSidebar": true},
    "indicators": [{"type": "ema", "params": {"period": 20}}]
  }'

# List workspaces
curl http://localhost:8000/api/v1/workspaces
```

### 3. Frontend Integration Test

```bash
cd web
npm run dev

# Open browser
open http://localhost:5173

# Check browser console for persistence logs:
# [Persistence] Drawing created: uuid
# [Persistence] Drawing auto-saved: uuid
# [Persistence] Workspace updated: uuid
```

---

## Roadmap Compliance

### ✅ Implemented Requirements

**§11.3 — Drawings Persistence:**
- ✅ Server persistence с schemaVersion
- ✅ revision tracking (increments on update)
- ✅ workspace scope
- ✅ symbol scope
- ✅ author tracking
- ✅ locked/hidden state
- ✅ 14 drawing tool types
- ✅ JSONB points, style

**§11.7 — Server Source of Truth:**
- ✅ PostgreSQL storage
- ✅ localStorage НЕ является единственной копией
- ✅ REST API для CRUD
- ✅ Frontend hooks с auto-save
- ✅ Optimistic updates

### 📋 TODO (Next Steps)

**Drawing Tools Logic (§11.3):**
- ⏳ Canvas interaction (onClick, onDrag)
- ⏳ Rendering на графике
- ⏳ Lock/hide/delete UI

**Workspace Management (§11.2):**
- ⏳ Dropdown menu (open, save, create copy)
- ⏳ Export/import JSON

**Schema Versioning:**
- ⏳ Migration scripts для schemaVersion upgrades
- ⏳ Backward compatibility tests

---

## Performance

**PostgreSQL Pool:**
- Min connections: 5
- Max connections: 20
- Auto-reconnect on failure

**Frontend:**
- React Query cache: 30s (drawings), 60s (workspaces)
- Auto-save debounce: 500ms (drawings), 1000ms (workspaces)
- Optimistic updates: instant UI feedback

**Expected Latency:**
- CREATE drawing: ~50ms
- UPDATE drawing: ~30ms
- LIST drawings: ~20ms (cached), ~50ms (cold)

---

## Troubleshooting

### PostgreSQL Connection Failed

```
ERROR: PostgreSQL persistence initialization failed
```

**Solution:**
1. Check PostgreSQL is running: `systemctl status postgresql`
2. Check credentials: `psql -U bybit_user -d bybit_platform -h localhost`
3. Check `.pgpass` file: `~/.pgpass` с правами `600`
4. Check environment variables: `echo $POSTGRES_HOST`

### Migration Failed

```
ERROR: relation "drawings" already exists
```

**Solution:**
- Migration already applied, skip
- To re-apply: `DROP TABLE drawings CASCADE;` затем run migration

### API Returns 500

```
GET /api/v1/drawings → 500 Internal Server Error
```

**Solution:**
1. Check API logs: `journalctl -u bybit-api -n 50`
2. Check persistence initialized: grep "PostgreSQL persistence initialized"
3. Check table exists: `psql -d bybit_platform -c "\d drawings"`

### Frontend Hook Error

```
Error: Persistence not initialized
```

**Solution:**
- API server не запущен или persistence failed
- Check backend logs
- Fallback: hooks return error state, handle gracefully

---

## Files Created

**Backend:**
- `deploy/postgresql/002_drawings_schema.sql` — PostgreSQL schema
- `packages/api/persistence_postgresql.py` — PostgreSQL storage adapter
- `packages/api/persistence_api.py` — REST API endpoints
- `packages/api/persistence_models.py` — Pydantic models (already existed)
- `packages/api/app.py` — Updated with lifespan, persistence router

**Frontend:**
- `web/src/api/persistence.ts` — API client
- `web/src/hooks/usePersistence.ts` — React hooks

**Dependencies:**
- `requirements.txt` — Added `asyncpg==0.29.0`

---

## Next Steps

1. **Apply migration на production** (P0)
2. **Restart API service** (P0)
3. **Test endpoints** (P0)
4. **Implement drawing tools canvas logic** (P1) — see §11.3
5. **Add workspace dropdown menu** (P1) — see §11.2
6. **Write E2E tests** (P2)

---

**Prepared by:** Claude Opus 5  
**Date:** 2026-08-13  
**Status:** Ready for deployment
