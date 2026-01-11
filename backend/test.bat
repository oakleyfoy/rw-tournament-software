@echo off
echo ========================================
echo RW Tournament Software - Test Runner
echo ========================================
echo.

echo [1/3] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo [2/3] Running database migrations...
alembic upgrade head
if errorlevel 1 (
    echo ERROR: Migration failed
    pause
    exit /b 1
)

echo.
echo [3/3] Running automated tests...
pytest -v
if errorlevel 1 (
    echo.
    echo WARNING: Some tests failed
) else (
    echo.
    echo SUCCESS: All tests passed!
)

echo.
echo ========================================
echo Testing complete!
echo ========================================
echo.
echo To start the server, run:
echo   uvicorn app.main:app --reload
echo.
echo Then visit http://localhost:8000/docs
echo.
pause

