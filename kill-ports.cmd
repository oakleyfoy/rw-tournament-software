@echo off
echo Killing processes on ports 8000 and 3000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo Killing PID %%a
    taskkill /F /PID %%a 2>nul
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do (
    echo Killing PID %%a
    taskkill /F /PID %%a 2>nul
)
timeout /t 3 /nobreak >nul
echo Done.
netstat -ano | findstr "LISTENING" | findstr "8000 3000"
