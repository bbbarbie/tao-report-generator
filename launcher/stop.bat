@echo off
REM Stops the TAO Report Generator started by the launcher.
REM Only touches processes running out of this folder's own environment, so a
REM different Python program on this computer is never affected.
setlocal
cd /d "%~dp0.."

set "TARGET=%CD%\.venv\Scripts"
set "FOUND="

for /f "usebackq skip=1 tokens=1,2 delims=," %%A in (
  `wmic process where "name='python.exe' or name='pythonw.exe' or name='streamlit.exe'" get ProcessId^,ExecutablePath /format:csv 2^>nul`
) do (
  echo %%B | findstr /i /c:"%TARGET%" >nul && (
    taskkill /pid %%A /f >nul 2>&1
    set "FOUND=1"
  )
)

if defined FOUND (
  mshta "javascript:new ActiveXObject('WScript.Shell').Popup('TAO Report Generator has been stopped.',0,'TAO Report Generator',64);close()"
) else (
  mshta "javascript:new ActiveXObject('WScript.Shell').Popup('TAO Report Generator was not running.',0,'TAO Report Generator',64);close()"
)
exit /b 0
