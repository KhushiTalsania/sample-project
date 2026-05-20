@echo off
echo ========================================
echo    Test WebSocket Documentation
echo ========================================
echo.

echo Checking if Python is available...
python --version
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /b 1
)

echo.
echo Starting WebSocket documentation test...
echo This will verify that WebSocket paths are visible in FastAPI docs.
echo.

python test_websocket_docs.py

echo.
echo Test completed. Check the results above.
echo.
pause
