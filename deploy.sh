#!/bin/bash
# ============================================================
# Job Agent — One-shot deploy script for Linux VPS
# Supports: Ubuntu/Debian (apt) and RHEL/Fedora/CentOS (dnf)
# Run as: sudo bash deploy.sh
# ============================================================

set -euo pipefail

INSTALL_DIR="/opt/jobs-auto"
REPO_URL="https://github.com/larbi-ishak/jobs-auto.git"
LOG_DIR="/var/log/job_agent"
SERVICE_USER="ubuntu"

echo "=========================================="
echo "  Job Agent — VPS Deployment"
echo "=========================================="

# ── Detect package manager ───────────────────────────────────
if command -v dnf &> /dev/null; then
    PKG_MGR="dnf"
    PKG_INSTALL="dnf install -y"
    echo "  Package manager: dnf (RHEL/Fedora/CentOS)"
elif command -v apt-get &> /dev/null; then
    PKG_MGR="apt"
    PKG_INSTALL="apt-get install -y"
    echo "  Package manager: apt-get (Ubuntu/Debian)"
else
    echo "  ERROR: Neither dnf nor apt-get found. Exiting."
    exit 1
fi

# ── 1. System packages ───────────────────────────────────────
echo ""
echo "[1/7] Installing system packages..."
if [ "$PKG_MGR" = "dnf" ]; then
    dnf install -y python3 python3-pip python3-devel git
else
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-pip git
fi

# ── 2. Clone repo ───────────────────────────────────────────
echo ""
echo "[2/7] Cloning repository..."
if [ -d "$INSTALL_DIR" ]; then
    echo "  $INSTALL_DIR exists — pulling latest..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ── 3. Python venv + dependencies ───────────────────────────
echo ""
echo "[3/7] Setting up Python virtual environment..."
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
source "$INSTALL_DIR/venv/bin/activate"
pip install --upgrade pip -q
pip install -r "$INSTALL_DIR/job_agent/requirements.txt" -q
deactivate

# ── 4. .env file ────────────────────────────────────────────
echo ""
echo "[4/7] Checking .env configuration..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    echo ""
    echo "  ⚠️  .env created from template. EDIT IT NOW with your API keys:"
    echo "      nano $INSTALL_DIR/.env"
    echo ""
    echo "  Then re-run this script or start the service manually."
    echo "  Exiting — fill .env first!"
    exit 1
else
    echo "  .env exists ✅"
fi

# ── 5. Log directory ────────────────────────────────────────
echo ""
echo "[5/7] Setting up log directory..."
mkdir -p "$LOG_DIR"

# Create service user if it doesn't exist (dnf systems may not have 'ubuntu')
if id "$SERVICE_USER" &> /dev/null; then
    echo "  User '$SERVICE_USER' exists ✅"
else
    echo "  Creating user '$SERVICE_USER'..."
    useradd -r -s /bin/bash "$SERVICE_USER" 2>/dev/null || true
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$LOG_DIR"

# ── 6. Permissions ──────────────────────────────────────────
echo ""
echo "[6/7] Setting file ownership..."
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ── 7. systemd service ──────────────────────────────────────
echo ""
echo "[7/7] Installing systemd service..."
cp "$INSTALL_DIR/job_agent.service" /etc/systemd/system/job_agent.service
systemctl daemon-reload
systemctl enable job_agent

# ── Log rotation ────────────────────────────────────────────
if [ -f "$INSTALL_DIR/logrotate.conf" ]; then
    cp "$INSTALL_DIR/logrotate.conf" /etc/logrotate.d/job_agent
    echo "  Log rotation installed ✅"
fi

echo ""
echo "=========================================="
echo "  Deployment complete! ✅"
echo "=========================================="
echo ""
echo "  Start:   sudo systemctl start job_agent"
echo "  Status:  sudo systemctl status job_agent"
echo "  Logs:    tail -f $LOG_DIR/service.log"
echo "  Stop:    sudo systemctl stop job_agent"
echo "  Restart: sudo systemctl restart job_agent"
echo ""
echo "  The service will:"
echo "    • Start automatically on boot"
echo "    • Restart automatically on crash (after 15s)"
echo "    • Run the pipeline every 6 hours"
echo ""
