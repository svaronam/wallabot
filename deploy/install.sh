#!/usr/bin/env bash
# Instala o actualiza Wallabot en la Raspberry Pi.  Uso:  bash deploy/install.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"
cd "$DIR/server"

echo "==> Dependencias del sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip openssl >/dev/null

echo "==> Entorno de Python"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> Configuración"
if [ ! -f .env ]; then
  cp "$DIR/deploy/env.example" .env
fi
if ! grep -q '^WALLABOT_TOKEN=.\+' .env; then
  TOKEN="$(openssl rand -hex 12)"
  sed -i "s/^WALLABOT_TOKEN=.*/WALLABOT_TOKEN=$TOKEN/" .env
fi
mkdir -p data

echo "==> Servicio systemd"
sed -e "s#__USER__#$USER_NAME#g" -e "s#__DIR__#$DIR#g" "$DIR/deploy/wallabot.service" \
  | sudo tee /etc/systemd/system/wallabot.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now wallabot
sudo systemctl restart wallabot
sleep 3

PORT="$(grep '^WALLABOT_PORT=' .env | cut -d= -f2)"
TOKEN="$(grep '^WALLABOT_TOKEN=' .env | cut -d= -f2)"
if curl -fsS "http://127.0.0.1:${PORT:-8788}/api/health" >/dev/null; then
  echo
  echo "✅ Wallabot funcionando"
else
  echo "⚠️  El servicio no responde todavía. Mira:  journalctl -u wallabot -n 50"
fi
TS_NAME="$(hostname)"
echo "   Panel:  http://$TS_NAME:${PORT:-8788}/?token=$TOKEN"
echo "   En la APK pon:  http://$TS_NAME:${PORT:-8788}   y el token  $TOKEN"
