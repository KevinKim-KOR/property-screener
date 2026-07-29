# oci/crawler/molit_csv_loader.py
"""
국토교통부 실거래가 공개시스템(rt.molit.go.kr)에서 다운로드한
매매 및 전월세 CSV 파일을 안전하게 파싱하는 로더 (SCORING_V2_DESIGN.md §4.1.1).
"""
import csv
import os
from typing import List, Dict, Generator
from .molit_schema import CanonicalTrade, CanonicalRentTrade

def read_molit_csv_raw(filepath: str) -> Generator[Dict[str, str], None, None]:
    """
    CP949(EUC-KR) 및 UTF-8 인코딩을 순차 시도하며,
    헤더 앞의 안내문 행을 건너뛰고 ("NO", "시군구" 키워드 포함 행을 헤더로 감지)
    각 데이터 행을 dict 형태로 yield한다.
    """
    if not os.path.exists(filepath):
        return

    lines = []
    for enc in ("cp949", "euc-kr", "utf-8", "utf-8-sig"):
        try:
            with open(filepath, "r", encoding=enc, errors="replace") as f:
                lines = f.readlines()
            break
        except Exception:
            continue

    if not lines:
        return

    # 헤더 행 찾기
    header_idx = -1
    for i, line in enumerate(lines[:30]):
        if "NO" in line and "시군구" in line and "단지명" in line:
            header_idx = i
            break
    
    if header_idx == -1:
        return

    # csv.reader로 헤더와 데이터 파싱
    reader = csv.reader(lines[header_idx:])
    try:
        header_row = next(reader)
    except StopIteration:
        return

    headers = [col.strip() for col in header_row]

    for row in reader:
        if not row or len(row) < len(headers):
            continue
        row_dict = {}
        for h, val in zip(headers, row):
            row_dict[h] = val.strip()
        yield row_dict


def load_sale_trades_from_csv(filepath: str, source_snapshot_date: str) -> List[CanonicalTrade]:
    """
    실거래 매매 CSV 파일로부터 CanonicalTrade 목록을 파싱하여 반환한다.
    """
    trades = []
    for row_dict in read_molit_csv_raw(filepath):
        trade = CanonicalTrade.from_csv_row(row_dict, source_snapshot_date)
        if trade:
            trades.append(trade)
    return trades


def load_rent_trades_from_csv(filepath: str) -> List[CanonicalRentTrade]:
    """
    실거래 전월세 CSV 파일로부터 CanonicalRentTrade 목록을 파싱하여 반환한다.
    """
    rents = []
    for row_dict in read_molit_csv_raw(filepath):
        rent = CanonicalRentTrade.from_csv_row(row_dict)
        if rent:
            rents.append(rent)
    return rents
