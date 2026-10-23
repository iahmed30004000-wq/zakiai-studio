@echo off
rem Double-click launcher: runs the PowerShell script with the same name next to this file.
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0%~n0.ps1" %*
set rc=%errorlevel%
pause
exit /b %rc%
