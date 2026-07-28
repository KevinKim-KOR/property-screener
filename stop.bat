@echo off
setlocal

echo ========================================
echo PC Property Quant Screener - stop
echo ========================================

set "found=0"

rem 1. Stop window titled "PC Property Quant Screener*"
taskkill /FI "WINDOWTITLE eq PC Property Quant Screener*" /F /T >nul 2>&1
if not errorlevel 1 set "found=1"

rem 2. Stop any python process whose command line contains pc\main.py or pc/main.py
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | Where-Object { $_.CommandLine -like '*pc\main.py*' -or $_.CommandLine -like '*pc/main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host '   - Terminated PID' $_.ProcessId }" 2>nul
if not errorlevel 1 set "found=1"

echo    - Stop complete.
echo.
echo ========================================
echo PC Screener stop done
echo ========================================
timeout /t 1 >nul
