@echo off
TITLE PC Quant Screener
echo =======================================
echo PC Quant Screener - Starting...
echo =======================================

IF NOT EXIST ".venv" (
    echo Creating Python virtual environment...
    python -m venv .venv
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Installing PC requirements...
pip install -r pc\requirements.txt

echo Starting PC Pipeline...
python pc\main.py

pause
