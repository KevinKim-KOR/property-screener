#!/usr/bin/env bash
# ========================================
# PC/Laptop - Naver Real Estate Crawler
# macOS / Linux 용 즉시 크롤링 스크립트 (Windows: crawl_now.bat)
# ========================================
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

VENV_PY="$BASE_DIR/.venv/bin/python"
VENV_PIP="$BASE_DIR/.venv/bin/pip"

echo "========================================"
echo "PC/Laptop - Naver Real Estate Crawler"
echo "========================================"
echo

if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment (.venv)..."
    python3 -m venv .venv
fi

echo "[1/2] Activating virtual environment and verifying dependencies..."
"$VENV_PIP" install -r oci/requirements.txt --quiet

echo "[2/2] Starting Naver Real Estate API Crawler (oci/main.py)..."
echo "      (config.yaml의 target_regions 지역 단지들을 최신화합니다)"
echo
"$VENV_PY" oci/main.py

echo
echo "========================================"
echo "[Crawl Complete] 실시간 매물 수집 및 DB(screener.db) 저장 완료."
echo "이제 ./start.sh 를 실행하시면 최신 수집 데이터로 퀀트 대시보드가 열립니다."
echo "========================================"
