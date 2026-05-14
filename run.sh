#!/usr/bin/env bash
set -e
set +e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Detect local IP
LOCAL_IP=$(ip route get 8.8.8.8 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)
if [ -z "$LOCAL_IP" ]; then
  LOCAL_IP=$(hostname -I | awk '{print $1}')
fi

# Load .env if present
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

export JUKEBOX_PASSWORD="${JUKEBOX_PASSWORD:-host}"
export YOUTUBE_API_KEY="${YOUTUBE_API_KEY:-}"

echo ""
echo "========================================="
echo "  PartyQueue startet..."
echo "========================================="
echo ""
echo "  Gaeste:  http://${LOCAL_IP}:5000/"
echo "  TV:      http://${LOCAL_IP}:5000/tv"
echo "  Host:    http://${LOCAL_IP}:5000/host"
echo ""
echo "  Passwort: ${JUKEBOX_PASSWORD}"
echo "========================================="
echo ""

# Create venv if missing
if [ ! -d ".venv" ]; then
  echo "Erstelle virtuelle Umgebung..."
  python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Install dependencies if missing
python3 -c "import flask" 2>/dev/null || pip install flask --quiet
python3 -c "import qrcode" 2>/dev/null || pip install qrcode --quiet
python3 -c "import PIL" 2>/dev/null || pip install pillow --quiet
python3 -c "import yt_dlp" 2>/dev/null || pip install yt-dlp --quiet

python3 app.py
