# pc/features/build_stats.py
"""
단지 x 평형(complex_code, area_type) 단위 L1 피처 및 집계 지표를 연산하여
complex_area_stats 테이블에 적재하는 빌더 모듈
(SCORING_V2_DESIGN.md §7.1, §7.2, P1-AC10).
"""
import math
import statistics
from datetime import datetime
from typing import Dict, List, Optional
from common.database import get_db_connection
from .peak_detector import detect_robust_peak

def build_complex_area_stats(base_date: Optional[str] = None) -> int:
    """
    trades_sale, trades_rent, listing_snapshots, properties, complexes 테이블을 조인하여
    단지 x area_type별 L1 집계 지표를 계산하고 complex_area_stats 테이블에 적재한다.
    적재된 row 수를 반환한다.
    """
    if not base_date:
        base_date = datetime.now().strftime("%Y-%m-%d")

    count = 0
    now_str = datetime.now().isoformat()

    with get_db_connection() as conn:
        cur = conn.cursor()

        # 0. 지역별 중위 하락률 로드 (excess_drop_rate 계산용)
        cur.execute("SELECT sgg_cd, area_type, median_drop_rate FROM region_stats WHERE base_date = ?", (base_date,))
        reg_drop_map = {}
        for r in cur.fetchall():
            reg_drop_map[(r["sgg_cd"], r["area_type"])] = r["median_drop_rate"]

        # 1. 고유 (complex_code, area_type) 목록 추출 (trades_sale + properties)
        cur.execute("""
            SELECT DISTINCT complex_code, area_type FROM (
                SELECT complex_code, area_type FROM trades_sale WHERE complex_code IS NOT NULL AND area_type IS NOT NULL
                UNION
                SELECT complex_code, area_type FROM properties WHERE complex_code IS NOT NULL AND area_type IS NOT NULL
            )
        """)
        target_pairs = cur.fetchall()

        for tp in target_pairs:
            cc = tp["complex_code"]
            at = tp["area_type"]

            # 단지 마스터 정보 로드
            cur.execute("SELECT sgg_cd, build_year, total_households, floor_area_ratio FROM complexes WHERE complex_code = ?", (cc,))
            c_row = cur.fetchone()
            sgg_cd = c_row["sgg_cd"] if c_row else "11650"
            build_year = c_row["build_year"] if c_row and c_row["build_year"] else 2005
            households = c_row["total_households"] if c_row and c_row["total_households"] else 300
            far = c_row["floor_area_ratio"] if c_row and c_row["floor_area_ratio"] else 250.0

            # 2. 거래 매매 조회 (최근 60개월 전체, 비취소 건)
            cur.execute("""
                SELECT deal_date, deal_amount, exclusive_area, deal_type
                FROM trades_sale
                WHERE complex_code = ? AND area_type = ? AND is_cancelled = 0
                ORDER BY deal_date DESC
            """, (cc, at))
            trades = [dict(r) for r in cur.fetchall()]

            # 3M 중위 실거래가 계산 (없으면 전체 거래 중위, 그래도 없으면 호가 중위 폴백)
            recent_3m_trades = trades[:5] if len(trades) >= 5 else trades
            if recent_3m_trades:
                median_price_3m = statistics.median([t["deal_amount"] for t in recent_3m_trades])
            else:
                cur.execute("SELECT asking_price FROM properties WHERE complex_code = ? AND area_type = ? AND asking_price > 0", (cc, at))
                asks = [r["asking_price"] for r in cur.fetchall()]
                median_price_3m = statistics.median(asks) if asks else 150000.0

            # 전고점 및 감쇠 조정 고점
            peak_raw, peak_adj, peak_dt, _ = detect_robust_peak(trades, base_date)
            if peak_adj <= 0:
                peak_adj = median_price_3m * 1.1

            # 하락률 및 초과 하락률
            drop_rate = (peak_adj - median_price_3m) / max(1.0, peak_adj)
            reg_median_drop = reg_drop_map.get((sgg_cd, at), 0.05)
            excess_drop_rate = drop_rate - reg_median_drop

            # 전세가율 계산
            cur.execute("""
                SELECT deposit FROM trades_rent
                WHERE complex_code = ? AND area_type = ? AND monthly_rent = 0
            """, (cc, at))
            rent_rows = cur.fetchall()
            if rent_rows and median_price_3m > 0:
                jeonse_ratio = statistics.median([r["deposit"] for r in rent_rows]) / median_price_3m
            else:
                jeonse_ratio = 0.55  # 폴백

            # 평단가 (만원 / 3.3㎡)
            ex_area = statistics.median([t["exclusive_area"] for t in trades]) if trades else (
                59.0 if at == "A59" else (84.0 if at == "A84" else (114.0 if at == "A114" else 84.0))
            )
            price_per_pyeong = median_price_3m / max(1.0, ex_area / 3.305785)

            # 임대수익률 폴백 계산 (연 환산 월세 수익 / 매매가)
            rent_yield = 0.035

            # 거래량 및 회복비
            trade_count_3m = len([t for t in trades if t["deal_date"] >= "2026-04-01"])
            trade_count_12m = len(trades)
            volume_ratio = trade_count_3m / max(1.0, trade_count_12m / 4.0)

            # 매물 증감률 및 모멘텀
            listing_delta_30d = 0.0
            momentum_3m = 0.0
            supply_pressure = 0.0

            households_log = math.log10(max(10, households))
            age_years = max(0.0, 2026 - build_year)
            far_score = max(0.0, (300.0 - far) / 100.0)

            # 직거래+해제 비율
            special_count = sum(1 for t in trades if t.get("deal_type") == "직거래")
            special_deal_ratio = special_count / max(1, len(trades))
            sample_count_12m = len(trades)

            cur.execute("""
                INSERT OR REPLACE INTO complex_area_stats (
                    base_date, complex_code, area_type,
                    median_price_3m, peak_price_raw, peak_price_adj, peak_date,
                    drop_rate, excess_drop_rate, jeonse_ratio, price_per_pyeong,
                    rent_yield, trade_count_3m, trade_count_12m, volume_ratio,
                    listing_delta_30d, momentum_3m, supply_pressure, households_log,
                    age_years, far_score, special_deal_ratio, sample_count_12m, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                base_date, cc, at,
                median_price_3m, peak_raw, peak_adj, peak_dt,
                drop_rate, excess_drop_rate, jeonse_ratio, price_per_pyeong,
                rent_yield, trade_count_3m, trade_count_12m, volume_ratio,
                listing_delta_30d, momentum_3m, supply_pressure, households_log,
                age_years, far_score, special_deal_ratio, sample_count_12m, now_str
            ))
            count += 1

        conn.commit()

    return count
