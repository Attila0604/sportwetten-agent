#!/bin/bash
echo "🚀 Sportwetten KI Multi-Agent v2.0 — IONOS Setup"
echo "=================================================="

echo "1️⃣  Python prüfen..."
python3 --version || { echo "❌ Python3 fehlt: sudo apt install python3 python3-pip"; exit 1; }

echo "2️⃣  Dependencies installieren..."
pip3 install -r requirements.txt && echo "✅ OK"

echo "3️⃣  Ordner erstellen..."
mkdir -p data static && echo "✅ OK"

echo "4️⃣  .env einrichten..."
[ ! -f .env ] && cp .env.example .env && echo "➡  Bitte ausfüllen: nano .env" || echo "✅ .env vorhanden"

echo "5️⃣  Systemd Service..."
WDIR=$(pwd)
PY=$(which python3)
cat > /tmp/betting-agent.service << EOF
[Unit]
Description=Sportwetten KI Multi-Agent
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WDIR
ExecStart=$PY main.py
Restart=always
RestartSec=10
EnvironmentFile=$WDIR/.env

[Install]
WantedBy=multi-user.target
EOF
sudo cp /tmp/betting-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable betting-agent
echo "✅ Service erstellt"

echo ""
echo "=================================================="
echo "✅ Setup fertig! Nächste Schritte:"
echo ""
echo "  1. nano .env              (API Keys eintragen)"
echo "  2. python setup_google_drive.py  (Google Drive einrichten)"
echo "  3. sudo systemctl start betting-agent"
echo ""
echo "Dashboard: http://$(curl -s ifconfig.me 2>/dev/null || echo 'DEINE-IP'):8000"
echo "Logs:      sudo journalctl -u betting-agent -f"
echo "=================================================="
