#!/bin/bash
# Double-click this file to start the TAO Report Generator.
cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/streamlit ]; then
  echo "Setting up for first use — this takes a few minutes…"
  python3 -m venv .venv || { echo "Python 3.10 or newer is required."; read -r; exit 1; }
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt || { echo "Setup failed."; read -r; exit 1; }
fi

PORT=8501
# Bound to the loopback address: reachable from this computer only.
./.venv/bin/streamlit run ui.py \
  --server.address=127.0.0.1 \
  --server.port="$PORT" \
  --server.headless=true \
  --browser.gatherUsageStats=false &

for _ in $(seq 1 90); do
  if curl -sf "http://127.0.0.1:$PORT/_stcore/health" >/dev/null 2>&1; then
    open "http://127.0.0.1:$PORT"
    break
  fi
  sleep 1
done

echo
echo "TAO Report Generator is running. Close this window to stop it."
wait
