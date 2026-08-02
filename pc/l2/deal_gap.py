# pc/l2/deal_gap.py
"""
L2 매물 괴리율(deal_gap_pct) 및 층 조정계수 산출 모듈
(SCORING_V2_DESIGN.md §15, P1-AC12).
"""
import re
from typing import Optional, Tuple
from datetime import datetime
from common.database import get_db_connection
from common.area_mapper import pyeong_to_area_type, to_area_type

def classify_floor_grade(floor_str: Optional[str]) -> Tuple[str, float]:
    """
    층 문자열을 파싱하여 (floor_grade, floor_coeff)를 반환한다.
    - LOW  (저층 1~3층, 지하, 반지하): 0.95
    - HIGH (고층 15층 이상, 탑층, 로열층): 1.03
    - MID  (중층 그 외): 1.00
    """
    if not floor_str:
        return "MID", 1.00

    s = str(floor_str).upper().strip()
    if any(k in s for k in ("저", "지하", "반지하", "1층", "2층", "3층", "1/", "2/", "3/")):
        return "LOW", 0.95
    elif any(k in s for k in ("고", "탑", "로열", "최고")):
        return "HIGH", 1.03

    # 숫자로 층수 추출 시도
    m = re.search(r"(\d+)", s)
    if m:
        try:
            fl = int(m.group(1))
            if fl <= 3:
                return "LOW", 0.95
            elif fl >= 15:
                return "HIGH", 1.03
        except ValueError:
            pass

    return "MID", 1.00


def calculate_deal_gap(asking_price: float, median_price_3m: float, floor_coeff: float) -> Optional[float]:
    """
    호가(asking_price)와 층 조정계수 반영 기준가(fair_price = median_price_3m * floor_coeff)
    사이의 괴리율(%)을 산출한다.
      deal_gap_pct = ((asking_price - fair_price) / fair_price) * 100.0
    """
    if not asking_price or asking_price <= 0:
        return None
    if not median_price_3m or median_price_3m <= 0:
        return None
    fair_price = median_price_3m * floor_coeff
    if fair_price <= 0:
        return None
    gap_pct = ((asking_price - fair_price) / fair_price) * 100.0
    return round(gap_pct, 2)


def update_all_properties_l2(base_date: Optional[str] = None) -> int:
    """
    properties 테이블의 모든 매물에 대해
    area_type 매핑, floor_grade 분류, 3M중위 기준가 대비 deal_gap_pct 연산 및
    v1 스코어(score_v1) 병행 연산을 수행하여 저장한다.
    업데이트된 매물 수를 반환한다.
    """
    if not base_date:
        base_date = datetime.now().strftime("%Y-%m-%d")

    count = 0
    with get_db_connection() as conn:
        cur = conn.cursor()
        # 1. properties 전체 로드
        cur.execute("SELECT * FROM properties")
        props = [dict(r) for r in cur.fetchall()]

        # 2. complex_area_stats 로드
        cur.execute("SELECT complex_code, area_type, median_price_3m FROM complex_area_stats WHERE base_date = ?", (base_date,))
        stats_map = {}
        for r in cur.fetchall():
            stats_map[(r["complex_code"], r["area_type"])] = r["median_price_3m"]

        for p in props:
            pid = p["property_id"]
            cc = p["complex_code"]
            ask = p.get("asking_price", 0) or 0
            high = p.get("high_price", 0) or 0

            # area_type 결정 (exclusive_area 우선, 없으면 pyeong_to_area_type, 기존 area_type, 폴백 A84 순)
            at = to_area_type(p.get("exclusive_area")) or pyeong_to_area_type(p.get("area_pyeong")) or p.get("area_type") or "A84"


            # floor_grade 및 계수 결정
            f_grade, f_coeff = classify_floor_grade(p.get("floor"))

            # 3M중위 기준가 조회
            med_3m = stats_map.get((cc, at), 0.0)
            deal_gap = calculate_deal_gap(ask, med_3m, f_coeff)

            # score_v1 계산 (기존 하락률 5-Factor 단순 100점 환산)
            drop_r = p.get("drop_rate", 0.0) or 0.0
            if high > 0 and ask > 0 and ask < high:
                drop_r = max(drop_r, (high - ask) / float(high))
            score_v1 = min(100.0, max(0.0, drop_r * 250.0))

            cur.execute("""
                UPDATE properties
                SET area_type = ?, floor_grade = ?, deal_gap_pct = ?, score_v1 = ?
                WHERE property_id = ?
            """, (at, f_grade, deal_gap, round(score_v1, 1), pid))
            count += 1

        conn.commit()

    return count
