# oci/crawler/molit_ingest.py
"""
국토부 실거래가 CSV 파일을 data/raw/molit/<date>/ 디렉토리에 아카이빙하고,
SQLite 데이터베이스(trades_sale, trades_rent)에 적재하는 인제스트 모듈 (SCORING_V2_DESIGN.md §4.1.1).
"""
import os
import shutil
from datetime import datetime
from typing import List, Optional
from common.database import get_db_connection
from .molit_csv_loader import load_sale_trades_from_csv, load_rent_trades_from_csv
from .molit_schema import CanonicalTrade, CanonicalRentTrade

def archive_raw_file(filepath: str, snapshot_date: str) -> str:
    """
    원본 CSV 파일을 data/raw/molit/<snapshot_date>/ 디렉토리에 무변경 보관한다.
    아카이빙된 파일 경로를 반환한다.
    """
    archive_dir = os.path.join("data", "raw", "molit", snapshot_date)
    os.makedirs(archive_dir, exist_ok=True)
    filename = os.path.basename(filepath)
    dest_path = os.path.join(archive_dir, filename)
    if os.path.abspath(filepath) != os.path.abspath(dest_path):
        shutil.copy2(filepath, dest_path)
    return dest_path


def ingest_sale_trades_to_db(trades: List[CanonicalTrade]) -> int:
    """
    CanonicalTrade 목록을 trades_sale 테이블에 적재한다.
    동일 trade_id는 최신 스냅샷 정보(last_seen_date, is_cancelled 등)로 업데이트한다.
    적재/업데이트된 건수를 반환한다.
    """
    if not trades:
        return 0
    now_str = datetime.now().isoformat()
    count = 0
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for t in trades:
            # 기존 레코드 존재 여부 확인
            cursor.execute("SELECT first_seen_date, is_cancelled FROM trades_sale WHERE trade_id = ?", (t.trade_id,))
            row = cursor.fetchone()
            first_seen = row["first_seen_date"] if row else t.source_snapshot_date
            # is_cancelled는 한번 1이면 유지 또는 갱신
            is_cancelled = max(t.is_cancelled, row["is_cancelled"] if row else 0)

            cursor.execute("""
                INSERT OR REPLACE INTO trades_sale (
                    trade_id, complex_code, sgg_cd, umd_nm, bonbun, bubun, road_name,
                    apt_name_raw, exclusive_area, area_type, deal_date, deal_amount,
                    building_dong, floor, buyer_type, seller_type, build_year,
                    is_cancelled, cancel_date, deal_type, agent_region, registry_date,
                    source, source_snapshot_date, first_seen_date, last_seen_date, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                t.trade_id, None, t.sgg_cd, t.umd_nm, t.bonbun, t.bubun, t.road_name,
                t.apt_name_raw, t.exclusive_area, t.area_type, t.deal_date, t.deal_amount,
                t.building_dong, t.floor, t.buyer_type, t.seller_type, t.build_year,
                is_cancelled, t.cancel_date, t.deal_type, t.agent_region, t.registry_date,
                t.source, t.source_snapshot_date, first_seen, t.source_snapshot_date, now_str
            ))
            count += 1
        conn.commit()
    return count


def ingest_rent_trades_to_db(rents: List[CanonicalRentTrade]) -> int:
    """
    CanonicalRentTrade 목록을 trades_rent 테이블에 적재한다.
    """
    if not rents:
        return 0
    now_str = datetime.now().isoformat()
    count = 0
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for r in rents:
            cursor.execute("""
                INSERT OR REPLACE INTO trades_rent (
                    rent_id, complex_code, sgg_cd, apt_name_raw, exclusive_area,
                    area_type, deal_date, deposit, monthly_rent, floor,
                    contract_type, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r.rent_id, None, r.sgg_cd, r.apt_name_raw, r.exclusive_area,
                r.area_type, r.deal_date, r.deposit, r.monthly_rent, r.floor,
                r.contract_type, now_str
            ))
            count += 1
        conn.commit()
    return count


def ingest_molit_csv_file(filepath: str, is_rent: bool = False, snapshot_date: Optional[str] = None) -> int:
    """
    CSV 파일 경로를 받아 원본 아카이빙 후 DB에 적재한다.
    """
    if not snapshot_date:
        snapshot_date = datetime.now().strftime("%Y-%m-%d")
    archive_raw_file(filepath, snapshot_date)
    if is_rent:
        rents = load_rent_trades_from_csv(filepath)
        return ingest_rent_trades_to_db(rents)
    else:
        trades = load_sale_trades_from_csv(filepath, snapshot_date)
        return ingest_sale_trades_to_db(trades)
