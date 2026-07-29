@echo off
setlocal

echo ========================================
echo PC Property Quant Screener - start (Web GUI)
echo ========================================
echo.

cd /d "%~dp0"

rem 0. Clean up existing processes
echo [0/4] Cleaning up existing screener processes...
cmd /c "%~dp0stop.bat" >nul 2>&1
timeout /t 1 >nul

rem 1. Check virtual environment
echo [1/4] Checking Python virtual environment (.venv)...
if not exist ".venv" (
    echo       Creating .venv...
    python -m venv .venv
)

echo       Verifying requirements...
.\.venv\Scripts\pip.exe install -r pc\requirements.txt --quiet

rem 2. Generate initial HTML dashboard report
echo [2/4] Generating initial local dashboard report...
.\.venv\Scripts\python.exe pc\viewer\generate_report.py >nul 2>&1

rem 3. Start PC Web GUI Server on Port 8585
echo [3/4] Starting PC Quant Screener Web GUI Server (Port 8585)...
start "PC Property Quant Screener" cmd /k "cd /d ""%~dp0"" && .\.venv\Scripts\python.exe pc\web_app.py"

rem 4. Open Local Web GUI in default web browser
echo [4/4] Waiting 2 seconds for server boot, then opening browser...
timeout /t 2 >nul
start "" "http://127.0.0.1:8585"

echo.
echo ========================================
echo Start complete
echo - Local Web Dashboard : http://127.0.0.1:8585
echo - Web GUI Server      : "PC Property Quant Screener" Window
echo Run stop.bat to shut down.
echo ========================================
pause
