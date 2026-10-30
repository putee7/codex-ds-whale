@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1" uninstall %*
set "WHALE_EXIT=%ERRORLEVEL%"
if not "%WHALE_NO_PAUSE%"=="1" pause
exit /b %WHALE_EXIT%
