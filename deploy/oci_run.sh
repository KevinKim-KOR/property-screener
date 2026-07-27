#!/usr/bin/env bash
# OCI 무료티어 (Docker 미사용) 환경 전용 자동 실행 스크립트
# crontab 또는 systemd 서비스 등록으로 구동 가능합니다.

set -e

# 프로젝트 홈 디렉토리 (스크립트 위치 기준)
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BASE_DIR"

echo "=========================================================="
echo "[OCI Native] PC-OCI Property Quant Screener - OCI Runner"
echo "=========================================================="

# 1. 가상환경 (.venv) 확인 및 생성
if [ ! -d ".venv" ]; then
    echo "[OCI Native] Creating Python virtual environment (.venv)..."
    python3 -m venv .venv
fi

# 2. 가상환경 활성화 및 종속성 설치
source .venv/bin/activate
echo "[OCI Native] Updating dependencies from oci/requirements.txt..."
pip install -r oci/requirements.txt --quiet

# 3. 환경 변수 파일(.env) 확인
if [ ! -f ".env" ]; then
    echo "[WARNING] .env 파일이 존재하지 않습니다. 카카오 API Key 또는 텔레그램 토큰 설정이 필요합니다."
fi

# 4. OCI 파이프라인(크롤러 -> DB 저장 -> 텔레그램 알림) 실행
echo "[OCI Native] Starting OCI Pipeline Engine..."
python3 oci/main.py

echo "[OCI Native] Execution finished successfully."
