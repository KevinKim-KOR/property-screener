# -*- coding: utf-8 -*-
import os
import sys
import time
import requests
import sqlite3
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath('.'))
load_dotenv("e:/AI Study/property/.env")

def is_elem_school(name: str) -> bool:
    if not name or "초등학교" not in name:
        return False
    if any(k in name for k in ["유치원", "어린이집", "버스", "정류장", "고등학교", "대학교"]):
        return False
    return True

def is_mid_school(name: str) -> bool:
    if not name or "중학교" not in name:
        return False
    if any(k in name for k in ["고등학교", "대학교", "유치원", "어린이집", "버스", "정류장"]):
        return False
    return True

def update_all_schools_dist():
    api_key = os.environ.get("KAKAO_REST_API_KEY")
    if not api_key:
        raise ValueError("KAKAO_REST_API_KEY is not set in .env")
    
    headers = {"Authorization": f"KakaoAK {api_key.strip()}"}
    url = "https://dapi.kakao.com/v2/local/search/category.json"
    
    conn = sqlite3.connect('screener.db')
    cur = conn.cursor()
    
    cols = [r[1] for r in cur.execute("PRAGMA table_info(complexes)").fetchall()]
    if "elem_school_name" not in cols:
        cur.execute("ALTER TABLE complexes ADD COLUMN elem_school_name TEXT")
    if "mid_school_dist_m" not in cols:
        cur.execute("ALTER TABLE complexes ADD COLUMN mid_school_dist_m REAL")
    if "mid_school_name" not in cols:
        cur.execute("ALTER TABLE complexes ADD COLUMN mid_school_name TEXT")
    conn.commit()
    
    cur.execute("""
        SELECT complex_code, region_name, complex_name, lat, lng
        FROM complexes
        WHERE lat IS NOT NULL AND lat != 0 AND lng IS NOT NULL AND lng != 0
    """)
    rows = cur.fetchall()
    
    print(f"Target geocoded complexes for SC4 (school) search: {len(rows)}")
    
    elem_success_cnt = 0
    mid_success_cnt = 0
    elem_within_300m = 0
    
    for idx, (cc, reg_nm, comp_nm, lat, lng) in enumerate(rows, 1):
        elem_dist = None
        elem_name = None
        mid_dist = None
        mid_name = None
        
        for page in range(1, 4):
            params = {
                "category_group_code": "SC4",
                "x": str(lng),
                "y": str(lat),
                "radius": 2000,
                "sort": "distance",
                "page": page
            }
            try:
                res = requests.get(url, headers=headers, params=params, timeout=10)
                if res.status_code != 200:
                    break
                data = res.json()
                docs = data.get("documents", [])
                if not docs:
                    break
                for doc in docs:
                    p_name = doc.get("place_name", "")
                    d_val = float(doc.get("distance", 99999))
                    if elem_dist is None and is_elem_school(p_name):
                        elem_dist = d_val
                        elem_name = p_name
                    if mid_dist is None and is_mid_school(p_name):
                        mid_dist = d_val
                        mid_name = p_name
                if elem_dist is not None and mid_dist is not None:
                    break
            except Exception as e:
                break
                
        if elem_dist is not None:
            elem_success_cnt += 1
            if elem_dist <= 300.0:
                elem_within_300m += 1
        if mid_dist is not None:
            mid_success_cnt += 1
            
        cur.execute("""
            UPDATE complexes
            SET elem_school_dist_m = ?,
                elem_school_name = ?,
                mid_school_dist_m = ?,
                mid_school_name = ?
            WHERE complex_code = ?
        """, (elem_dist, elem_name, mid_dist, mid_name, cc))
        
        if idx % 100 == 0 or idx == len(rows):
            print(f"  [{idx}/{len(rows)}] schools checked... elem success: {elem_success_cnt} (<=300m: {elem_within_300m}), mid success: {mid_success_cnt}")
            conn.commit()
            
    conn.commit()
    
    print("\n=== [ Schools Distance Summary ] ===")
    print(f"전체 대상 단지 수: {len(rows)}곳")
    print(f"초등학교 정보 붙은 단지 수 (2km 이내): {elem_success_cnt}곳")
    print(f"중학교 정보 붙은 단지 수 (2km 이내): {mid_success_cnt}곳")
    print(f"초등학교 300m 이내인 단지 수: {elem_within_300m}곳")
    
    out = []
    out.append(f"전체 대상 단지 수: {len(rows)}곳")
    out.append(f"초등학교 정보 붙은 단지 수 (2km 이내): {elem_success_cnt}곳")
    out.append(f"중학교 정보 붙은 단지 수 (2km 이내): {mid_success_cnt}곳")
    out.append(f"초등학교 300m 이내인 단지 수: {elem_within_300m}곳")
    
    conn.close()
    
    with open(r"C:\Users\minan\.gemini\antigravity\brain\ddff3f34-9a5d-4f36-929c-f33ed2ccc290\scratch\schools_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("Report saved to scratch/schools_report.txt")

if __name__ == "__main__":
    update_all_schools_dist()
