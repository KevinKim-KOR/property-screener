# pc/features/build_stats.py
"""
단지 x 평형(complex_code, area_type) 단위 L1 피처 및 집계 지표를 연산하여
complex_area_stats 테이블에 적재하는 빌더 모듈
(SCORING_V2_DESIGN.md §7.1, §7.2, P1-AC10).
"""
import math
import sqlite3
import statistics
from datetime import datetime
from typing import Dict, List, Optional
from common.database import get_db_connection
from .peak_detector import detect_robust_peak

def get_ref_pyeong_m2(at: str) -> float:
    if not at or not at.startswith("A"):
        return 84.0
    parts = at[1:].split("_")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return (float(parts[0]) + float(parts[1])) / 2.0
    return {"A59": 59.0, "A84": 84.0, "A114": 114.0}.get(at, 84.0)

def build_complex_area_stats(base_date: str = "2026-07-31") -> int:
    """
    SCORING_V2_DESIGN.md §3 기준 complex_area_stats 테이블 재생성.
    v4.1: 거래 창 조건 (3개월 1건 미만 시 6개월 -> 12개월 -> 제외)
    v4.2: 5㎡ 단위 버킷 (A50_55 ~ A130_135) 계산 적용
    """
    count = 0
    now_str = datetime.now().isoformat()

    with get_db_connection() as conn:
        cur = conn.cursor()
        for _alter in (
            "ALTER TABLE complex_area_stats ADD COLUMN last_deal_date TEXT",
            "ALTER TABLE complex_area_stats ADD COLUMN price_window TEXT",
        ):
            try:
                cur.execute(_alter)
            except sqlite3.OperationalError:
                # 의도적 삼킴: 컬럼이 이미 있으면 실패가 정상 (멱등성 보장).
                pass
        try:
            cur.execute("ALTER TABLE complex_area_stats ADD COLUMN sample_count_24m INTEGER")
        except sqlite3.OperationalError:
            # 의도적 삼킴: 컬럼이 이미 있으면 실패가 정상 (멱등성 보장).
            # sqlite3.OperationalError 로 한정해 다른 예외는 드러나게 한다.
            pass
        cur.execute("DELETE FROM complex_area_stats WHERE base_date = ?", (base_date,))

        # 0. 지역별 중위 하락률 로드 (excess_drop_rate 계산용)
        cur.execute("SELECT sgg_cd, area_type, median_drop_rate FROM region_stats WHERE base_date = ?", (base_date,))
        reg_drop_map = {}
        for r in cur.fetchall():
            reg_drop_map[(r["sgg_cd"], r["area_type"])] = r["median_drop_rate"]

        # 1. 고유 (complex_code, area_type) 목록 추출
        cur.execute("""
            SELECT DISTINCT t.complex_code, t.area_type 
            FROM trades_sale t
            JOIN complexes c ON t.complex_code = c.complex_code
            WHERE c.sgg_cd IN ('11650', '11680') AND t.area_type IS NOT NULL AND t.area_type LIKE 'A%'
        """)
        target_pairs = cur.fetchall()

        for tp in target_pairs:
            cc = tp["complex_code"]
            at = tp["area_type"]

            # 단지 마스터 정보 로드
            cur.execute("SELECT sgg_cd, build_year, total_households, floor_area_ratio FROM complexes WHERE complex_code = ?", (cc,))
            c_row = cur.fetchone()
            sgg_cd = c_row["sgg_cd"] if c_row else "11650"
            assert str(sgg_cd) in ("11650", "11680"), f"C8 위반: sgg_cd {sgg_cd} 가 감지되었습니다."
            build_year = c_row["build_year"] if c_row and c_row["build_year"] else 2005
            households = c_row["total_households"] if c_row and c_row["total_households"] else 300
            far = c_row["floor_area_ratio"] if c_row and c_row["floor_area_ratio"] else 250.0

            # 2. 거래 매매 조회 (최근 60개월 전체, 비취소 건)
            # 2. 거래 매매 조회 (최근 60개월 전체, 비취소 및 직거래 제외 유효 거래 §2.4)
            cur.execute("""
                SELECT deal_date, deal_amount, exclusive_area, deal_type
                FROM trades_sale
                WHERE complex_code = ? AND area_type = ? AND is_cancelled = 0 AND deal_type != '직거래'
                ORDER BY deal_date DESC
            """, (cc, at))
            trades = [dict(r) for r in cur.fetchall()]

            # 24개월/12개월/6개월/3개월 유효 거래 목록 분리 (§3.1, §3.4, v4.2 §11.2)
            # ⚠️ 기간 창의 시작일이 하드코딩되어 있다. base_date 기준 상대 계산이 아니라
            #    시간이 갈수록 창이 넓어진다(2026-08-27 기준 3M 창이 실제 3.9개월,
            #    12M 창이 13.9개월). price_window 컬럼의 '3개월/6개월/12개월' 표기도
            #    그만큼 실제보다 짧게 말하는 셈이다. 창을 base_date 상대로 바꾸면
            #    적격 단지 수와 하락률이 모두 달라지므로 별도 판단이 필요하다.
            trades_24m = [t for t in trades if str(t.get("deal_date", "")) >= "2024-07-01"]
            trades_12m = [t for t in trades if str(t.get("deal_date", "")) >= "2025-07-01"]
            trades_6m  = [t for t in trades if str(t.get("deal_date", "")) >= "2026-02-01"]
            trades_3m  = [t for t in trades if str(t.get("deal_date", "")) >= "2026-05-01"]

            # 마지막 실거래 계약일. "이 단지가 최근에 실제로 거래됐나"를 보기 위한 값으로,
            # 아래 median_price_3m(기간 중위값)과는 다른 정보다.
            last_deal_date = max((str(t.get("deal_date") or "") for t in trades), default="") or None

            # 최근 거래가: 최소 3건 요구 (3개월 3건+ -> 6개월 3건+ -> 12개월 3건+ -> 3건 미만 시 0.0 제외)
            # 어느 창에서 나온 값인지 함께 남긴다. 창이 넓어질수록 '최근 시세'라기 어렵고
            # 하락률도 그만큼 오래된 기준과 비교한 값이 되므로, 화면에서 구분할 수 있어야 한다.
            if len(trades_3m) >= 3:
                median_price_3m = statistics.median([t["deal_amount"] for t in trades_3m])
                price_window = "3M"
            elif len(trades_6m) >= 3:
                median_price_3m = statistics.median([t["deal_amount"] for t in trades_6m])
                price_window = "6M"
            elif len(trades_12m) >= 3:
                median_price_3m = statistics.median([t["deal_amount"] for t in trades_12m])
                price_window = "12M"
            else:
                median_price_3m = 0.0
                price_window = None

            # 전고점 (추정치/기본값 폐지 §10 D2)
            peak_raw, peak_adj, peak_dt, _ = detect_robust_peak(trades, base_date)

            # 하락률 및 초과 하락률 (§3.3)
            if peak_adj > 0 and median_price_3m > 0:
                if median_price_3m > peak_adj:
                    drop_rate = 0.0
                else:
                    drop_rate = (peak_adj - median_price_3m) / float(peak_adj)
            else:
                drop_rate = 0.0
            reg_median_drop = reg_drop_map.get((sgg_cd, at), 0.05)
            excess_drop_rate = drop_rate - reg_median_drop

            # 전세가율 계산 (최근 6개월, 순수 전세, 동일 단지 및 5㎡ 버킷, 최소 2건 요구)
            cur.execute("""
                SELECT deposit FROM trades_rent
                WHERE complex_code = ? AND area_type = ? 
                  AND (monthly_rent = 0 OR monthly_rent IS NULL) 
                  AND deal_date >= '2026-02-01'
            """, (cc, at))
            rent_rows = cur.fetchall()
            if len(rent_rows) >= 2 and median_price_3m > 0:
                jeonse_ratio = statistics.median([r["deposit"] for r in rent_rows]) / median_price_3m
            else:
                jeonse_ratio = None

            # 평단가 (만원 / 3.3㎡)
            ex_area = statistics.median([t["exclusive_area"] for t in trades]) if trades else get_ref_pyeong_m2(at)
            price_per_pyeong = median_price_3m / max(1.0, ex_area / 3.305785) if median_price_3m > 0 else 0.0

            # 임대수익률 폴백 계산 (연 환산 월세 수익 / 매매가)
            rent_yield = 0.035

            # 거래량 및 회복비 (§3.4)
            trade_count_3m = len(trades_3m)
            trade_count_12m = len(trades_12m)
            volume_ratio = trade_count_3m / max(0.01, trade_count_12m / 4.0)

            # 매물 증감률 및 모멘텀
            listing_delta_30d = 0.0
            momentum_3m = 0.0
            supply_pressure = 0.0

            households_log = math.log10(max(10, households))
            age_years = max(0.0, 2026 - build_year)
            far_score = max(0.0, (300.0 - far) / 100.0)

            # M3, M6, M12 계산 (각 구간 및 이전 구간 최소 2건 요구)
            trades_prev_3m  = [t for t in trades if "2026-02-01" <= str(t.get("deal_date", "")) < "2026-05-01"]
            trades_prev_6m  = [t for t in trades if "2025-08-01" <= str(t.get("deal_date", "")) < "2026-02-01"]
            trades_prev_12m = [t for t in trades if "2024-07-01" <= str(t.get("deal_date", "")) < "2025-07-01"]

            m3 = (statistics.median([t["deal_amount"] for t in trades_3m]) / statistics.median([t["deal_amount"] for t in trades_prev_3m]) - 1.0) if (len(trades_3m) >= 2 and len(trades_prev_3m) >= 2) else None
            m6 = (statistics.median([t["deal_amount"] for t in trades_6m]) / statistics.median([t["deal_amount"] for t in trades_prev_6m]) - 1.0) if (len(trades_6m) >= 2 and len(trades_prev_6m) >= 2) else None
            m12 = (statistics.median([t["deal_amount"] for t in trades_12m]) / statistics.median([t["deal_amount"] for t in trades_prev_12m]) - 1.0) if (len(trades_12m) >= 2 and len(trades_prev_12m) >= 2) else None

            # 직거래+해제 비율 (12개월 전체 거래 중 취소/직거래 비중 §4)
            cur.execute("""
                SELECT deal_type, is_cancelled
                FROM trades_sale
                WHERE complex_code = ? AND area_type = ? AND deal_date >= '2025-07-01'
            """, (cc, at))
            all_12m = [dict(r) for r in cur.fetchall()]
            special_count = sum(1 for t in all_12m if t.get("deal_type") == "직거래" or t.get("is_cancelled") == 1)
            special_deal_ratio = (special_count / max(1, len(all_12m))) if all_12m else 0.0
            sample_count_12m = trade_count_12m
            sample_count_24m = len(trades_24m)

            cur.execute("""
                INSERT OR REPLACE INTO complex_area_stats (
                    base_date, complex_code, area_type,
                    median_price_3m, peak_price_raw, peak_price_adj, peak_date,
                    drop_rate, excess_drop_rate, jeonse_ratio, price_per_pyeong,
                    rent_yield, trade_count_3m, trade_count_12m, volume_ratio,
                    listing_delta_30d, momentum_3m, supply_pressure, households_log,
                    age_years, far_score, special_deal_ratio, sample_count_12m, sample_count_24m,
                    m3, m6, m12, last_deal_date, price_window, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                base_date, cc, at,
                median_price_3m, peak_raw, peak_adj, peak_dt,
                drop_rate, excess_drop_rate, jeonse_ratio, price_per_pyeong,
                rent_yield, trade_count_3m, trade_count_12m, volume_ratio,
                listing_delta_30d, momentum_3m, supply_pressure, households_log,
                age_years, far_score, special_deal_ratio, sample_count_12m, sample_count_24m,
                m3, m6, m12, last_deal_date, price_window, now_str
            ))
            count += 1

        conn.commit()

    return count
