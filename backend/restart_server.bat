@echo off
cd /d "%~dp0"
echo ========================================
echo RW Tournament Software - Restart Backend
echo ========================================
echo.

echo [1/2] Stopping whatever is using port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo   Stopping process PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
powershell -Command "$pids = (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique; foreach ($p in $pids) { if ($p -gt 0) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } }" >nul 2>&1
timeout /t 2 /nobreak >nul
echo   Port 8000 cleared.
echo.

echo [2/2] Starting backend server...
echo.
echo Server will be available at:
echo   http://localhost:8000
echo.
echo API Documentation:
echo   http://localhost:8000/docs
echo.
echo Press Ctrl+C to stop the server
echo.
echo ========================================
echo.

cd /d "%~dp0"
uvicorn app.main:app --reload --log-level debug

