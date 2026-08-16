#!/usr/bin/env bash
# ========================================
# PC Property Quant Screener - start (Web GUI)
# macOS / Linux 용 실행 스크립트 (Windows: start.bat)
# ========================================
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

PORT=8585
VENV_PY="$BASE_DIR/.venv/bin/python"
VENV_PIP="$BASE_DIR/.venv/bin/pip"

echo "========================================"
echo "PC Property Quant Screener - start (Web GUI)"
echo "========================================"
echo

# 0. 기존 프로세스 정리
echo "[0/3] Cleaning up existing screener processes..."
"$BASE_DIR/stop.sh" >/dev/null 2>&1 || true

# 1. 가상환경 확인 및 종속성 설치
echo "[1/3] Checking Python virtual environment (.venv)..."
if [ ! -d ".venv" ]; then
    echo "      Creating .venv..."
    python3 -m venv .venv
fi
echo "      Verifying requirements..."
"$VENV_PIP" install -r pc/requirements.txt --quiet

# 참고: reports/report.html 생성 단계는 기동 경로에서 제외했다.
#       웹 대시보드(pc/templates/index.html)는 이 파일을 쓰지 않으며,
#       필요할 때 아래 명령으로 직접 생성한다.
#           ./.venv/bin/python -m pc.viewer.generate_report

# 2. 웹 GUI 서버 기동 (백그라운드, 로그는 logs/web_app.log)
echo "[2/3] Starting PC Quant Screener Web GUI Server (Port $PORT)..."
mkdir -p logs
nohup "$VENV_PY" pc/web_app.py >> logs/web_app.log 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > .web_app.pid

# 3. 서버 기동 대기 후 브라우저 열기
echo "[3/3] Waiting for server boot, then opening browser..."
for _ in $(seq 1 30); do
    if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then
        break
    fi
    sleep 0.5
done

if command -v open >/dev/null 2>&1; then
    open "http://127.0.0.1:$PORT"
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:$PORT"
fi

echo
echo "========================================"
echo "Start complete"
echo "- Local Web Dashboard : http://127.0.0.1:$PORT"
echo "- Server PID          : $SERVER_PID (logs/web_app.log)"
echo "종료하려면 ./stop.sh 를 실행하세요."
echo "========================================"
