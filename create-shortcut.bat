@echo off
echo Creating desktop shortcut...
powershell -ExecutionPolicy Bypass -File "%~dp0create-shortcut.ps1"
echo.
echo Done! Check your desktop for "RW Tournament Software" shortcut.
pause

