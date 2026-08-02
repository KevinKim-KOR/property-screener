# pc/features/region_stats.py
"""
강남/서초 통합(BELT_AREA) 및 구별(SGG_AREA) area_type별 기준선
(중위 하락률, 평단가, 전세가율, 샘플수)을 산출하여 region_stats 테이블에 저장하는 모듈
(SCORING_V2_DESIGN.md §8.2, P1-AC9).

v4.2 수정: median_drop_rate = median([단지별 하락률])
  - 단지×평형마다 하락률을 먼저 구하고(complex_area_stats), 그 하락률들의 중위값
  - 제외된 단지(G1 거래 부족)는 중위값 계산에 넣지 않음
  - 같은 평형끼리만 묶음
"""
import statistics
from datetime import datetime
from typing import Dict, List, Optional
from common.database import get_db_connection


def get_ref_pyeong(at: str) -> float:
    if not at or not at.startswith("A"):
        return 25.7
    parts = at[1:].split("_")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return (float(parts[0]) + float(parts[1])) / 2.0 / 3.305785
    return {"A59": 18.0, "A84": 25.7, "A114": 34.5}.get(at, 25.7)


def compute_and_store_region_stats(cas_date: str = "2026-07-31", base_date: Optional[str] = None) -> int:
    """
    5m2 bucket region stats calculation.
    """
    if not base_date:
        base_date = cas_date

    records = []
    with get_db_connection() as conn:
        cur = conn.cursor()

        cur.execute("DELETE FROM region_stats WHERE base_date = ?", (base_date,))

        # 1. 적격 단지(PASS)의 하락률을 complex_area_stats에서 로드
        #    제외된 단지(EXCLUDED)는 중위값 계산에서 제외
        cur.execute("""
            SELECT s.complex_code, c.complex_name, c.sgg_cd, s.area_type,
                   s.drop_rate, s.price_per_pyeong,
                   s.median_price_3m, s.peak_price_adj,
                   s.trade_count_12m, s.sample_count_12m, s.sample_count_24m
            FROM complex_area_stats s
            JOIN complexes c ON s.complex_code = c.complex_code
            LEFT JOIN market_scores m ON s.complex_code = m.complex_code
                 AND s.area_type = m.area_type AND m.base_date = ?
            WHERE s.base_date = ?
              AND c.sgg_cd IN ('11650', '11680')
              AND s.area_type IS NOT NULL AND s.area_type LIKE 'A%'
        """, (cas_date, cas_date))
        rows = cur.fetchall()

        # 2. 구×평형 그룹화 (적격 단지만)
        #    drop_rate, ppp 수집
        drops: Dict[str, Dict[str, List[float]]] = {
            "11650": {}, "11680": {}, "BELT": {}
        }
        ppps: Dict[str, Dict[str, List[float]]] = {
            "11650": {}, "11680": {}, "BELT": {}
        }
        sample_ns: Dict[str, Dict[str, int]] = {
            "11650": {}, "11680": {}, "BELT": {}
        }

        all_area_types = set()

        for r in rows:
            sgg = r["sgg_cd"]
            at = r["area_type"]
            dr = r["drop_rate"]
            ppp = r["price_per_pyeong"]

            # G0 제외: 토지임대부
            if "토지임대부" in str(r["complex_name"] or ""):
                continue

            # G3_INVERTED_PRICE 제외: 최근가 > 전고점 × 1.10
            med_3m = r["median_price_3m"] or 0
            peak_adj = r["peak_price_adj"] or 0
            if med_3m > (peak_adj * 1.10) and peak_adj > 0:
                continue

            # G1 제외: 12m < 3 OR 24m < 8
            n_12m = r["sample_count_12m"] or r["trade_count_12m"] or 0
            n_24m = r["sample_count_24m"] or 0
            if n_12m < 3 or n_24m < 8:
                continue

            all_area_types.add(at)

            if dr is not None and dr > 0:
                drops[sgg].setdefault(at, []).append(dr)
                drops["BELT"].setdefault(at, []).append(dr)

            if ppp is not None and ppp > 0:
                ppps[sgg].setdefault(at, []).append(ppp)
                ppps["BELT"].setdefault(at, []).append(ppp)

            tc = r["trade_count_12m"] or 0
            sample_ns[sgg][at] = sample_ns[sgg].get(at, 0) + tc
            sample_ns["BELT"][at] = sample_ns["BELT"].get(at, 0) + tc

        # 3. 전세가율 계산용 최근 전세 데이터
        #    (기존 로직 유지: 전세보증금 / 매매 중위가)

        # 4. 지역×평형별 레코드 생성
        for sgg_code in ["11650", "11680", "BELT"]:
            for at in sorted(all_area_types):
                drop_list = drops[sgg_code].get(at, [])
                ppp_list = ppps[sgg_code].get(at, [])
                sample_n = sample_ns[sgg_code].get(at, 0)

                if not drop_list:
                    continue

                median_drop = statistics.median(drop_list)
                median_ppp = statistics.median(ppp_list) if ppp_list else 0.0

                # 전세가율 중위값
                if sgg_code == "BELT":
                    cur.execute("""
                        SELECT deposit FROM trades_rent
                        WHERE area_type = ? AND monthly_rent = 0
                          AND sgg_cd IN ('11650', '11680')
                    """, (at,))
                else:
                    cur.execute("""
                        SELECT deposit FROM trades_rent
                        WHERE sgg_cd = ? AND area_type = ? AND monthly_rent = 0
                    """, (sgg_code, at))
                rent_rows = cur.fetchall()

                # 매매 중위가 추정 (적격 단지 ppp 중위 × 34평 기준)
                ref_pyeong = get_ref_pyeong(at)
                ref_price = median_ppp * ref_pyeong if median_ppp > 0 else 0.0

                jeonse_ratios = []
                for rr in rent_rows:
                    dep = rr["deposit"]
                    if ref_price > 0 and dep and dep > 0:
                        jeonse_ratios.append(dep / ref_price)
                median_jr = statistics.median(jeonse_ratios) if jeonse_ratios else 0.55

                records.append((
                    base_date, sgg_code, at,
                    median_drop, median_ppp, median_jr, sample_n, 0.0, 0.0
                ))

                n_complexes = len(drop_list)
                print(f"[RegionStats] {sgg_code}/{at}: "
                      f"median_drop={median_drop*100:.1f}% "
                      f"({n_complexes} complexes), "
                      f"median_ppp={median_ppp:.0f}")

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
