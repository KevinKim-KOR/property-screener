# pc/features/region_stats.py
"""
강남/서초 통합(BELT_AREA) 및 구별(SGG_AREA) area_type별 기준선
(중위 초과하락률, 평단가, 전세가율, 샘플수)을 산출하여 region_stats 테이블에 저장하는 모듈
(SCORING_V2_DESIGN.md §8.2, P1-AC9).
"""
import statistics
from datetime import datetime
from typing import Dict, List, Optional
from common.database import get_db_connection
from .peak_detector import detect_robust_peak

def compute_and_store_region_stats(base_date: Optional[str] = None) -> int:
    """
    trades_sale 및 trades_rent 데이터를 집계하여
    sgg_cd ('11650', '11680', 'BELT') x area_type ('A40', 'A59', 'A84', 'A114', 'A135P')
    기준 통계를 region_stats에 저장한다.
    저장된 레코드 수를 반환한다.
    """
    if not base_date:
        base_date = datetime.now().strftime("%Y-%m-%d")

    records = []
    with get_db_connection() as conn:
        cur = conn.cursor()
        # 1. trades_sale에서 지역별, area_type별 실거래 매칭 조회 (최근 12개월 거래 기준)
        cur.execute("""
            SELECT sgg_cd, area_type, deal_amount, exclusive_area, deal_date
            FROM trades_sale
            WHERE is_cancelled = 0 AND area_type IS NOT NULL
        """)
        rows = cur.fetchall()

        # sgg_cd ('11650', '11680') 및 'BELT' 그룹화
        groups: Dict[str, Dict[str, List[Dict]]] = {
            "11650": {}, "11680": {}, "BELT": {}
        }
        for r in rows:
            sgg = r["sgg_cd"]
            at = r["area_type"]
            item = {
                "deal_amount": r["deal_amount"],
                "exclusive_area": r["exclusive_area"],
                "deal_date": r["deal_date"]
            }
            if sgg in ("11650", "11680"):
                groups[sgg].setdefault(at, []).append(item)
                groups["BELT"].setdefault(at, []).append(item)

        for sgg_code, at_dict in groups.items():
            for at, items in at_dict.items():
                if not items:
                    continue
                amounts = [x["deal_amount"] for x in items]
                ppps = []
                for x in items:
                    # 3.3㎡당 금액(만원) = (deal_amount / (exclusive_area / 3.305785))
                    if x["exclusive_area"] and x["exclusive_area"] > 0:
                        pyeong = x["exclusive_area"] / 3.305785
                        ppps.append(x["deal_amount"] / pyeong)

                median_ppp = statistics.median(ppps) if ppps else 0.0
                sample_n = len(items)

                # 중위 하락률 계산: 해당 그룹 거래 목록 전고점 대비 중위 실거래가 하락률
                raw_peak, adj_peak, _, _ = detect_robust_peak(items, base_date)
                median_price = statistics.median(amounts)
                median_drop = 0.0
                if adj_peak and adj_peak > 0 and adj_peak > median_price:
                    median_drop = (adj_peak - median_price) / adj_peak

                # 전세가율 중위값
                cur.execute("""
                    SELECT deposit, exclusive_area FROM trades_rent
                    WHERE sgg_cd = ? AND area_type = ? AND monthly_rent = 0
                """, (sgg_code if sgg_code != "BELT" else "11650", at))
                rent_rows = cur.fetchall()
                if sgg_code == "BELT":
                    cur.execute("""
                        SELECT deposit, exclusive_area FROM trades_rent
                        WHERE area_type = ? AND monthly_rent = 0
                    """, (at,))
                    rent_rows = cur.fetchall()

                jeonse_ratios = []
                for rr in rent_rows:
                    if median_price > 0 and rr["deposit"] > 0:
                        jeonse_ratios.append(rr["deposit"] / median_price)
                median_jr = statistics.median(jeonse_ratios) if jeonse_ratios else 0.55

                records.append((
                    base_date, sgg_code, at,
                    median_drop, median_ppp, median_jr, sample_n, 0.0, 0.0
                ))

        for rec in records:
            cur.execute("""
                INSERT OR REPLACE INTO region_stats (
                    base_date, sgg_cd, area_type,
                    median_drop_rate, median_ppp, median_jeonse_ratio,
                    sample_n, supply_ratio, unsold_delta_3m
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rec)

        conn.commit()

    return len(records)
