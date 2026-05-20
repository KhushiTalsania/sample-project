@echo off
echo ========================================
echo    Test Main Application WebSocket APIs
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
echo Starting comprehensive WebSocket API test for main application...
echo This will test all endpoints and functionality.
echo.

python test_main_websocket_apis.py

echo.
echo Test completed. Check the results above.
echo.
pause
