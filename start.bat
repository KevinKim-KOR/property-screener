@echo off
setlocal

echo ========================================
echo PC Property Quant Screener - start
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
echo [2/4] Generating local HTML report dashboard...
.\.venv\Scripts\python.exe pc\viewer\generate_report.py >nul 2>&1

rem 3. Start PC Pipeline engine in a dedicated console window
echo [3/4] Starting PC Quant Screener Pipeline window...
start "PC Property Quant Screener" cmd /k "cd /d ""%~dp0"" && .\.venv\Scripts\python.exe pc\main.py"

rem 4. Open local dashboard in default web browser
echo [4/4] Opening dashboard report in default web browser...
timeout /t 2 >nul
start "" "%~dp0pc\viewer\report.html"

echo.
echo ========================================
echo Start complete
echo - Local Dashboard : %~dp0pc\viewer\report.html
echo - Pipeline Engine : "PC Property Quant Screener" Window
echo Run stop.bat to shut down.
echo ========================================
pause
