#!/bin/bash
# Double-click this file to start the TAO Report Generator.
# The Windows equivalent is "TAO Report Generator.vbs".
cd "$(dirname "$0")" || exit 1

PORT=8501

# Already running? Just open it again.
if ./.venv/bin/python launcher/open_when_ready.py "$PORT" 2 >/dev/null 2>&1; then
  exit 0
fi

if [ ! -x .venv/bin/streamlit ]; then
  echo "Setting up for first use — this takes a few minutes…"
  python3 -m venv .venv || { echo "Python 3.10 or newer is required."; read -r; exit 1; }
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt || { echo "Setup failed."; read -r; exit 1; }
fi

# Open the browser once the server answers, without blocking it.
./.venv/bin/python launcher/open_when_ready.py "$PORT" &

echo "TAO Report Generator is starting. Close this window to stop it."

# Bound to the loopback address: reachable from this computer only.
exec ./.venv/bin/streamlit run ui.py \
  --server.address=127.0.0.1 \
  --server.port="$PORT" \
  --server.headless=true \
  --browser.gatherUsageStats=false \
  --server.fileWatcherType=none
