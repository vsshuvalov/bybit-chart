# Bybit Order Flow Platform — Production Deploy

Этот документ описывает деплой на production сервер.

---

## Архитектура Production

```
┌─────────────────────────────────────────────────────────┐
│ Production Server                                        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Nginx (reverse proxy)                                  │
│    ├─→ /api/*  → FastAPI backend (:8000)                │
│    └─→ /*      → Vite frontend (static build)           │
│                                                          │
│  Backend Services:                                       │
│    ├─→ market-collector (WebSocket → Parquet)           │
│    ├─→ orderflow-worker (analytics pipeline)            │
│    ├─→ api-server (REST API + WebSocket)                │
│    └─→ supervisor (process management)                  │
│                                                          │
│  Storage:                                                │
│    ├─→ /opt/bybit-chart/data/ (Parquet files)           │
│    └─→ PostgreSQL (drawings/workspaces — TODO)          │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Clone repo на сервере

```bash
ssh user@your-server
cd /opt
git clone https://github.com/yourusername/bybit-chart.git
cd bybit-chart
```

### 2. Setup Python environment

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Build frontend

```bash
cd web
npm install
npm run build
# Output: web/dist/
```

### 4. Configure Nginx

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Frontend (static files)
    location / {
        root /opt/bybit-chart/web/dist;
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 5. Start services

```bash
# Market collector
python -m uvicorn packages.api.app:app --host 127.0.0.1 --port 8000 &

# TODO: Add systemd services for all workers
```

---

## Systemd Services

Create `/etc/systemd/system/bybit-api.service`:

```ini
[Unit]
Description=Bybit Chart API Server
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/bybit-chart
Environment="PATH=/opt/bybit-chart/.venv/bin"
ExecStart=/opt/bybit-chart/.venv/bin/python -m uvicorn packages.api.app:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable bybit-api
sudo systemctl start bybit-api
sudo systemctl status bybit-api
```

---

## Environment Variables

Create `/opt/bybit-chart/.env`:

```bash
# Data storage
DATA_DIR=/opt/bybit-chart/data

# Bybit API (if collecting live data)
BYBIT_API_KEY=your_api_key
BYBIT_API_SECRET=your_api_secret

# PostgreSQL (для persistence)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=bybit_chart
POSTGRES_USER=bybit
POSTGRES_PASSWORD=strong_password

# Redis (для IPC)
REDIS_URL=redis://localhost:6379/0
```

---

## Security Checklist

- [ ] Nginx HTTPS (certbot)
- [ ] Firewall (ufw): только 80/443
- [ ] Non-root user для services
- [ ] .env secrets (не в git)
- [ ] Rate limiting (nginx)
- [ ] CORS настроен правильно
- [ ] PostgreSQL authentication
- [ ] Backup strategy (Parquet + DB)

---

## Monitoring

### Logs

```bash
# API logs
sudo journalctl -u bybit-api -f

# Nginx logs
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

### Metrics

- Prometheus: http://your-server:9090
- Grafana: http://your-server:3000
- API metrics: http://your-server/api/metrics

---

## Update Procedure

```bash
cd /opt/bybit-chart
git pull origin main

# Rebuild frontend
cd web
npm install
npm run build

# Restart services
sudo systemctl restart bybit-api

# Check status
sudo systemctl status bybit-api
curl http://localhost:8000/health
```

---

## Rollback

```bash
cd /opt/bybit-chart
git log --oneline -10
git checkout <previous-commit>

# Rebuild + restart
cd web && npm run build
sudo systemctl restart bybit-api
```

---

## Current Status (Этап 7, коммит f51ae1e)

**Working:**
- ✅ Frontend: React + TypeScript + Vite (готов к production build)
- ✅ Backend API: 10+ endpoints (trades, OHLC, analytics)
- ✅ Shell layout: TopBar, LeftToolbar, ChartPanel, Sidebars, StatusBar
- ✅ Mock data: работает без live collector

**TODO после деплоя:**
- [ ] WebSocket live updates
- [ ] Persistence API endpoints (/api/v1/drawings, /workspaces)
- [ ] Drawings canvas interaction (14 инструментов)
- [ ] PostgreSQL для persistence
- [ ] Live market collector
- [ ] Systemd services для всех workers

---

## Next Steps

1. **Deploy на сервер** — скопировать код, build frontend, запустить API
2. **Проверить в браузере** — открыть http://your-server
3. **Продолжить разработку на сервере** — git pull, edit, commit, push
4. **Добавить systemd services** — автозапуск при reboot
5. **Setup PostgreSQL** — для drawings/workspaces persistence
6. **Enable HTTPS** — certbot для SSL
