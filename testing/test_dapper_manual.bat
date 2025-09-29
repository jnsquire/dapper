@echo off
REM Two-step process to test Dapper debug adapter

echo ===================================
echo  Dapper Debug Adapter Manual Test
echo ===================================
echo.

echo This script demonstrates how to test your Dapper debug adapter:
echo.
echo STEP 1: Start the debug adapter
echo --------------------------------
echo Run this command in one terminal:
echo    python -m dapper --port 4711 --log-level DEBUG
echo.
echo STEP 2: Connect and debug a program  
echo ------------------------------------
echo Run this command in another terminal:
echo    python test_dapper_client.py --program examples/sample_programs/simple_app.py
echo.
echo OR test just the connection:
echo    python test_dapper_client.py --test-only --program examples/sample_programs/simple_app.py
echo.

echo ===================================
echo  Quick Test (Connection Only)
echo ===================================
echo.
echo Testing if debug adapter is running...
python test_dapper_client.py --test-only --program examples/sample_programs/simple_app.py

echo.
echo ===================================
echo  VS Code Integration
echo ===================================
echo.
echo To test with VS Code:
echo 1. Start debug adapter: "Launch Debug Adapter (TCP)"
echo 2. Use: "Test Dapper Debug Adapter" configuration
echo.

pause
