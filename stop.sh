#!/usr/bin/env bash
# ========================================
# PC Property Quant Screener - stop
# macOS / Linux 용 종료 스크립트 (Windows: stop.bat)
#
# 주의: 포트를 점유한 프로세스를 무조건 종료하지 않고,
#       이 프로젝트(BASE_DIR)에 속한 프로세스인지 확인한 뒤에만 종료합니다.
#       또한 이 프로젝트가 실제로 사용하는 포트(8585)만 대상으로 하며,
#       더 이상 바인딩하지 않는 레거시 포트 8000은 건드리지 않습니다.
#       (다른 프로젝트의 개발 서버를 내리지 않기 위함)
# ========================================
set -uo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

# 이 프로젝트가 실제로 바인딩하는 포트만 나열 (pc/web_app.py 기준)
SCREENER_PORTS=(8585)

echo "========================================"
echo "PC Property Quant Screener - stop"
echo "========================================"

FOUND=0

# 커맨드라인이 실제 스크리너 진입점을 실행 중인지 검사 (엄격).
# 단순히 프로젝트 경로 문자열만 포함하는 셸 등은 제외해야 하므로
# BASE_DIR 자체는 매칭 조건에 넣지 않는다.
cmd_matches() {
    case "$1" in
        *pc/web_app.py*|*pc/main.py*|*pc.web_app*) return 0 ;;
        *) return 1 ;;
    esac
}

# 해당 PID가 이 프로젝트의 스크리너 프로세스인지 판별.
# uvicorn 의 reload 자식 프로세스는 커맨드라인이
# "python -c from multiprocessing.spawn import spawn_main ..." 형태라
# 경로 정보가 전혀 없으므로, 부모 계보와 cwd 까지 함께 확인한다.
is_ours() {
    local pid="$1"
    local cmd cwd cur depth

    cmd="$(ps -o command= -p "$pid" 2>/dev/null)" || return 1
    [ -z "$cmd" ] && return 1
    cmd_matches "$cmd" && return 0

    # 이 프로젝트의 .venv 인터프리터로 구동된 프로세스
    case "$cmd" in
        "$BASE_DIR"/.venv/*) return 0 ;;
    esac

    # 부모 계보 추적 (최대 4단계, PID 1 에서 중단)
    cur="$pid"
    for depth in 1 2 3 4; do
        cur="$(ps -o ppid= -p "$cur" 2>/dev/null | tr -d ' ')"
        [ -z "$cur" ] && break
        [ "$cur" -le 1 ] 2>/dev/null && break
        cmd="$(ps -o command= -p "$cur" 2>/dev/null)"
        [ -n "$cmd" ] && cmd_matches "$cmd" && return 0
    done

    # 마지막 보루: 부모가 먼저 종료되어 계보가 끊긴 reload 자식 프로세스 대비.
    # 작업 디렉토리가 정확히 프로젝트 루트인 python 프로세스만 인정한다.
    cwd="$(lsof -a -d cwd -p "$pid" -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
    if [ "$cwd" = "$BASE_DIR" ]; then
        cmd="$(ps -o command= -p "$pid" 2>/dev/null)"
        case "$cmd" in
            *[Pp]ython*) return 0 ;;
        esac
    fi

    return 1
}

kill_if_ours() {
    local pid="$1" label="$2" sig="${3:-TERM}"
    [ "$pid" = "$$" ] && return
    # 이미 종료된 프로세스는 조용히 넘어감 (reload 자식 프로세스 등)
    kill -0 "$pid" 2>/dev/null || return
    if is_ours "$pid"; then
        echo "   - $label PID $pid terminated."
        kill "-$sig" "$pid" 2>/dev/null || true
        FOUND=1
    else
        echo "   - $label PID $pid 는 이 프로젝트 소유가 아니므로 건너뜁니다."
    fi
}

# 1. start.sh가 기록한 PID 파일로 종료
if [ -f ".web_app.pid" ]; then
    PID="$(cat .web_app.pid)"
    if kill -0 "$PID" 2>/dev/null; then
        kill_if_ours "$PID" "PID file"
    fi
    rm -f .web_app.pid
fi

# 2. 이 프로젝트가 사용하는 포트(8585) 리스닝 프로세스 중 소유가 확인된 것만 종료
for PORT in "${SCREENER_PORTS[@]}"; do
    for P in $(lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null || true); do
        kill_if_ours "$P" "Port $PORT"
    done
done

# 3. pc/web_app.py, pc/main.py 를 실행 중인 python 프로세스 종료
for PATTERN in "pc/web_app.py" "pc/main.py"; do
    for P in $(pgrep -f "$PATTERN" 2>/dev/null || true); do
        kill_if_ours "$P" "$PATTERN"
    done
done

# 4. 정상 종료되지 않은 프로세스 강제 종료
if [ "$FOUND" = "1" ]; then
    sleep 1
    for PORT in "${SCREENER_PORTS[@]}"; do
        for P in $(lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null || true); do
            kill_if_ours "$P" "Port $PORT (force)" KILL
        done
    done
fi

if [ "$FOUND" = "0" ]; then
    echo "   - No matching PC Screener process found."
else
    echo "   - Stop complete."
fi

echo
echo "========================================"
echo "PC Screener stop done"
echo "========================================"
