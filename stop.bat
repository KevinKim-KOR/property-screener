@echo off
setlocal

echo ========================================
echo PC Property Quant Screener - stop
echo ========================================

set "found=0"

rem 1. Stop window titled "PC Property Quant Screener*"
taskkill /FI "WINDOWTITLE eq PC Property Quant Screener*" /F /T >nul 2>&1
if not errorlevel 1 set "found=1"

rem 2. Stop by Port 8585 & 8000 (FastAPI Web GUI)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /C:":8585 " ^| findstr /C:"LISTENING"') do (
    echo    - Port 8585 PID %%a terminated.
    taskkill /F /PID %%a >nul 2>&1
    set "found=1"
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /C:":8000 " ^| findstr /C:"LISTENING"') do (
    echo    - Port 8000 PID %%a terminated.
    taskkill /F /PID %%a >nul 2>&1
    set "found=1"
)

rem 3. Stop any python process whose command line contains pc\main.py, pc/web_app.py, etc.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | Where-Object { $_.CommandLine -like '*pc\main.py*' -or $_.CommandLine -like '*pc/web_app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host '   - Terminated PID' $_.ProcessId }" 2>nul
if not errorlevel 1 set "found=1"

if %found%==0 (
    echo    - No matching PC Screener process found.
) else (
    echo    - Stop complete.
)

echo.
echo ========================================
echo PC Screener stop done
echo ========================================
timeout /t 1 >nul
