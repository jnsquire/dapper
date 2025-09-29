@echo off
echo ========================================
echo  Dapper Debug Adapter Two-Terminal Test  
echo ========================================
echo.
echo This will open two command prompts:
echo.
echo Window 1: Debug Adapter Server
echo Window 2: Test Client
echo.
echo In Window 1, run:
echo   python -m dapper --port 4711 --log-level DEBUG
echo.
echo In Window 2, run:
echo   python test_dapper_client.py --test-only --program examples/sample_programs/simple_app.py
echo.
echo Press any key to open the terminals...
pause > nul

echo Opening debug adapter terminal...
start "Dapper Debug Adapter" cmd /k "echo Run: python -m dapper --port 4711 --log-level DEBUG && echo."

echo Waiting 2 seconds...
timeout /t 2 /nobreak > nul

echo Opening test client terminal...
start "Dapper Test Client" cmd /k "echo Run: python test_dapper_client.py --test-only --program examples/sample_programs/simple_app.py && echo."

echo.
echo ✅ Two terminals opened!
echo 📋 Follow the instructions in each window to test the debug adapter.
echo.
pause
