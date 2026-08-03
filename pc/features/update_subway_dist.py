# -*- coding: utf-8 -*-
import os
import sys
import time
import requests
import sqlite3
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath('.'))
load_dotenv("e:/AI Study/property/.env")

def clean_subway_name(place_name: str) -> str:
    name = place_name.split()[0]
    if "(" in name:
        name = name.split("(")[0]
        if not name.endswith("역"):
            name += "역"
    elif not name.endswith("역"):
        name += "역"
    return name

def update_all_subway_dist():
    api_key = os.environ.get("KAKAO_REST_API_KEY")
    if not api_key:
        raise ValueError("KAKAO_REST_API_KEY is not set in .env")
    
    headers = {"Authorization": f"KakaoAK {api_key.strip()}"}
    url = "https://dapi.kakao.com/v2/local/search/category.json"
    
    conn = sqlite3.connect('screener.db')
    cur = conn.cursor()
    
    cur.execute("""
        SELECT complex_code, region_name, complex_name, lat, lng
        FROM complexes
        WHERE lat IS NOT NULL AND lat != 0 AND lng IS NOT NULL AND lng != 0
    """)
    rows = cur.fetchall()
    
    print(f"Target geocoded complexes for subway distance: {len(rows)}")
    
    success_cnt = 0
    empty_cnt = 0
    
    for idx, (cc, reg_nm, comp_nm, lat, lng) in enumerate(rows, 1):
        params = {
            "category_group_code": "SW8",
            "x": str(lng),
            "y": str(lat),
            "radius": 1500,
            "sort": "distance"
        }
        
        dist_m = None
        s_name = ""
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code == 200:
                docs = res.json().get("documents", [])
                if docs:
                    d = docs[0]
                    dist_val = float(d["distance"])
                    if dist_val <= 1500.0:
                        dist_m = dist_val
                        s_name = clean_subway_name(d["place_name"])
        except Exception as e:
            pass
        
        if dist_m is not None and s_name:
            success_cnt += 1
            cur.execute("""
                UPDATE complexes
                SET subway_dist_m = ?, subway_name = ?
                WHERE complex_code = ?
            """, (dist_m, s_name, cc))
        else:
            empty_cnt += 1
            cur.execute("""
                UPDATE complexes
                SET subway_dist_m = NULL, subway_name = ''
                WHERE complex_code = ?
            """, (cc,))
        
        if idx % 100 == 0 or idx == len(rows):
            print(f"  [{idx}/{len(rows)}] subway checked... success: {success_cnt}, empty(>1.5km): {empty_cnt}")
            conn.commit()
            
    conn.commit()
    
    print("\n=== [ Subway Distance Summary ] ===")
    print(f"역세권 정보 붙은 단지 수: {success_cnt}곳")
    print(f"1.5km 초과(또는 미발견)로 빈칸인 곳: {empty_cnt}곳")
    
    print("\n=== [ 거리 가까운 순 상위 10곳 ] ===")
    cur.execute("""
        SELECT region_name, complex_name, subway_name, subway_dist_m
        FROM complexes
        WHERE subway_dist_m IS NOT NULL AND subway_dist_m <= 1500
        ORDER BY subway_dist_m ASC
        LIMIT 10
    """)
    top10 = cur.fetchall()
    out = []
    out.append(f"역세권 정보 붙은 단지 수: {success_cnt}곳")
    out.append(f"1.5km 초과(또는 미발견)로 빈칸인 곳: {empty_cnt}곳\n")
    out.append("=== 거리 가까운 순 상위 10곳 ===")
    for idx, (reg, comp, sname, sdist) in enumerate(top10, 1):
        line = f"{idx:2d}위 | {reg} | {comp} | {sname} {int(round(sdist))}m"
        print(" ", line)
        out.append(line)
        
    conn.close()
    
    with open(r"C:\Users\minan\.gemini\antigravity\brain\ddff3f34-9a5d-4f36-929c-f33ed2ccc290\scratch\subway_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("Report saved to scratch/subway_report.txt")

if __name__ == "__main__":
    update_all_subway_dist()
