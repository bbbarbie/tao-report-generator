@echo off
REM Double-click this file to start the TAO Monthly Report Generator.
cd /d "%~dp0"

if not exist .venv (
  echo Setting up for first use - this takes a minute...
  python -m venv .venv || goto :nopython
  .venv\Scripts\pip install --quiet --upgrade pip
  .venv\Scripts\pip install --quiet -r requirements.txt
)

echo Opening the report generator in your browser...
.venv\Scripts\streamlit run ui.py
goto :eof

:nopython
echo Python 3 is required. Install it from python.org and try again.
pause
