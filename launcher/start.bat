@echo off
REM Starts the TAO Report Generator and opens it in the browser.
REM Launched by "TAO Report Generator.vbs", which hides the console window,
REM so anything the user needs to see has to be a message box.
setlocal
cd /d "%~dp0.."

set "PORT=8501"
set "PY="

py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  call :say "TAO Report Generator needs Python 3.10 or newer.||Install it from python.org - tick 'Add python.exe to PATH' during setup - then try again."
  exit /b 1
)

REM First run only: build the private environment and install the libraries.
if not exist ".venv\Scripts\streamlit.exe" (
  call :say "Setting up TAO Report Generator.||This happens once and takes a few minutes. You will be told when it is ready."
  %PY% -m venv .venv
  if errorlevel 1 goto :setupfailed
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  if errorlevel 1 goto :setupfailed
)

REM Bound to 127.0.0.1 so the server is reachable only from this computer.
REM Headless, because the browser is opened below once the port answers —
REM Streamlit's own auto-open is unreliable when there is no console.
start "" /b ".venv\Scripts\streamlit.exe" run ui.py ^
  --server.address=127.0.0.1 ^
  --server.port=%PORT% ^
  --server.headless=true ^
  --browser.gatherUsageStats=false

call :waitforport
if errorlevel 1 (
  call :say "The report generator did not start.||Try again, and if it keeps happening send launcher\startup.log to whoever set this up."
  exit /b 1
)

start "" "http://127.0.0.1:%PORT%"
exit /b 0


:waitforport
REM Wait up to ~90 seconds for the server to answer before opening the browser.
for /l %%i in (1,1,90) do (
  ".venv\Scripts\python.exe" -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(s.connect_ex(('127.0.0.1',%PORT%)))" >nul 2>&1
  if not errorlevel 1 exit /b 0
  timeout /t 1 /nobreak >nul
)
exit /b 1

:setupfailed
call :say "Setup could not finish.||Check that this computer can reach the internet to download the libraries, then try again."
exit /b 1

:say
REM No console to print to, so use a message box. '||' becomes a line break.
mshta "javascript:var m='%~1'.split('||').join('\n');new ActiveXObject('WScript.Shell').Popup(m,0,'TAO Report Generator',64);close()"
exit /b 0
