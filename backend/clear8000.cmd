@echo off
REM Kill all processes bound to :8000 (repeatable, deterministic)
echo Killing processes on port 8000...
for /L %%i in (1,1,3) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /PID %%a /F 2>nul
  timeout /t 1 /nobreak >nul
)
echo Checking :8000...
netstat -ano | findstr ":8000"
if %errorlevel% neq 0 echo Port 8000 is clear.
exit /b 0
