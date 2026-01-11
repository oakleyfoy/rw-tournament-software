@echo off
echo Starting RW Tournament Software API Server...
echo.
echo Server will be available at:
echo   http://localhost:8000
echo.
echo API Documentation:
echo   http://localhost:8000/docs
echo.
echo Press Ctrl+C to stop the server
echo.
uvicorn app.main:app --reload

