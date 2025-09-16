@echo off
REM Quick test script for Windows to verify debug adapter setup

echo ===================================
echo  Dapper Debug Adapter Quick Test
echo ===================================
echo.

echo Testing debug adapter setup...
python test_debug_adapter_setup.py

echo.
echo ===================================
echo  Manual Testing Instructions
echo ===================================
echo.
echo 1. Open VS Code in this project
echo 2. Go to Run and Debug (Ctrl+Shift+D)
echo 3. Try these configurations:
echo    - "Launch Debug Adapter (TCP)"
echo    - "Debug Simple App (Standard Python)"
echo    - "Debug Advanced App (Standard Python)"
echo.
echo 4. Set breakpoints in example programs:
echo    - examples/sample_programs/simple_app.py
echo    - examples/sample_programs/advanced_app.py
echo.
echo 5. Test debugging features:
echo    - Breakpoints
echo    - Step over/into/out
echo    - Variable inspection
echo    - Call stack
echo.

pause
