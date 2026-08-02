# pc/features/peak_detector.py
"""
60개월 롤링 3개월 윈도우 상위 90분위수(p90) 기반 전고점 탐지 및
36개월 반감기 지수 시간감쇠(Exponential Time Decay) 모듈
(SCORING_V2_DESIGN.md §7.2, P1-AC7).
"""
import math
from datetime import datetime
from typing import List, Dict, Optional, Tuple

DECAY_TAU = 36.0    # 반감기: 36개월 (3년)
DECAY_FLOOR = 0.80  # 감쇠 하한선: 80% (0.80 미만으로 떨어지지 않음)

def calculate_percentile(values: List[float], percentile: float) -> float:
    """
    정렬된 실수 목록에서 상위 백분위수(p90 등)를 선형 보간으로 산출한다.
    percentile=0.90 -> 90th percentile
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = (n - 1) * percentile
    lower_idx = int(idx)
    upper_idx = min(lower_idx + 1, n - 1)
    weight = idx - lower_idx
    return sorted_vals[lower_idx] * (1.0 - weight) + sorted_vals[upper_idx] * weight


def calculate_months_elapsed(from_date: str, to_date: str) -> float:
    """
    두 날짜 ("YYYY-MM-DD" 또는 "YYYYMM") 사이의 개월 수를 실수로 계산한다.
    """
    def parse_dt(s: str) -> datetime:
        s = str(s).strip()[:10]
        if len(s) == 7:  # YYYY-MM
            return datetime.strptime(s, "%Y-%m")
        elif len(s) == 6:  # YYYYMM
            return datetime.strptime(s, "%Y%m")
        else:
            return datetime.strptime(s, "%Y-%m-%d")

    try:
        dt1 = parse_dt(from_date)
        dt2 = parse_dt(to_date)
        diff_days = max(0, (dt2 - dt1).days)
        return diff_days / 30.4375
    except Exception:
        return 0.0


def compute_decay_factor(months_elapsed: float, tau: float = DECAY_TAU, floor: float = DECAY_FLOOR) -> float:
    """
    지수 감쇠 인자 계산:
      decay = max(DECAY_FLOOR, 0.5 ** (months_elapsed / DECAY_TAU))
    """
    if months_elapsed <= 0:
        return 1.0
    decay = 0.5 ** (months_elapsed / tau)
    return max(floor, decay)


def detect_robust_peak(trades: List[Dict], base_date: Optional[str] = None) -> Tuple[float, float, Optional[str], float]:
    """
    SCORING_DESIGN_v4.2 전고점 산출:
    1) 최근 60개월 내 유효거래 전체를 한 줄로 세워 상위 95% 지점(p95) 값을 기록
    2) 그 값(p95)에 해당하는(가장 가까운) 거래의 계약월(YYYY.MM)을 전고점 시점으로 반환
    3) 3개월 창과 창당 최소 건수는 폐지
    4) 시간 감쇠는 적용하지 않는다 (decay_factor = 1.0, peak_adj = peak_raw).
    """
    if not trades:
        return 0.0, 0.0, None, 1.0
    if not base_date:
        base_date = datetime.now().strftime("%Y-%m-%d")

    # 60개월 이내 거래만 필터링
    valid_trades = []
    for t in trades:
        d = str(t.get("deal_date", "")).strip()[:10]
        amt = float(t.get("deal_amount", 0))
        if amt <= 0 or not d:
            continue
        months_ago = calculate_months_elapsed(d, base_date)
        if 0.0 <= months_ago <= 60.0:
            valid_trades.append({"deal_date": d, "deal_amount": amt, "months_ago": months_ago})

    if not valid_trades:
        return 0.0, 0.0, None, 1.0

    p95 = calculate_percentile([t["deal_amount"] for t in valid_trades], 0.95)

    # p95와 가장 가까운 거래의 계약월을 전고점 시점으로 선택 (동점 시 더 최근 거래)
    best_trade = min(
        valid_trades,
        key=lambda t: (abs(t["deal_amount"] - p95), -t["months_ago"]),
    )
    best_peak_dt = best_trade["deal_date"][:7].replace("-", ".")

    return p95, p95, best_peak_dt, 1.0
