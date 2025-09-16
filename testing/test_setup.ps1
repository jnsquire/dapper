#!/usr/bin/env pwsh
# Quick test script for PowerShell to verify debug adapter setup

Write-Host "===================================" -ForegroundColor Cyan
Write-Host " Dapper Debug Adapter Quick Test" -ForegroundColor Cyan  
Write-Host "===================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Testing debug adapter setup..." -ForegroundColor Yellow
python test_debug_adapter_setup.py

Write-Host ""
Write-Host "===================================" -ForegroundColor Cyan
Write-Host " Manual Testing Instructions" -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "1. Open VS Code in this project" -ForegroundColor Green
Write-Host "2. Go to Run and Debug (Ctrl+Shift+D)" -ForegroundColor Green
Write-Host "3. Try these configurations:" -ForegroundColor Green
Write-Host "   - 'Launch Debug Adapter (TCP)'" -ForegroundColor White
Write-Host "   - 'Debug Simple App (Standard Python)'" -ForegroundColor White
Write-Host "   - 'Debug Advanced App (Standard Python)'" -ForegroundColor White
Write-Host ""
Write-Host "4. Set breakpoints in example programs:" -ForegroundColor Green
Write-Host "   - examples/sample_programs/simple_app.py" -ForegroundColor White
Write-Host "   - examples/sample_programs/advanced_app.py" -ForegroundColor White
Write-Host ""
Write-Host "5. Test debugging features:" -ForegroundColor Green
Write-Host "   - Breakpoints" -ForegroundColor White
Write-Host "   - Step over/into/out" -ForegroundColor White
Write-Host "   - Variable inspection" -ForegroundColor White
Write-Host "   - Call stack" -ForegroundColor White
Write-Host ""

Read-Host "Press Enter to continue"
