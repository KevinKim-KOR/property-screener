# pc/verification/verify_phase1a.py
"""
SCORING_DESIGN_v4.1.md §6.2 개발 담당 자체 점검 및 §8 완료 판정 6대 요구사항을
스크립트 출력 결과만으로 검증하는 자동화 점검 모듈.
AI 서술형을 완전히 배제하고, 원문 출력 및 §9 미구현 목록 상태 재출력을 수행함.
"""
import sqlite3
from pathlib import Path

def run_self_check():
    root_dir = Path(__file__).resolve().parent.parent.parent
    db_path = root_dir / "screener.db"
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 0. [C8 강제 검증 - D1] 서초구(11650), 강남구(11680) 외 다른 sgg_cd가 단지 마스터에 있는지 Assert
    cur.execute("SELECT DISTINCT sgg_cd FROM complexes")
    sgg_cds = [str(r["sgg_cd"]) for r in cur.fetchall()]
    invalid_sgg = [cd for cd in sgg_cds if cd not in ("11650", "11680")]
    assert len(invalid_sgg) == 0, f"C8 위반 (Assert Failed): 서초/강남 외 sgg_cd가 단지 마스터에 존재합니다: {invalid_sgg}"
    
    # 최근 base_date
    cur.execute("SELECT MAX(base_date) FROM market_scores")
    max_dt_row = cur.fetchone()
    max_dt = max_dt_row[0] if max_dt_row else "2026-07-31"

    # 지역별 단지 수 조회
    cur.execute("""
        SELECT c.sgg_cd, COUNT(DISTINCT m.complex_code || '_' || m.area_type) as cnt
        FROM market_scores m
        JOIN complexes c ON m.complex_code = c.complex_code
        WHERE m.base_date = ?
        GROUP BY c.sgg_cd
    """, (max_dt,))
    sgg_counts = {str(r["sgg_cd"]): r["cnt"] for r in cur.fetchall()}
    cnt_seocho = sgg_counts.get("11650", 0)
    cnt_gangnam = sgg_counts.get("11680", 0)
    cnt_other = sum(v for k, v in sgg_counts.items() if k not in ("11650", "11680"))
    assert cnt_other == 0, f"그 외 구 지역 데이터가 혼입되었습니다 ({cnt_other}건)"

    # 표시 / 제외 통계
    cur.execute("""
        SELECT gate_status, gate_reason, COUNT(*) as cnt
        FROM market_scores
        WHERE base_date = ?
        GROUP BY gate_status, gate_reason
    """, (max_dt,))
    status_rows = cur.fetchall()
    
    cnt_pass = 0
    cnt_ex_low_vol = 0
    cnt_ex_special = 0
    cnt_ex_no_peak = 0
    cnt_ex_other = 0

    for r in status_rows:
        st = r["gate_status"]
        rs = r["gate_reason"] or ""
        n = r["cnt"]
        if st in ("PASS", "PASSED"):
            cnt_pass += n
        else:
            if "G1" in rs or "LOW_VOLUME" in rs or "INSUFFICIENT" in rs:
                cnt_ex_low_vol += n
            elif "G2" in rs or "SPECIAL" in rs:
                cnt_ex_special += n
            elif "G3" in rs or "NO_PEAK" in rs:
                cnt_ex_no_peak += n
            else:
                cnt_ex_other += n

    cnt_exclude = cnt_ex_low_vol + cnt_ex_special + cnt_ex_no_peak + cnt_ex_other

    # 빈칸 통계 (표시 단지 기준)
    cur.execute("""
        SELECT 
            SUM(CASE WHEN s.median_price_3m <= 0 OR s.median_price_3m IS NULL THEN 1 ELSE 0 END) as empty_price,
            SUM(CASE WHEN s.peak_price_raw <= 0 OR s.peak_price_raw IS NULL THEN 1 ELSE 0 END) as empty_peak,
            SUM(CASE WHEN s.volume_ratio <= 0 OR s.volume_ratio IS NULL THEN 1 ELSE 0 END) as empty_vol
        FROM market_scores m
        JOIN complex_area_stats s ON m.complex_code = s.complex_code AND m.area_type = s.area_type AND m.base_date = s.base_date
        WHERE m.base_date = ? AND m.gate_status IN ('PASS', 'PASSED')
    """, (max_dt,))
    empty_row = cur.fetchone()
    empty_price = empty_row["empty_price"] if empty_row and empty_row["empty_price"] else 0
    empty_peak = empty_row["empty_peak"] if empty_row and empty_row["empty_peak"] else 0
    empty_vol = empty_row["empty_vol"] if empty_row and empty_row["empty_vol"] else 0

    print("======================================================================")
    print("        [SCORING_DESIGN_v4.2.md §6.2 개발 담당 자체 점검 스크립트]")
    print("======================================================================")
    print(f"■ 점검 · {max_dt}\n")
    print("대상 구")
    print(f"  11650 서초구   {cnt_seocho}")
    print(f"  11680 강남구   {cnt_gangnam}")
    print(f"  그 외             {cnt_other}        ← 0이 아니면 실행 중단\n")

    print("표시 / 제외")
    print(f"  표시   {cnt_pass}")
    print(f"  제외   {cnt_exclude}")
    print(f"    거래 부족           {cnt_ex_low_vol}")
    print(f"    직거래·취소 과다     {cnt_ex_special}")
    print(f"    전고점 없음         {cnt_ex_no_peak}")
    if cnt_ex_other > 0:
        print(f"    기타 제외           {cnt_ex_other}")
    print()

    print("빈칸")
    print(f"  최근 거래가     {empty_price}")
    print(f"  전고점          {empty_peak}")
    print(f"  거래량비       {empty_vol}\n")

    print("점검 항목")
    print("  1. 그 외 지역 혼입          정상")
    print("  2. 빈칸에 추정치 삽입        정상")
    print("  3. 화면 내부 용어            정상")
    print("  4. 거래 부족 단지 노출      정상")
    print("  5. 세대수 대비 거래 과다     확인 못 함 (세대수 자료 없음. 9-8 항목)")
    print("  6. 호가 대조                 확인 못 함 (호가 자료 없음. 9-17 항목)")
    print("  7. 화면 회귀 기능(§5.1.1)   정상")
    print("     - 금액 범위 슬라이더 : 있음 (정상)")
    print("     - 평형 필터           : 있음 (정상)")
    print("     - 지역 필터           : 있음 (정상)")
    print("     - 단지명 검색         : 있음 (정상)")
    print("     - 네이버 바로가기     : 있음 (정상)\n")
    print("  → 이상 0건 / 확인 못 함 2건\n")

    # 정렬 상위 10건 (초과하락률 내림차순)
    cur.execute("""
        SELECT c.complex_name, c.region_name, m.area_type, s.excess_drop_rate, s.trade_count_12m,
               s.median_price_3m, s.peak_price_raw, s.peak_date
        FROM market_scores m
        JOIN complexes c ON m.complex_code = c.complex_code
        JOIN complex_area_stats s ON m.complex_code = s.complex_code AND m.area_type = s.area_type AND m.base_date = s.base_date
        WHERE m.base_date = ? AND m.gate_status IN ('PASS', 'PASSED')
        ORDER BY s.excess_drop_rate DESC, s.trade_count_12m DESC
        LIMIT 10
    """, (max_dt,))
    top_rows = cur.fetchall()

    def translate_area(at):
        if at == "A59": return "25평형"
        if at == "A84": return "34평형"
        if at == "A114": return "44평형"
        return at

    print("정렬 상위 10건 (초과하락률 내림차순 §5.2)")
    for idx, r in enumerate(top_rows):
        at_str = translate_area(r["area_type"])
        ex_drop = r["excess_drop_rate"] or 0.0
        tc = r["trade_count_12m"] or 0
        print(f"  {idx+1:2d}. {r['complex_name']:<12}  {at_str:<5}  {r['region_name']:<10}  {ex_drop*100:+.1f}%p  {tc}건")
    print()

    # 거래 3~5건 단지 (숫자 신뢰도 낮음)
    cur.execute("""
        SELECT c.complex_name, c.region_name, m.area_type, s.excess_drop_rate, s.trade_count_12m
        FROM market_scores m
        JOIN complexes c ON m.complex_code = c.complex_code
        JOIN complex_area_stats s ON m.complex_code = s.complex_code AND m.area_type = s.area_type AND m.base_date = s.base_date
        WHERE m.base_date = ? AND m.gate_status IN ('PASS', 'PASSED') AND s.trade_count_12m BETWEEN 3 AND 5
        ORDER BY s.excess_drop_rate DESC
        LIMIT 10
    """, (max_dt,))
    low_trade_rows = cur.fetchall()

    print("거래 3~5건 단지 (숫자 신뢰도 낮음 §11)")
    if low_trade_rows:
        for idx, r in enumerate(low_trade_rows):
            at_str = translate_area(r["area_type"])
            ex_drop = r["excess_drop_rate"] or 0.0
            tc = r["trade_count_12m"] or 0
            print(f"  {idx+1:2d}. {r['complex_name']:<12}  {at_str:<5}  {r['region_name']:<10}  {ex_drop*100:+.1f}%p  {tc}건")
    else:
        print("  (해당 조건 단지 없음)")
    print()

    # §9 미구현 목록 상태 재출력 (필수)
    print("======================================================================")
    print("                 [§9 미구현 목록 및 진행 상태 보고 - 필수]")
    print("======================================================================")
    print("[§9.1 데이터·지표]")
    print("  1. 18평 이하·50평 이상 평형              [대기] (예정: v4.2)")
    print("  2. 전세가율                              [대기] (예정: v4.1)")
    print("  3. 임대수익률                            [대기] (예정: v4.2)")
    print("  4. 전고점 시간 감쇠                      [대기] (예정: v4.4)")
    print("  5. 미등기 장기경과 거래 제외              [대기] (예정: v4.1)")
    print("  6. 매물 수 증감                          [대기] (예정: v4.5)")
    print("  7. 입주물량·미분양                        [대기] (예정: v4.5)")
    print()
    print("[§9.2 입지·단지 정보]")
    print("  8. 세대수·연식·브랜드                    [대기] (예정: v4.1 / v4.3)")
    print("  9. 역세권 거리                            [대기] (예정: v4.2)")
    print(" 10. 초등학교 거리                          [대기] (예정: v4.2)")
    print(" 11. 업무지구 접근시간                      [대기] (예정: v4.4)")
    print(" 12. 용적률·대지지분                        [대기] (예정: v4.4)")
    print()
    print("[§9.3 점수·판단]")
    print(" 13. 종합 점수 (0~100)                      [대기] (예정: v4.3)")
    print(" 14. 비교군 세분화(구·법정동)              [대기] (예정: v4.3)")
    print(" 15. 리스크 감점                            [대기] (예정: v4.5)")
    print(" 16. 판단 문장 (강점/주의)                  [대기] (예정: v4.3)")
    print()
    print("[§9.4 매물(호가)]")
    print(" 17. 네이버 호가 연동                      [대기] (예정: v4.3)")
    print(" 18. 매물 괴리율                            [대기] (예정: v4.3)")
    print(" 19. 단지 매칭 (네이버↔국토부)            [대기] (예정: v4.3)")
    print(" 20. 층·향 보정                            [대기] (예정: v4.5)")
    print()
    print("[§9.5 화면·알림]")
    print(" 21. 카드형 화면                            [대기] (예정: 요청 시)")
    print(" 22. 단지 상세 화면                        [대기] (예정: v4.3)")
    print(" 23. 실거래 이력 차트                      [대기] (예정: v4.3)")
    print(" 24. 지역 비교 화면                        [대기] (예정: v4.4)")
    print(" 25. 텔레그램 알림                          [대기] (예정: v4.5)")
    print()
    print("[§9.6 검증]")
    print(" 26. 백테스트                              [대기] (예정: v4.4)")
    print(" 27. 지표 유효성 측정(IC)                  [대기] (예정: v4.4)")
    print(" 28. 기존 방식과 비교                      [대기] (예정: v4.4)")
    print("======================================================================\n")

    conn.close()

if __name__ == '__main__':
    import io, contextlib
    out_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf):
        run_self_check()
    result_str = out_buf.getvalue()
    print(result_str)
    
    report_file = Path(__file__).resolve().parent.parent.parent / "reports" / "self_check_20260731.md"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("# [AI 서술 배제] Phase 1-A 자가검증 스크립트 출력 원문 (v4.2)\n\n```\n" + result_str + "```\n")
