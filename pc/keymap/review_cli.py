# pc/keymap/review_cli.py
"""
미매칭 단지 또는 검수 필요(REVIEW_REQUIRED) 단지에 대해
CLI 상에서 단지 코드를 수동 매핑하거나 검수 이력을 관리하는 유틸리티 (SCORING_V2_DESIGN.md §5).
"""
import sys
from common.database import get_db_connection

def list_review_required():
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, sgg_cd, umd_nm, apt_name_raw, confidence, match_method, status
            FROM complex_key_map
            WHERE status IN ('REVIEW_REQUIRED', 'UNMATCHED')
            ORDER BY confidence DESC
        """)
        rows = cur.fetchall()
        print(f"\n[Complex Review List] 총 {len(rows)}건")
        for r in rows:
            print(f"ID: {r['id']} | {r['sgg_cd']} {r['umd_nm']} | {r['apt_name_raw']} | conf: {r['confidence']:.2f} | {r['status']}")

def apply_manual_mapping(map_id: int, target_complex_code: str):
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT sgg_cd, apt_name_raw FROM complex_key_map WHERE id = ?", (map_id,))
        row = cur.fetchone()
        if not row:
            print(f"[Error] ID {map_id}에 해당하는 매핑 정보를 찾을 수 없습니다.")
            return

        cur.execute("""
            UPDATE complex_key_map
            SET complex_code = ?, status = 'MANUAL_MATCHED', match_method = 'MANUAL'
            WHERE id = ?
        """, (target_complex_code, map_id))

        cur.execute("""
            UPDATE trades_sale SET complex_code = ?
            WHERE sgg_cd = ? AND apt_name_raw = ?
        """, (target_complex_code, row["sgg_cd"], row["apt_name_raw"]))

        cur.execute("""
            UPDATE trades_rent SET complex_code = ?
            WHERE sgg_cd = ? AND apt_name_raw = ?
        """, (target_complex_code, row["sgg_cd"], row["apt_name_raw"]))

        conn.commit()
        print(f"[Success] ID {map_id} ({row['apt_name_raw']}) -> {target_complex_code} 수동 매핑 완료")

if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1] == "list":
        list_review_required()
    elif len(sys.argv) == 4 and sys.argv[1] == "map":
        apply_manual_mapping(int(sys.argv[2]), sys.argv[3])
    else:
        print("Usage: python -m pc.keymap.review_cli [list | map <id> <complex_code>]")
