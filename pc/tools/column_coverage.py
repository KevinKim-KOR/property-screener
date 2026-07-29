# pc/tools/column_coverage.py
"""
SCORING_V3_DESIGN.md §5.5, P1-AC3:
연도별 × 컬럼별 결측률(%)을 산출하여 docs/molit_column_coverage.md에 기록하는 도구.
대상 컬럼: 거래유형, 해제사유발생일, 등기일자, 동, 매수자, 매도자
"""
import os
import csv
import re
from typing import Dict, List, Tuple
from collections import defaultdict

TARGET_COLUMNS = ["거래유형", "해제사유발생일", "등기일자", "동", "매수자", "매도자"]

def is_missing(val: str) -> bool:
    if val is None:
        return True
    v = val.strip()
    if not v or v == "-" or v == "null" or v == "NULL":
        return True
    return False

def analyze_csv_directory(csv_dir: str = "csv") -> Dict[str, Dict[str, Tuple[int, int]]]:
    """
    연도별로 (결측 수, 전체 수)를 dict 형식으로 산출한다.
    반환: { '2018': { '거래유형': (missing_count, total_count), ... }, ... }
    """
    results = defaultdict(lambda: {col: [0, 0] for col in TARGET_COLUMNS})

    if not os.path.exists(csv_dir):
        print(f"[Warn] '{csv_dir}' 폴더가 없습니다.")
        return {}

    files = sorted([f for f in os.listdir(csv_dir) if f.endswith(".csv")])
    for fname in files:
        # 연도 추출 (예: 2018_서울_매매.csv -> 2018)
        match = re.search(r"(\d{4})", fname)
        if not match:
            continue
        year = match.group(1)
        fpath = os.path.join(csv_dir, fname)

        # CP949 시도 후 UTF-8 폴백 (§5.3)
        lines = []
        for enc in ("cp949", "utf-8", "utf-8-sig"):
            try:
                with open(fpath, "r", encoding=enc, errors="replace") as f:
                    lines = f.readlines()
                break
            except Exception:
                continue

        if not lines:
            continue

        # 헤더 키워드 탐색 (§5.3 skip 앞 안내문)
        start_idx = 0
        for idx, line in enumerate(lines[:30]):
            if "시군구" in line and ("단지명" in line or "단지" in line):
                start_idx = idx
                break

        reader = csv.reader(lines[start_idx:])
        try:
            headers = next(reader)
        except StopIteration:
            continue

        # 헤더명 클린징
        clean_headers = [h.strip().replace('"', '').replace("'", "") for h in headers]
        col_indices = {}
        for target in TARGET_COLUMNS:
            for idx, ch in enumerate(clean_headers):
                if target in ch:
                    col_indices[target] = idx
                    break

        for row in reader:
            if not row or len(row) < 3:
                continue
            for target in TARGET_COLUMNS:
                results[year][target][1] += 1
                idx = col_indices.get(target)
                if idx is None or idx >= len(row) or is_missing(row[idx]):
                    results[year][target][0] += 1

    # tuple 변환
    final_res = {}
    for year in sorted(results.keys()):
        final_res[year] = {col: (results[year][col][0], results[year][col][1]) for col in TARGET_COLUMNS}
    return final_res

def generate_markdown_report(results: Dict[str, Dict[str, Tuple[int, int]]]) -> str:
    lines = [
        "# 실거래 CSV 연도별 컬럼 커버리지 리포트 (SCORING_V3_DESIGN.md §5.5)",
        "",
        "> **분석 대상**: `csv/` 내 2018~2026 서울 아파트 매매/전월세 전체 파일",
        "> **작성 시점**: 2026-07-29",
        "",
        "## 1. 연도별 x 컬럼별 결측률(%) 요약표",
        "",
        "| 연도 | 총 거래건수 | 거래유형 결측률 | 해제사유발생일 결측률 | 등기일자 결측률 | 동 결측률 | 매수자 결측률 | 매도자 결측률 |",
        "| :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    ]

    for year in sorted(results.keys()):
        stats = results[year]
        # total count는 아무 컬럼이나 total_count 참조
        total = stats[TARGET_COLUMNS[0]][1]
        row_str = f"| **{year}** | {total:,} | "
        cols_str = []
        for col in TARGET_COLUMNS:
            missing, tot = stats[col]
            pct = (missing / tot * 100.0) if tot > 0 else 100.0
            cols_str.append(f"{pct:.1f}%")
        row_str += " | ".join(cols_str) + " |"
        lines.append(row_str)

    lines.extend([
        "",
        "## 2. 시사점 및 고점 탐지 구간 적용 방안",
        "",
        "- **과거 연도 플래그 결측 구간**: 2018~2020 구간은 거래유형·해제사유발생일·등기일자 필드가 없거나 미제공되어 결측률이 매우 높게 나타납니다.",
        "- **G1/G2/G2b 게이트 적용 범위**: 품질 게이트는 최근 12개월 데이터를 대상으로 하므로 과거 구간 결측에 영향을 받지 않습니다.",
        "- **전고점 탐지(60M lookback) 방어**: 과거 구간에서 거래유형 및 해제 필터가 제한되므로, 단일 최고값 대신 **p90 롤링 윈도우(`peak_detector.py`)**를 1차 방어막으로 동작시킵니다.",
        ""
    ])

    return "\n".join(lines)

def main():
    print("[ColumnCoverage] 2018~2026 CSV 연도별 결측률 분석 시작...")
    results = analyze_csv_directory("csv")
    report_md = generate_markdown_report(results)

    os.makedirs("docs", exist_ok=True)
    report_path = os.path.join("docs", "molit_column_coverage.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"[ColumnCoverage] 분석 완료 -> '{report_path}' 생성 성공!")
    print(report_md)

if __name__ == "__main__":
    main()
