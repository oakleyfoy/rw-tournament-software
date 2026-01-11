@echo off
echo ========================================
echo RW Tournament Software - Server Restart
echo ========================================
echo.

echo [1/3] Forcefully stopping all Python processes...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM pythonw.exe /T >nul 2>&1
powershell -Command "Get-Process | Where-Object {$_.ProcessName -like '*python*'} | Stop-Process -Force -ErrorAction SilentlyContinue" >nul 2>&1
echo All Python processes stopped

echo.
echo [2/3] Forcefully stopping processes on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
    echo Killing process %%a
    taskkill /F /PID %%a >nul 2>&1
)
powershell -Command "netstat -ano | findstr :8000 | ForEach-Object { $parts = $_ -split '\s+'; if ($parts[-1] -match '^\d+$') { taskkill /F /PID $parts[-1] 2>$null } }" >nul 2>&1
echo Port 8000 cleared

echo.
echo [3/3] Starting backend server...
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

