@echo off
cd /d "%~dp0"
echo ========================================
echo Backend FULL RESET and Restart
echo ========================================
echo.

echo [1/3] Clearing Python cache (__pycache__ and .pyc)...
for /d /r . %%d in (__pycache__) do @if exist "%%d" (
    echo   Removing %%d
    rd /s /q "%%d" 2>nul
)
for /r . %%f in (*.pyc) do @if exist "%%f" (
    echo   Removing %%f
    del /q "%%f" 2>nul
)
echo   Cache cleared.
echo.

echo [2/3] Stopping backend on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo   Stopping process PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
powershell -Command "$pids = (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique; foreach ($p in $pids) { if ($p -gt 0) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } }" 2>nul
timeout /t 2 /nobreak >nul
echo   Port 8000 cleared.
echo.

echo [3/3] Starting backend (uvicorn with --reload)...
echo.
echo Server will be at: http://localhost:8000
echo API docs: http://localhost:8000/docs
echo.
echo After it starts, run Build Schedule again (with clear existing).
echo ========================================
echo.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
