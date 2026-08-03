# -*- coding: utf-8 -*-
import os
import sys
import time
import requests
import sqlite3
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath('.'))
load_dotenv("e:/AI Study/property/.env")

def update_all_academies_count():
    api_key = os.environ.get("KAKAO_REST_API_KEY")
    if not api_key:
        raise ValueError("KAKAO_REST_API_KEY is not set in .env")
    
    headers = {"Authorization": f"KakaoAK {api_key.strip()}"}
    url = "https://dapi.kakao.com/v2/local/search/category.json"
    
    conn = sqlite3.connect('screener.db')
    cur = conn.cursor()
    
    # Ensure academies_count column exists
    cols = [r[1] for r in cur.execute("PRAGMA table_info(complexes)").fetchall()]
    if "academies_count" not in cols:
        cur.execute("ALTER TABLE complexes ADD COLUMN academies_count INTEGER")
        print("Added column 'academies_count' to complexes table.")
    
    cur.execute("""
        SELECT complex_code, region_name, complex_name, lat, lng
        FROM complexes
        WHERE lat IS NOT NULL AND lat != 0 AND lng IS NOT NULL AND lng != 0
    """)
    rows = cur.fetchall()
    
    print(f"Target geocoded complexes for AC5 (academy) search: {len(rows)}")
    
    success_cnt = 0
    fail_cnt = 0
    
    for idx, (cc, reg_nm, comp_nm, lat, lng) in enumerate(rows, 1):
        params = {
            "category_group_code": "AC5",
            "x": str(lng),
            "y": str(lat),
            "radius": 1000
        }
        
        count_val = None
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                count_val = int(data.get("meta", {}).get("total_count", 0))
        except Exception as e:
            pass
        
        if count_val is not None:
            success_cnt += 1
            cur.execute("""
                UPDATE complexes
                SET academies_count = ?
                WHERE complex_code = ?
            """, (count_val, cc))
        else:
            fail_cnt += 1
            cur.execute("""
                UPDATE complexes
                SET academies_count = NULL
                WHERE complex_code = ?
            """, (cc,))
        
        if idx % 100 == 0 or idx == len(rows):
            print(f"  [{idx}/{len(rows)}] academies checked... success: {success_cnt}, fail: {fail_cnt}")
            conn.commit()
            
    conn.commit()
    
    print("\n=== [ Academies Density Summary ] ===")
    print(f"학원가 정보 붙은 단지 수: {success_cnt}곳")
    print(f"조회 실패(또는 미확인) 단지 수: {fail_cnt}곳")
    
    print("\n=== [ 학원 개수 상위 10곳 ] ===")
    cur.execute("""
        SELECT region_name, complex_name, academies_count
        FROM complexes
        WHERE academies_count IS NOT NULL
        ORDER BY academies_count DESC, complex_name ASC
        LIMIT 10
    """)
    top10 = cur.fetchall()
    out = []
    out.append(f"학원가 정보 붙은 단지 수: {success_cnt}곳")
    out.append(f"조회 실패(또는 미확인) 단지 수: {fail_cnt}곳\n")
    out.append("=== 학원 개수 상위 10곳 ===")
    for idx, (reg, comp, cnt) in enumerate(top10, 1):
        line = f"{idx:2d}위 | {reg} | {comp} | 학원 {cnt}곳"
        print(" ", line)
        out.append(line)
        
    print("\n=== [ 학원 개수 하위 10곳 ] ===")
    cur.execute("""
        SELECT region_name, complex_name, academies_count
        FROM complexes
        WHERE academies_count IS NOT NULL
        ORDER BY academies_count ASC, complex_name ASC
        LIMIT 10
    """)
    bot10 = cur.fetchall()
    out.append("\n=== 학원 개수 하위 10곳 ===")
    for idx, (reg, comp, cnt) in enumerate(bot10, 1):
        line = f"{idx:2d}위 | {reg} | {comp} | 학원 {cnt}곳"
        print(" ", line)
        out.append(line)
        
    conn.close()
    
    with open(r"C:\Users\minan\.gemini\antigravity\brain\ddff3f34-9a5d-4f36-929c-f33ed2ccc290\scratch\academies_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("Report saved to scratch/academies_report.txt")

if __name__ == "__main__":
    update_all_academies_count()
