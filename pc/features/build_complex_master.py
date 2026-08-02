# pc/features/build_complex_master.py
"""
국토부 실거래가 CSV 데이터(trades_sale)에서 Phase 1-A 단지 마스터(complexes)를 생성하고,
실거래에서 관측된 전용면적 min/max(area_min_m2, area_max_m2)를 저장하는 모듈.
단지 매칭(네이버 연동 등)은 Phase 1-B로 미루고, 국토부 데이터 자체를 마스터로 사용한다.
"""
import hashlib
from datetime import datetime
from common.database import get_db_connection

def build_complex_master_from_molit() -> int:
    """
    trades_sale 테이블을 집계하여 complexes 테이블을 재구성하고,
    trades_sale, trades_rent의 complex_code 컬럼을 업데이트한다.
    생성된 단지 마스터 건수를 반환한다.
    """
    now_str = datetime.now().isoformat()
    count = 0

    with get_db_connection() as conn:
        cur = conn.cursor()

        # 1. trades_sale에서 고유 단지 단위 (sgg_cd, umd_nm, bonbun, bubun, apt_name_raw, build_year) 집계
        cur.execute("""
            SELECT 
                sgg_cd,
                umd_nm,
                bonbun,
                bubun,
                apt_name_raw,
                build_year,
                MIN(exclusive_area) AS min_area,
                MAX(exclusive_area) AS max_area,
                COUNT(*) AS trade_cnt
            FROM trades_sale
            WHERE sgg_cd IN ('11650', '11680') AND apt_name_raw IS NOT NULL
            GROUP BY sgg_cd, umd_nm, bonbun, bubun, apt_name_raw, build_year
        """)
        groups = [dict(r) for r in cur.fetchall()]
        assert all(str(g["sgg_cd"]) in ("11650", "11680") for g in groups), "C8 위반: 서초구/강남구 외 다른 시군구 데이터가 적재되었습니다!"

        # 2. complexes 테이블 클린업 (Phase 1-A 전용 국토부 마스터 적재)
        cur.execute("DELETE FROM complexes")

        complex_rows = []
        sale_updates = []
        rent_updates = []

        for g in groups:
            sgg_cd = g["sgg_cd"]
            umd_nm = g.get("umd_nm") or ""
            bonbun = g.get("bonbun") or 0
            bubun = g.get("bubun") or 0
            apt_name = g["apt_name_raw"]
            build_year = g.get("build_year") or 0
            min_a = g.get("min_area") or 0.0
            max_a = g.get("max_area") or 0.0

            # 결정론적 complex_code 생성
            raw_key = f"{sgg_cd}_{umd_nm}_{bonbun}_{bubun}_{apt_name}_{build_year}"
            md5_hash = hashlib.md5(raw_key.encode("utf-8")).hexdigest()[:8].upper()
            c_code = f"MOLIT_{sgg_cd}_{md5_hash}"

            # total_households는 임시로 300(폴백 기준), brand는 apt_name 앞 단어
            brand = apt_name.split()[0] if apt_name else ""

            complex_rows.append((
                c_code,
                apt_name,
                str(sgg_cd),
                "", # umd_cd
                umd_nm,
                int(build_year) if build_year else 2005,
                300, # total_households
                1,   # total_dongs
                250.0, # floor_area_ratio
                20.0,  # building_coverage
                brand,
                0.0, 0.0, # lat, lng
                500.0, "", 10.0, # subway_dist_m, subway_name, subway_walk_min
                300.0, # elem_school_dist_m
                25.0,  # cbd_transit_min
                int(bonbun),
                int(bubun),
                "", # road_name
                float(min_a),
                float(max_a),
                now_str
            ))

            sale_updates.append((c_code, sgg_cd, umd_nm, bonbun, bubun, apt_name, build_year))
            rent_updates.append((c_code, sgg_cd, apt_name))

        # 3. complexes 대량 적재
        cur.executemany("""
            INSERT OR REPLACE INTO complexes (
                complex_code, complex_name, sgg_cd, umd_cd, region_name,
                build_year, total_households, total_dongs, floor_area_ratio, building_coverage,
                brand, lat, lng, subway_dist_m, subway_name, subway_walk_min,
                elem_school_dist_m, cbd_transit_min, bonbun, bubun, road_name,
                area_min_m2, area_max_m2, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, complex_rows)

        count = len(complex_rows)

        # 4. trades_sale에 complex_code 매핑 업데이트
        cur.executemany("""
            UPDATE trades_sale
            SET complex_code = ?
            WHERE sgg_cd = ? AND umd_nm = ? AND bonbun = ? AND bubun = ? AND apt_name_raw = ? AND build_year = ?
        """, sale_updates)

        # 5. trades_rent에 complex_code 매핑 업데이트
        cur.executemany("""
            UPDATE trades_rent
            SET complex_code = ?
            WHERE sgg_cd = ? AND apt_name_raw = ?
        """, rent_updates)

        conn.commit()

    return count

if __name__ == "__main__":
    c = build_complex_master_from_molit()
    print(f"Built {c} complex master rows from MOLIT CSV trades.")
