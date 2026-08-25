#!/bin/bash
# Double-click this file to start the TAO Monthly Report Generator.
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "Setting up for first use — this takes a minute…"
  python3 -m venv .venv || { echo "Python 3 is required."; read -r; exit 1; }
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

echo "Opening the report generator in your browser…"
exec ./.venv/bin/streamlit run ui.py
