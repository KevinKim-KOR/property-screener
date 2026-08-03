# oci/crawler/molit_client.py
"""
국토부 공공데이터포털 실거래 API 클라이언트.
매매 상세(RTMSDataSvcAptTradeDev)와 전월세(RTMSDataSvcAptRent) 데이터를
XML 응답으로 받아 CanonicalTrade / CanonicalRentTrade 객체로 변환한다.
"""
import os
import time
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Tuple

import requests
from dotenv import load_dotenv

from .molit_schema import CanonicalTrade, CanonicalRentTrade

logger = logging.getLogger(__name__)

# .env 파일에서 키 로드 (프로젝트 루트 기준)
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(_project_root, ".env"))

TRADE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
RENT_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

# 대상 자치구 코드
TARGET_SGG_CODES = ["11650", "11680"]  # 서초구, 강남구

REQUEST_TIMEOUT = 10
MAX_ROWS_PER_PAGE = 1000


def _get_api_key() -> str:
    key = os.getenv("MOLIT_API_KEY")
    if not key:
        raise RuntimeError("MOLIT_API_KEY가 .env에 설정되어 있지 않습니다.")
    return key


def _get_recent_months(n: int = 3) -> List[str]:
    """최근 n개월의 YYYYMM 리스트를 반환한다."""
    today = datetime.now()
    months = []
    for i in range(n):
        dt = today.replace(day=1) - timedelta(days=i * 28)
        ym = dt.strftime("%Y%m")
        if ym not in months:
            months.append(ym)
    # 당월 포함
    current_ym = today.strftime("%Y%m")
    if current_ym not in months:
        months.insert(0, current_ym)
    months.sort(reverse=True)
    return months[:n]


def _fetch_all_pages(url: str, params: dict) -> List[dict]:
    """
    API를 페이지 단위로 호출하여 모든 item을 수집한다.
    각 item은 XML element를 dict로 변환한 것이다.
    """
    items = []
    page = 1
    while True:
        params["pageNo"] = str(page)
        params["numOfRows"] = str(MAX_ROWS_PER_PAGE)
        try:
            res = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            logger.error(f"[MolitClient] HTTP request failed: {e}")
            break

        if res.status_code != 200:
            logger.error(f"[MolitClient] HTTP {res.status_code}: {res.text[:200]}")
            break

        try:
            root = ET.fromstring(res.content)
        except ET.ParseError as e:
            logger.error(f"[MolitClient] XML parse error: {e}")
            break

        result_code = root.findtext(".//resultCode")
        if result_code != "000":
            result_msg = root.findtext(".//resultMsg")
            logger.error(f"[MolitClient] API error: resultCode={result_code}, resultMsg={result_msg}")
            break

        page_items = root.findall(".//item")
        for elem in page_items:
            item_dict = {}
            for child in elem:
                item_dict[child.tag] = child.text
            items.append(item_dict)

        total_count = int(root.findtext(".//totalCount") or "0")
        fetched_so_far = page * MAX_ROWS_PER_PAGE
        if fetched_so_far >= total_count:
            break
        page += 1
        time.sleep(0.3)  # API 부하 방지

    return items


def fetch_trade_items(sgg_cd: str, deal_ymd: str) -> List[dict]:
    """매매 상세 API에서 특정 시군구/계약년월의 모든 거래를 가져온다."""
    api_key = _get_api_key()
    params = {"serviceKey": api_key, "LAWD_CD": sgg_cd, "DEAL_YMD": deal_ymd}
    logger.info(f"[MolitClient] Fetching trades: sgg={sgg_cd}, ymd={deal_ymd}")
    return _fetch_all_pages(TRADE_URL, params)


def fetch_rent_items(sgg_cd: str, deal_ymd: str) -> List[dict]:
    """전월세 API에서 특정 시군구/계약년월의 모든 거래를 가져온다."""
    api_key = _get_api_key()
    params = {"serviceKey": api_key, "LAWD_CD": sgg_cd, "DEAL_YMD": deal_ymd}
    logger.info(f"[MolitClient] Fetching rents: sgg={sgg_cd}, ymd={deal_ymd}")
    return _fetch_all_pages(RENT_URL, params)


