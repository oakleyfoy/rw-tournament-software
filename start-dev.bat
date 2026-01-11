@echo off
REM Launch PowerShell script completely hidden
powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0start-dev.ps1"
exit
