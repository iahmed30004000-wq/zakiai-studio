@echo off
rem Zakiai Systems - double-click: starts the studio and opens it in the browser.
rem If it is already running, it only opens the browser.
cd /d "%~dp0"
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %errorlevel%==0 (
  start http://127.0.0.1:8000
  exit /b 0
)
start "" /min cmd /c "timeout /t 4 /nobreak >nul && start http://127.0.0.1:8000"
python run_web.py
pause