def fetch_and_convert_trades(sgg_cd: str, deal_ymd: str,
                              snapshot_date: str) -> List[CanonicalTrade]:
    """매매 API 호출 → CanonicalTrade 변환."""
    raw_items = fetch_trade_items(sgg_cd, deal_ymd)
    trades = []
    for item in raw_items:
        ct = CanonicalTrade.from_api_item(item, sgg_cd, deal_ymd, snapshot_date)
        if ct:
            trades.append(ct)
    logger.info(f"[MolitClient] Converted {len(trades)}/{len(raw_items)} trade items (sgg={sgg_cd}, ymd={deal_ymd})")
    return trades


def fetch_and_convert_rents(sgg_cd: str, deal_ymd: str) -> List[CanonicalRentTrade]:
    """전월세 API 호출 → CanonicalRentTrade 변환."""
    raw_items = fetch_rent_items(sgg_cd, deal_ymd)
    rents = []
    for item in raw_items:
        cr = CanonicalRentTrade.from_api_item(item, sgg_cd)
        if cr:
            rents.append(cr)
    logger.info(f"[MolitClient] Converted {len(rents)}/{len(raw_items)} rent items (sgg={sgg_cd}, ymd={deal_ymd})")
    return rents


def run_incremental_update(months: int = 3) -> dict:
    """
    서초구·강남구 × 최근 n개월 × 매매·전월세를 API에서 가져와 DB에 적재한다.
    중복(trade_id/rent_id)은 INSERT OR REPLACE로 처리된다.
    
    Returns:
        dict with keys: trade_new, trade_dup, rent_new, rent_dup, errors
    """
    from .molit_ingest import ingest_sale_trades_to_db, ingest_rent_trades_to_db
    from common.database import get_db_connection

    snapshot_date = datetime.now().strftime("%Y-%m-%d")
    deal_months = _get_recent_months(months)
    
    result = {
        "trade_new": 0, "trade_dup": 0,
        "rent_new": 0, "rent_dup": 0,
        "errors": []
    }

    for sgg_cd in TARGET_SGG_CODES:
        for ym in deal_months:
            # --- 매매 ---
            try:
                trades = fetch_and_convert_trades(sgg_cd, ym, snapshot_date)
                if trades:
                    # 중복 체크: DB에 이미 있는 trade_id 조회
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        trade_ids = [t.trade_id for t in trades]
                        placeholders = ",".join("?" * len(trade_ids))
                        cursor.execute(
                            f"SELECT trade_id FROM trades_sale WHERE trade_id IN ({placeholders})",
                            trade_ids
                        )
                        existing = {row["trade_id"] for row in cursor.fetchall()}
                    
                    new_trades = [t for t in trades if t.trade_id not in existing]
                    dup_trades = [t for t in trades if t.trade_id in existing]
                    
                    # 신규 + 기존 업데이트 모두 적재 (INSERT OR REPLACE)
                    ingested = ingest_sale_trades_to_db(trades)
                    result["trade_new"] += len(new_trades)
                    result["trade_dup"] += len(dup_trades)
                    logger.info(f"[MolitClient] Trade ingest: sgg={sgg_cd} ym={ym} new={len(new_trades)} dup={len(dup_trades)}")
            except Exception as e:
                msg = f"Trade fetch error: sgg={sgg_cd} ym={ym}: {e}"
                logger.error(f"[MolitClient] {msg}")
                result["errors"].append(msg)

            # --- 전월세 ---
            try:
                rents = fetch_and_convert_rents(sgg_cd, ym)
                if rents:
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        rent_ids = [r.rent_id for r in rents]
                        placeholders = ",".join("?" * len(rent_ids))
                        cursor.execute(
                            f"SELECT rent_id FROM trades_rent WHERE rent_id IN ({placeholders})",
                            rent_ids
                        )
                        existing = {row["rent_id"] for row in cursor.fetchall()}
                    
                    new_rents = [r for r in rents if r.rent_id not in existing]
                    dup_rents = [r for r in rents if r.rent_id in existing]
                    
                    ingested = ingest_rent_trades_to_db(rents)
                    result["rent_new"] += len(new_rents)
                    result["rent_dup"] += len(dup_rents)
                    logger.info(f"[MolitClient] Rent ingest: sgg={sgg_cd} ym={ym} new={len(new_rents)} dup={len(dup_rents)}")
            except Exception as e:
                msg = f"Rent fetch error: sgg={sgg_cd} ym={ym}: {e}"
                logger.error(f"[MolitClient] {msg}")
                result["errors"].append(msg)

            time.sleep(0.5)  # API 부하 방지

    return result
