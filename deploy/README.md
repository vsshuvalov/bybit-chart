# Bybit Chart Platform - Production Deployment Guide

## Overview

Production-ready deployment stack для Bybit Chart Platform с Docker, systemd, и monitoring.

## Architecture

```
┌─────────────────────────────────────────┐
│           Nginx (Port 80/443)           │
│  ├─ Static files (Frontend)             │
│  ├─ Reverse proxy → API                 │
│  └─ WebSocket proxy                     │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│        FastAPI Backend (Port 8000)      │
│  ├─ REST API (12 endpoints)             │
│  ├─ WebSocket (/ws/live/{symbol})       │
│  └─ Health check (/health)              │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│          Redis (Port 6379)              │
│  Pub/Sub для real-time updates          │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│       Data Collector (Background)       │
│  WebSocket → EventCollector → Storage   │
└─────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Ubuntu 20.04+ / Debian 11+
- Docker 20.10+
- Docker Compose 1.29+
- 2GB+ RAM
- 10GB+ disk space

### Automated Deployment

```bash
# Clone repository
git clone <repo-url>
cd bybit-chart

# Run deployment script (requires root)
sudo bash deploy/deploy.sh
```

The script will:
1. Install Docker and dependencies
2. Create application user (`bybit`)
3. Copy files to `/opt/bybit-chart`
4. Build Docker images
5. Install systemd service
6. Configure firewall
7. Start services

### Manual Deployment

```bash
# Build images
docker-compose build

# Start services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

## Configuration

### Environment Variables

Create `.env` file in project root:

```bash
# Data directory
DATA_DIR=/data

# Redis
REDIS_URL=redis://redis:6379/0

# Logging
LOG_LEVEL=info

# API
API_HOST=0.0.0.0
API_PORT=8000
```

### Docker Compose

Edit `docker-compose.yml` to customize:

- Ports mapping
- Volume mounts
- Resource limits
- Environment variables

### Nginx

Edit `deploy/nginx.conf` for:

- SSL/TLS certificates (production)
- Custom domain names
- Rate limiting rules
- Cache settings

## Service Management

### Systemd Commands

```bash
# Start service
sudo systemctl start bybit-chart

# Stop service
sudo systemctl stop bybit-chart

# Restart service
sudo systemctl restart bybit-chart

# Check status
sudo systemctl status bybit-chart

# Enable autostart
sudo systemctl enable bybit-chart

# View logs
sudo journalctl -u bybit-chart -f
```

### Docker Commands

```bash
cd /opt/bybit-chart

# View running containers
sudo docker-compose ps

# View logs
sudo docker-compose logs -f

# Restart specific service
sudo docker-compose restart api

# Stop all services
sudo docker-compose down

# Rebuild and restart
sudo docker-compose up -d --build
```

## Monitoring

### Health Checks

```bash
# API health
curl http://localhost:8000/health

# Response:
# {
#   "status": "healthy",
#   "service": "bybit-chart-query-api",
#   "timestamp": 1234567890,
#   "version": "1.0.0",
#   "services": {
#     "redis": "connected",
#     "storage": "ready"
#   }
# }
```

### Container Status

```bash
# Docker health checks
docker ps --format "table {{.Names}}\t{{.Status}}"

# Outputs:
# NAMES              STATUS
# bybit-api          Up 2 hours (healthy)
# bybit-redis        Up 2 hours (healthy)
# bybit-collector    Up 2 hours
# bybit-nginx        Up 2 hours (healthy)
```

### Logs

```bash
# API logs
docker-compose logs -f api

# Collector logs
docker-compose logs -f collector

# Redis logs
docker-compose logs -f redis

# Nginx logs
docker-compose logs -f nginx

# All logs
docker-compose logs -f
```

## Data Persistence

### Volumes

- `redis-data`: Redis persistence (AOF)
- `./data`: Parquet files, WAL segments
- `./logs`: Application logs

### Backup

```bash
# Backup data directory
tar -czf backup-$(date +%Y%m%d).tar.gz /opt/bybit-chart/data

# Restore
tar -xzf backup-20240101.tar.gz -C /opt/bybit-chart/
```

## Security

### Firewall (UFW)

```bash
# Allow HTTP/HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Allow API (if public)
sudo ufw allow 8000/tcp

# Enable firewall
sudo ufw enable
```

### SSL/TLS (Production)

1. Obtain certificates (Let's Encrypt):
```bash
sudo apt install certbot
sudo certbot certonly --standalone -d your-domain.com
```

2. Update `deploy/nginx.conf`:
```nginx
ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
```

3. Restart nginx:
```bash
docker-compose restart nginx
```

### User Permissions

The application runs as `bybit` user (non-root) with:
- Read-only application files
- Write access to `/data` and `/logs`
- Docker group membership

## Performance Tuning

### Resource Limits

Edit `docker-compose.yml`:

```yaml
services:
  api:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 1G
```

### Redis Optimization

For high-frequency trading:

```yaml
redis:
  command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
```

## Troubleshooting

### Services not starting

```bash
# Check Docker status
sudo systemctl status docker

# Check logs
docker-compose logs

# Rebuild
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Redis connection failed

```bash
# Check Redis container
docker ps | grep redis

# Test connection
docker exec -it bybit-redis redis-cli ping

# Restart Redis
docker-compose restart redis
```

### API health check failing

```bash
# Check API logs
docker-compose logs api

# Check if port is accessible
curl http://localhost:8000/health

# Restart API
docker-compose restart api
```

### Disk space issues

```bash
# Check disk usage
df -h

# Clean old Docker images
docker system prune -a

# Clean logs
docker-compose logs --tail=1000 > /tmp/logs-backup.txt
docker-compose down
docker-compose up -d
```

## Upgrading

```bash
cd /opt/bybit-chart

# Pull latest changes
sudo -u bybit git pull

# Rebuild
sudo -u bybit docker-compose build

# Restart with zero downtime
sudo systemctl restart bybit-chart
```

## Support

- Documentation: `docs/`
- Issues: GitHub Issues
- API Reference: `http://localhost:8000/docs`

## License

See `LICENSE` file.
