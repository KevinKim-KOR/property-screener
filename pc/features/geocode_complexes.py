# -*- coding: utf-8 -*-
import os
import sys
import time
import requests
import sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from pc.features.api_failures import ApiFailureTracker

sys.path.insert(0, os.path.abspath('.'))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

SGG_MAP = {
    "11650": "서울 서초구",
    "11680": "서울 강남구"
}

def geocode_all_complexes():
    api_key = os.environ.get("KAKAO_REST_API_KEY")
    if not api_key:
        raise ValueError("KAKAO_REST_API_KEY is not set in .env")
    
    headers = {"Authorization": f"KakaoAK {api_key.strip()}"}
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    
    conn = sqlite3.connect('screener.db')
    cur = conn.cursor()
    
    cur.execute("SELECT count(*) FROM complexes")
    total_cnt = cur.fetchone()[0]
    
    cur.execute("""
        SELECT complex_code, sgg_cd, region_name, complex_name, bonbun, bubun, road_name
        FROM complexes
        WHERE lat IS NULL OR lat = 0 OR lng IS NULL OR lng = 0
    """)
    rows = cur.fetchall()
    
    print(f"Total complexes: {total_cnt}, to geocode: {len(rows)}")
    
    # 카카오 API 호출 실패 집계 (개별은 넘기되 과반 실패면 중단)
    api_tracker = ApiFailureTracker("지오코딩", len(rows))
    success_cnt = 0
    fail_cnt = 0
    failed_list = []
    
    now_str = datetime.now().isoformat()
    
    for idx, (cc, sgg_cd, reg_nm, comp_nm, bonbun, bubun, road_nm) in enumerate(rows, 1):
        gu_str = SGG_MAP.get(str(sgg_cd), "서울")
        lat, lng = None, None
        
        # 1. 시군구 + 본번-부번 조합 시도
        if bonbun and int(bonbun) > 0:
            if bubun and int(bubun) > 0:
                addr1 = f"{gu_str} {reg_nm} {int(bonbun)}-{int(bubun)}"
            else:
                addr1 = f"{gu_str} {reg_nm} {int(bonbun)}"
            
            try:
                res = requests.get(url, headers=headers, params={"query": addr1}, timeout=10)
                if res.status_code == 200:
                    docs = res.json().get("documents", [])
                    if docs:
                        lat = float(docs[0]["y"])
                        lng = float(docs[0]["x"])
            except Exception as e:
                # 개별 실패는 넘어가되 집계한다. 과반 실패면 tracker 가 중단시킨다.
                api_tracker.record_failure(f"{comp_nm}/지번", e)
        
        # 2. 실패하면 도로명 주소로 재시도
        if lat is None:
            effective_road = road_nm.strip() if road_nm else ""
            if not effective_road:
                # Check trades_sale for a road_name
                cur.execute("""
                    SELECT road_name FROM trades_sale
                    WHERE complex_code = ? AND road_name IS NOT NULL AND road_name != ''
                    LIMIT 1
                """, (cc,))
                rrow = cur.fetchone()
                if rrow and rrow[0]:
                    effective_road = rrow[0].strip()
            
            if effective_road:
                addr2 = f"{gu_str} {effective_road}"
                try:
                    res = requests.get(url, headers=headers, params={"query": addr2}, timeout=10)
                    if res.status_code == 200:
                        docs = res.json().get("documents", [])
                        if docs:
                            lat = float(docs[0]["y"])
                            lng = float(docs[0]["x"])
                except Exception as e:
                    api_tracker.record_failure(f"{comp_nm}/도로명", e)
        
        # 3. 결과 처리
        if lat is not None and lng is not None:
            success_cnt += 1
            cur.execute("""
                UPDATE complexes
                SET lat = ?, lng = ?, updated_at = ?
                WHERE complex_code = ?
            """, (lat, lng, now_str, cc))
        else:
            fail_cnt += 1
            failed_list.append((cc, reg_nm, comp_nm, bonbun, bubun, road_nm))
        
        if idx % 100 == 0 or idx == len(rows):
            print(f"  [{idx}/{len(rows)}] geocoded... success: {success_cnt}, fail: {fail_cnt}")
            conn.commit()
    
    conn.commit()
    
    # Check total already geocoded in DB
    cur.execute("SELECT count(*) FROM complexes WHERE lat IS NOT NULL AND lat != 0 AND lng IS NOT NULL AND lng != 0")
    total_geocoded = cur.fetchone()[0]
    total_failed = total_cnt - total_geocoded
    
    conn.close()
    
    print("\n=== [ Geocode Summary ] ===")
    print(f"전체 단지 수: {total_cnt}")
    print(f"좌표 확보: {total_geocoded}")
    print(f"실패: {total_failed}")
    
    api_tracker.report()
    print(f"\n=== [ 실패한 단지 목록 (총 {len(failed_list)}곳 중 앞 10곳) ] ===")
    for idx, (cc, reg_nm, comp_nm, bonbun, bubun, road_nm) in enumerate(failed_list[:10], 1):
        print(f"  {idx}. [{reg_nm}] {comp_nm} | 본부번:{bonbun}-{bubun} | 도로명:{road_nm}")

    # Write report to file for inspection
    out = []
    out.append(f"전체 단지 수: {total_cnt}")
    out.append(f"좌표 확보: {total_geocoded}")
    out.append(f"실패: {total_failed}\n")
    out.append(f"=== 실패한 단지 목록 ({len(failed_list)}곳) ===")
    for idx, (cc, reg_nm, comp_nm, bonbun, bubun, road_nm) in enumerate(failed_list, 1):
        out.append(f"{idx}. [{reg_nm}] {comp_nm} | 본번:{bonbun} 부번:{bubun} | 도로명:{road_nm}")
    
    report_path = PROJECT_ROOT / "reports" / "geocode_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"Report saved to {report_path}")

if __name__ == "__main__":
    geocode_all_complexes()
