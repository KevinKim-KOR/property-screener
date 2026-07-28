@echo off
setlocal

echo ========================================
echo PC/Laptop - Naver Real Estate Crawler
echo ========================================
echo.

cd /d "%~dp0"

if not exist ".venv" (
    echo Creating Python virtual environment (.venv)...
    python -m venv .venv
)

echo [1/2] Activating virtual environment and verifying dependencies...
.\.venv\Scripts\pip.exe install -r oci\requirements.txt --quiet

echo [2/2] Starting Naver Real Estate API Crawler (oci/main.py)...
echo       (config.yaml의 target_regions 지역 단지들을 최신화합니다)
echo.
.\.venv\Scripts\python.exe oci\main.py

echo.
echo ========================================
echo [Crawl Complete] 실시간 매물 수집 및 DB(screener.db) 저장 완료.
echo 이제 start.bat을 실행하시면 최신 수집 데이터로 퀀트 대시보드가 열립니다.
echo ========================================
pause
