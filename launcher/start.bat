@echo off
REM TAO Report Generator - Windows launcher.
REM
REM Run hidden by "TAO Report Generator.vbs", so there is no console to print
REM to: everything the user must see is a message box, in Chinese.
REM
REM The server runs in the FOREGROUND of this script. A child started with
REM `start /b` shares this console, and when this script exits the console is
REM destroyed and the server dies with it. Keeping the server here keeps the
REM console alive for as long as it runs.
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0.."

set "PORT=8501"
set "PY="

REM --- Already running? Then just bring it back to the front ------------------
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" launcher\open_when_ready.py %PORT% 2 >nul 2>&1
  if not errorlevel 1 exit /b 0
)

REM --- Step 1: is Python installed, and new enough? ---------------------------
py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto :nopython

REM --- Step 2: first run only - prepare the program ---------------------------
if not exist ".venv\Scripts\streamlit.exe" (
  call :say "正在第一次安裝，請稍候。||這個步驟只需要做一次，大約需要 3 到 5 分鐘。||安裝完成後，瀏覽器會自動打開。||請不要關閉電腦，也不要重複點擊。"
  %PY% -m venv .venv
  if errorlevel 1 goto :setupfailed
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  if errorlevel 1 goto :setupfailed
  if not exist ".venv\Scripts\streamlit.exe" goto :setupfailed
  call :say "安裝完成！||以後只要按一下「TAO Report Generator」就可以直接使用了。||現在為您打開程式。"
)

REM --- Step 3: open the browser once the server answers -----------------------
set "OPENER=.venv\Scripts\pythonw.exe"
if not exist "%OPENER%" set "OPENER=.venv\Scripts\python.exe"
start "" /b "%OPENER%" launcher\open_when_ready.py %PORT%

REM --- Step 4: run the program (stays here until it is stopped) ---------------
REM Bound to 127.0.0.1: reachable from this computer only.
".venv\Scripts\streamlit.exe" run ui.py --server.address=127.0.0.1 --server.port=%PORT% --server.headless=true --browser.gatherUsageStats=false --server.fileWatcherType=none
exit /b 0

:nopython
call :say "需要先安裝 Python 才能使用這個程式。||請照著做：||1. 打開網址 python.org/downloads||2. 點藍色大按鈕「Download Python」||3. 打開下載好的檔案||4. 【重要】先勾選最下面的「Add python.exe to PATH」||5. 再點「Install Now」，等它跑完||6. 裝好後，重新點一下「TAO Report Generator」||如果不確定，請看資料夾裡的「FIRST_TIME_SETUP.md」。"
exit /b 1

:setupfailed
call :say "安裝沒有成功。||最常見的原因是網路沒有連上。||請照著做：||1. 確認電腦可以正常上網||2. 重新點一下「TAO Report Generator」||如果試了兩次還是不行，請把這個訊息拍照傳給您的家人協助。"
exit /b 1

:say
REM No console to print to, so use a message box. '||' becomes a line break.
mshta "javascript:var m='%~1'.split('||').join('\n');new ActiveXObject('WScript.Shell').Popup(m,0,'TAO 報表產生器',64);close()"
exit /b 0
