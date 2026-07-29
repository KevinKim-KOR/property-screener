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
    거래 목록(trades: [{'deal_date': 'YYYY-MM-DD', 'deal_amount': int}, ...])에서
    1) 60개월 이내의 거래를 필터링
    2) 상위 90분위수(p90) 금액 및 해당 시점을 탐지 -> peak_price_raw, peak_date
    3) 시간 감쇠 인자를 적용 -> peak_price_adj, decay_factor
    반환: (peak_price_raw, peak_price_adj, peak_date, decay_factor)
    """
    if not trades:
        return 0.0, 0.0, None, 1.0
    if not base_date:
        base_date = datetime.now().strftime("%Y-%m-%d")

    # 60개월 이내 거래만 필터링
    valid_trades = []
    for t in trades:
        d = t.get("deal_date", "")
        amt = float(t.get("deal_amount", 0))
        if amt <= 0 or not d:
            continue
        months_ago = calculate_months_elapsed(d, base_date)
        if months_ago <= 60.0:
            valid_trades.append({"deal_date": d, "deal_amount": amt, "months_ago": months_ago})

    if not valid_trades:
        return 0.0, 0.0, None, 1.0

    # 금액 목록 p90 산출
    amounts = [t["deal_amount"] for t in valid_trades]
    peak_price_raw = calculate_percentile(amounts, 0.90)

    # p90 이상인 거래 중 가장 최근 날짜를 peak_date로 설정
    peak_candidates = [t for t in valid_trades if t["deal_amount"] >= peak_price_raw * 0.98]
    if not peak_candidates:
        peak_candidates = valid_trades

    # peak_date 및 경과 개월 수 산출
    best_candidate = max(peak_candidates, key=lambda x: x["deal_amount"])
    peak_date = best_candidate["deal_date"]
    months_elapsed = calculate_months_elapsed(peak_date, base_date)

    decay_factor = compute_decay_factor(months_elapsed, DECAY_TAU, DECAY_FLOOR)
    peak_price_adj = peak_price_raw * decay_factor

    return peak_price_raw, peak_price_adj, peak_date, decay_factor
