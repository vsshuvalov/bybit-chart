#!/bin/bash
# Production deployment script для Bybit Chart Platform
# Roadmap §15: Automated deployment

set -e  # Exit on error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
APP_NAME="bybit-chart"
APP_DIR="/opt/${APP_NAME}"
APP_USER="bybit"
DATA_DIR="${APP_DIR}/data"
LOG_DIR="${APP_DIR}/logs"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Bybit Chart Platform - Deployment${NC}"
echo -e "${GREEN}========================================${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: Please run as root (sudo)${NC}"
    exit 1
fi

# Step 1: Install dependencies
echo -e "\n${YELLOW}[1/8] Installing dependencies...${NC}"
apt-get update
apt-get install -y \
    docker.io \
    docker-compose \
    git \
    curl \
    wget

systemctl enable docker
systemctl start docker

# Step 2: Create user
echo -e "\n${YELLOW}[2/8] Creating application user...${NC}"
if ! id -u ${APP_USER} > /dev/null 2>&1; then
    useradd -r -s /bin/bash -d ${APP_DIR} -m ${APP_USER}
    usermod -aG docker ${APP_USER}
    echo -e "${GREEN}User ${APP_USER} created${NC}"
else
    echo -e "${GREEN}User ${APP_USER} already exists${NC}"
fi

# Step 3: Create directories
echo -e "\n${YELLOW}[3/8] Creating directories...${NC}"
mkdir -p ${APP_DIR}
mkdir -p ${DATA_DIR}
mkdir -p ${LOG_DIR}
chown -R ${APP_USER}:${APP_USER} ${APP_DIR}

# Step 4: Copy application files
echo -e "\n${YELLOW}[4/8] Copying application files...${NC}"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cp -r ${SCRIPT_DIR}/* ${APP_DIR}/
chown -R ${APP_USER}:${APP_USER} ${APP_DIR}

# Step 5: Build Docker images
echo -e "\n${YELLOW}[5/8] Building Docker images...${NC}"
cd ${APP_DIR}
sudo -u ${APP_USER} docker-compose build

# Step 6: Install systemd service
echo -e "\n${YELLOW}[6/8] Installing systemd service...${NC}"
cp ${APP_DIR}/deploy/bybit-chart.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable ${APP_NAME}

# Step 7: Configure firewall (optional)
echo -e "\n${YELLOW}[7/8] Configuring firewall...${NC}"
if command -v ufw &> /dev/null; then
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 8000/tcp
    echo -e "${GREEN}Firewall rules added${NC}"
else
    echo -e "${YELLOW}UFW not installed, skipping firewall configuration${NC}"
fi

# Step 8: Start services
echo -e "\n${YELLOW}[8/8] Starting services...${NC}"
systemctl start ${APP_NAME}

# Wait for services to start
sleep 5

# Check service status
echo -e "\n${YELLOW}Service Status:${NC}"
systemctl status ${APP_NAME} --no-pager

# Check container status
echo -e "\n${YELLOW}Container Status:${NC}"
cd ${APP_DIR}
sudo -u ${APP_USER} docker-compose ps

# Health check
echo -e "\n${YELLOW}Health Check:${NC}"
sleep 10
if curl -f http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ API is healthy${NC}"
else
    echo -e "${RED}✗ API health check failed${NC}"
fi

# Summary
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e ""
echo -e "Application directory: ${APP_DIR}"
echo -e "Data directory: ${DATA_DIR}"
echo -e "Log directory: ${LOG_DIR}"
echo -e ""
echo -e "Services:"
echo -e "  - API: http://localhost:8000"
echo -e "  - Frontend: http://localhost"
echo -e "  - WebSocket: ws://localhost:8000/ws/live/{symbol}"
echo -e ""
echo -e "Management commands:"
echo -e "  Start:   systemctl start ${APP_NAME}"
echo -e "  Stop:    systemctl stop ${APP_NAME}"
echo -e "  Restart: systemctl restart ${APP_NAME}"
echo -e "  Status:  systemctl status ${APP_NAME}"
echo -e "  Logs:    journalctl -u ${APP_NAME} -f"
echo -e ""
echo -e "Docker commands:"
echo -e "  cd ${APP_DIR}"
echo -e "  sudo -u ${APP_USER} docker-compose ps"
echo -e "  sudo -u ${APP_USER} docker-compose logs -f"
echo -e ""
echo -e "${YELLOW}Note: Configure SSL certificates in deploy/nginx.conf for production${NC}"
