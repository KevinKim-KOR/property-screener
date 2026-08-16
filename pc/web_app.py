import json
import sqlite3
import yaml
import sys
import os
import threading
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any

# 프로젝트 루트를 sys.path에 추가
root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir))

from common.config_loader import Config
from oci.crawler.naver_crawler import NaverCrawler
from pc.ml_engine.scorer import MLEngine
from pc.scoring.gate import check_l2_price_sanity_gates
from pc.scoring.ui_translator import (
    translate_area_type,
    translate_price_interpretation,
    generate_strength_sentence,
    generate_caution_sentence,
    translate_exclusion_reason,
)

app = FastAPI(title="PC Quant Screener Web GUI", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 주요 서울 법정동 프리셋 리스트
SEOUL_PRESETS = [
    {"name": "서초구 반포동", "code": "1165010700"},
    {"name": "강남구 개포동", "code": "1168010300"},
    {"name": "강남구 대치동", "code": "1168010600"},
    {"name": "송파구 잠실동", "code": "1171010100"},
    {"name": "강남구 압구정동", "code": "1168011000"},
    {"name": "서초구 서초동", "code": "1165010800"},
    {"name": "용산구 이촌동", "code": "1117012900"},
    {"name": "강남구 청담동", "code": "1168010400"},
    {"name": "송파구 가락동", "code": "1171010700"},
    {"name": "성동구 성수동1가", "code": "1120011400"},
    {"name": "영등포구 여의도동", "code": "1156011000"},
    {"name": "마포구 아현동", "code": "1144010100"}
]

# 크롤링 상태 관리 변수 (백그라운드 스레드 모니터링)
crawl_state = {
    "is_crawling": False,
    "progress_msg": "대기 중",
    "last_updated": None,
    # 마지막 작업이 실패했으면 사유 문자열, 성공했으면 None.
    # 프런트엔드는 이 값으로 성공/실패를 구분한다. progress_msg 만으로는
    # 오류 문구에도 "✓ 완료"가 붙어 실패가 성공처럼 보였다.
    "error": None
}


def _ingest_latest_molit_csvs():
    """
    data/raw/molit/ 의 가장 최신 날짜 폴더에서 CSV 를 DB 에 적재한다.

    적재는 trade_id 기준 INSERT OR REPLACE 이므로 이미 있는 건은 갱신되고
    신규분만 늘어난다(중복 적재로 건수가 부풀지 않는다).

    반환: {"snapshot_date":..., "files":n, "sale_rows":n, "rent_rows":n, "errors":[...]}
    """
    from oci.crawler.molit_ingest import ingest_molit_csv_file

    result = {"snapshot_date": None, "files": 0, "sale_rows": 0, "rent_rows": 0, "errors": []}
    base_dir = os.path.join(str(root_dir), "data", "raw", "molit")
    if not os.path.isdir(base_dir):
        return result

    # CSV 가 실제로 들어있는 폴더 중 최신 날짜
    dated = []
    for name in sorted(os.listdir(base_dir), reverse=True):
        d = os.path.join(base_dir, name)
        if os.path.isdir(d) and any(f.endswith(".csv") for f in os.listdir(d)):
            dated.append((name, d))
    if not dated:
        return result

    snapshot_date, csv_dir = dated[0]
    result["snapshot_date"] = snapshot_date

    for fname in sorted(os.listdir(csv_dir)):
        if not fname.endswith(".csv"):
            continue
        fpath = os.path.join(csv_dir, fname)
        is_rent = ("전세" in fname) or ("월세" in fname) or ("전월세" in fname)
        try:
            n = ingest_molit_csv_file(fpath, is_rent=is_rent, snapshot_date=snapshot_date)
            result["files"] += 1
            result["rent_rows" if is_rent else "sale_rows"] += n
            print(f"[CSV 적재] {fname}: {n:,}건")
        except Exception as e:
            # 파일 하나가 깨져도 나머지는 적재하되, 실패를 감추지 않고 모아서 보고한다.
            msg = f"{fname}: {type(e).__name__}: {e}"
            result["errors"].append(msg)
            print(f"[CSV 적재 실패] {msg}")

    return result


def _run_full_rescore(base_date: str = None):
    """
    실거래 → 통계 → 점수 전체 재계산 체인.

    크롤링 / 재채점 / 실거래 갱신 세 경로가 모두 이 함수를 호출한다.
    과거에는 경로마다 import 가 달라 refresh 만 존재하지 않는 모듈
    (pc.scoring.quant_scorer, pc.scoring.l2_match)을 참조해 항상 실패했고,
    그 예외를 삼켜 화면에는 완료로 표시됐다.

    스코어러는 complex_area_stats / region_stats 를 '읽기만' 한다. 통계 재빌드
    없이 스코어러만 돌리면 universe=0 이 되어 점수가 전혀 갱신되지 않으므로,
    통계 재빌드를 이 체인에 포함한다.

    실패를 삼키지 않는다. 예외는 호출자로 그대로 전파되어 화면에 실패로 표시된다.
    """
    from pc.features.build_complex_master import build_complex_master_from_molit
    from pc.keymap.matcher import run_complex_matching
    from pc.features.build_stats import build_complex_area_stats
    from pc.features.region_stats import compute_and_store_region_stats
    from pc.scoring.scorer_v2 import run_l1_scoring_v2
    from pc.scoring.scorer_v3 import run_scoring
    from pc.l2.deal_gap import update_all_properties_l2

    if not base_date:
        base_date = datetime.now().strftime("%Y-%m-%d")

    # 1. 단지 마스터 구축: 실거래에서 고유 단지를 집계해 complexes 를 만들고
    #    trades_sale/trades_rent 의 complex_code 를 채운다.
    #    이 단계가 없으면 매칭이 전부 UNMATCHED 가 되어 이후가 전부 0이 된다.
    master_cnt = build_complex_master_from_molit()
    print(f"[Rescore] 단지 마스터 {master_cnt:,}건")

    # 2. 단지 매칭: 마스터로 못 붙은 잔여 거래를 4단계 매칭으로 붙인다.
    match_res = run_complex_matching()
    print(f"[Rescore] 매칭 시도 {match_res.get('total', 0):,}건 / 성공 {match_res.get('matched', 0):,}건")

    # 3~5. 통계 재빌드.
    #      build_complex_area_stats 는 region_stats 를(excess_drop_rate 용),
    #      compute_and_store_region_stats 는 complex_area_stats 를 읽는 상호 참조
    #      관계이므로 build → region → build 2패스로 채운다.
    cas_cnt = build_complex_area_stats(base_date)
    reg_cnt = compute_and_store_region_stats(base_date)
    cas_cnt = build_complex_area_stats(base_date)
    print(f"[Rescore] 단지x평형 통계 {cas_cnt:,}건 / 지역 통계 {reg_cnt:,}건")

    # 6~8. 점수 산출
    run_l1_scoring_v2(base_date)
    run_scoring(base_date)
    gap_cnt = update_all_properties_l2(base_date)
    print(f"[Rescore] 매물 괴리율 산출 {gap_cnt:,}건")

def get_data_reference_date():
    """data/raw/molit/ 폴더 내 매매 CSV 또는 API 갱신 마커가 있는 가장 최신 날짜 폴더명을 반환합니다."""
    base_dir = os.path.join(str(root_dir), "data", "raw", "molit")
    if not os.path.exists(base_dir):
        return None
    folders = []
    for name in os.listdir(base_dir):
        p = os.path.join(base_dir, name)
        if os.path.isdir(p):
            children = os.listdir(p)
            has_csv = any(f.endswith(".csv") and "매매" in f for f in children)
            has_marker = "_api_refresh.txt" in children
            if has_csv or has_marker:
                folders.append(name)
    if not folders:
        return None
    folders.sort(reverse=True)
    return folders[0]

class RegionItem(BaseModel):
    name: str
    code: str

class RegionsPayload(BaseModel):
    regions: List[RegionItem]

def format_subway_str(comp: dict) -> str:
    if not comp:
        return ""
    s_dist = comp.get("subway_dist_m")
    s_name = comp.get("subway_name")
    if s_dist is not None and float(s_dist) <= 1500.0 and s_name:
        return f"{s_name} {int(round(float(s_dist)))}m"
    return ""

def format_academies_str(comp: dict) -> str:
    if not comp:
        return ""
    cnt = comp.get("academies_count")
    if cnt is not None:
        return f"학원 {int(cnt)}곳"
    return ""

def format_schools_str(comp: dict) -> str:
    if not comp:
        return ""
    parts = []
    e_dist = comp.get("elem_school_dist_m")
    if e_dist is not None and float(e_dist) <= 2000.0:
        parts.append(f"초 {int(round(float(e_dist)))}m")
    m_dist = comp.get("mid_school_dist_m")
    if m_dist is not None and float(m_dist) <= 2000.0:
        parts.append(f"중 {int(round(float(m_dist)))}m")
    return " / ".join(parts)

def _compute_days_ago(ref_date_str: str) -> int:
    """
    기준일 문자열(YYYY-MM-DD)로부터 경과 일수를 계산한다.
    해석할 수 없으면 ValueError 를 던진다 — 조용히 넘기면 배너에서
    기준일이 사라진 이유를 알 수 없다.
    """
    try:
        ref_dt = datetime.strptime(ref_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError) as e:
        raise ValueError(f"기준일 형식이 올바르지 않습니다: {ref_date_str!r} ({e})") from e
    return (datetime.now().date() - ref_dt).days


@app.get("/api/properties")
def get_properties():
    """screener.db 매물 정보와 v2/v1 스코어링 정보를 반환합니다."""
    db_path = Path(Config.get_db_path())
    properties = []
    excluded_properties = []
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # market_scores 로드 (최신 base_date 기준)
            cursor.execute("SELECT * FROM market_scores WHERE base_date = (SELECT MAX(base_date) FROM market_scores)")
            ms_map = { (str(r["complex_code"]), str(r["area_type"])): dict(r) for r in cursor.fetchall() }

            # complex_area_stats 로드
            cursor.execute("SELECT * FROM complex_area_stats WHERE base_date = (SELECT MAX(base_date) FROM complex_area_stats)")
            cas_map = { (str(r["complex_code"]), str(r["area_type"])): dict(r) for r in cursor.fetchall() }

            cursor.execute("SELECT * FROM complexes")
            comp_map = {str(r["complex_code"]): dict(r) for r in cursor.fetchall()}

            cursor.execute("SELECT * FROM properties")
            for row in cursor.fetchall():
                pid = str(row["property_id"])
                cc = str(row["complex_code"] or "")
                at = str(row["area_type"] or "A84")

                ms = ms_map.get((cc, at), {})
                cas = cas_map.get((cc, at), {})
                comp = comp_map.get(cc, {})

                by_val = comp.get("build_year")
                if by_val and int(by_val) > 1900:
                    by_int = int(by_val)
                    age_int = max(0, 2026 - by_int)
                    by_str = f"{by_int}년 · {age_int}년"
                else:
                    by_str = ""
                brand_str = str(comp.get("brand") or "")
                subway_str = format_subway_str(comp)
                academies_str = format_academies_str(comp)
                schools_str = format_schools_str(comp)

                asking_price = float(row["asking_price"] or 0)
                med_3m = float(cas.get("median_price_3m", 0))
                peak_price = float(cas.get("peak_price_adj", 0))
                excess_drop = float(cas.get("excess_drop_rate", 0.0)) * 100.0
                deal_gap = row["deal_gap_pct"]
                if deal_gap is not None:
                    deal_gap = float(deal_gap)

                market_score = ms.get("market_score")
                if market_score is None:
                    # 폴백: v1점수 또는 0.0
                    market_score = float(row["score_v1"] or 0.0)
                else:
                    market_score = float(market_score)

                score_v1 = float(row["score_v1"] or 0.0)

                sgg = str(comp.get("sgg_cd") or "")
                gu_name = "서초구" if sgg == "11650" else ("강남구" if sgg == "11680" else "기타구")
                dong_name = str(comp.get("region_name") or "기타동")
                region_name = dong_name

                # V2 / V6 가격 정합성 게이트 검증 (SCORING_V3.1_DESIGN.md §11.5)
                # 위반 시 UI 목록(L2)에 렌더링하지 않고 진단 로그 출력
                is_price_valid, _ = check_l2_price_sanity_gates(
                    dict(row), med_3m, peak_price, cas
                )
                if not is_price_valid:
                    continue

                item_dict = dict(row)
                item_dict.update(cas)
                item_dict.update(ms)

                prop_data = {
                    "property_id": pid,
                    "complex_code": cc,
                    "complex_name": str(row["complex_name"] or "Unknown"),
                    "region_name": region_name,
                    "gu_name": gu_name,
                    "dong_name": dong_name,
                    "building_dong": str(row["building_dong"] or "-"),
                    "floor": str(row["floor"] or "-"),
                    "floor_grade": str(row["floor_grade"] or "MID"),
                    "area_type": at,
                    "area_type_str": translate_area_type(at),
                    "area_pyeong": float(row["area_pyeong"] or 0),
                    "build_year_str": by_str,
                    "age_years": age_int if by_val and int(by_val) > 1900 else None,
                    "brand": brand_str,
                    "subway_str": subway_str,
                    "subway_dist_m": float(comp.get("subway_dist_m")) if comp.get("subway_dist_m") is not None and float(comp.get("subway_dist_m")) <= 1500.0 and comp.get("subway_name") else None,
                    "academies_str": academies_str,
                    "academies_count": int(comp.get("academies_count")) if comp.get("academies_count") is not None else None,
                    "schools_str": schools_str,
                    "asking_price": asking_price,
                    "median_price_3m": med_3m,
                    "price_interpretation": translate_price_interpretation(asking_price, med_3m),
                    "deal_gap_pct": deal_gap,
                    "peak_price": peak_price,
                    "peak_date": str(cas.get("peak_date") or ""),
                    "drop_rate": round(float(cas.get("drop_rate") or 0.0) * 100.0, 1),
                    "excess_drop_rate": round(excess_drop, 2),
                    "jeonse_ratio": round(float(cas["jeonse_ratio"]) * 100.0, 1) if cas.get("jeonse_ratio") is not None else None,
                    "m3": round(float(cas["m3"]), 4) if cas.get("m3") is not None else None,
                    "m6": round(float(cas["m6"]), 4) if cas.get("m6") is not None else None,
                    "m12": round(float(cas["m12"]), 4) if cas.get("m12") is not None else None,
                    "trade_count_12m": int(cas.get("trade_count_12m") or cas.get("sample_count_12m") or 0),
                    "volume_ratio": round(float(cas.get("volume_ratio") or 0.0), 2),
                    "change_1m": round(float(row["change_1m"] or 0.0), 2),
                    "change_3m": round(float(row["change_3m"] or 0.0), 2),
                    "change_6m": round(float(row["change_6m"] or 0.0), 2),
                    "market_score": round(market_score, 1),
                    "score_v1": round(score_v1, 1),
                    "strength_sentence": generate_strength_sentence(item_dict),
                    "caution_sentence": generate_caution_sentence(item_dict),
                    "gate_status": ms.get("gate_status", "PASSED"),
                    "gate_reason": ms.get("gate_reason"),
                    "gate_reason_kr": translate_exclusion_reason(ms.get("gate_reason") or ""),
                    "has_evidence": bool(ms.get("evidence_json")),
                    "naver_link": f"https://new.land.naver.com/complexes/{cc}" if cc and cc.isdigit() else ""
                }

                if ms.get("gate_status") == "EXCLUDED":
                    excluded_properties.append(prop_data)
                else:
                    properties.append(prop_data)

            if not properties and not excluded_properties and ms_map:
                cursor.execute("SELECT * FROM complexes")
                comp_map = {str(r["complex_code"]): dict(r) for r in cursor.fetchall()}

                for (cc, at), ms in ms_map.items():
                    comp = comp_map.get(cc, {})
                    cas = cas_map.get((cc, at), {})
                    market_score = float(ms.get("market_score") or 0.0)
                    min_a = float(comp.get("area_min_m2") or 0.0)
                    max_a = float(comp.get("area_max_m2") or 0.0)
                    avg_pyeong = round((min_a + max_a) / 2.0 / 3.30578, 1) if max_a > 0 else 32.0

                    by_val = comp.get("build_year")
                    if by_val and int(by_val) > 1900:
                        by_int = int(by_val)
                        age_int = max(0, 2026 - by_int)
                        by_str = f"{by_int}년 · {age_int}년"
                    else:
                        by_str = ""
                    brand_str = str(comp.get("brand") or "")
                    subway_str = format_subway_str(comp)
                    academies_str = format_academies_str(comp)
                    schools_str = format_schools_str(comp)

                    item_dict = {
                        "val_score": float(ms.get("block_value") or 50.0),
                        "flw_score": float(ms.get("block_flow") or 50.0),
                        "loc_score": float(ms.get("block_location") or 50.0),
                        "qty_score": float(ms.get("block_quality") or 50.0),
                        "drop_rate": float(cas.get("drop_rate") or 0.0) * 100.0,
                        "change_1m": float(cas.get("change_1m") or 0.0) * 100.0,
                        "change_3m": float(cas.get("change_3m") or 0.0) * 100.0,
                        "change_6m": float(cas.get("change_6m") or 0.0) * 100.0,
                        "area_type": at,
                        "floor_grade": "L1",
                        "market_score": market_score,
                        "deal_gap_pct": 0.0,
                        "excess_drop_rate": float(cas.get("excess_drop_rate") or 0.0),
                        "gate_status": ms.get("gate_status", "PASSED"),
                        "gate_reason": ms.get("gate_reason"),
                    }

                    sgg = str(comp.get("sgg_cd") or "")
                    gu_name = "서초구" if sgg == "11650" else ("강남구" if sgg == "11680" else "기타구")
                    dong_name = str(comp.get("region_name") or "기타동")

                    prop_data = {
                        "property_id": f"L1_{cc}_{at}",
                        "complex_code": cc,
                        "complex_name": str(comp.get("complex_name") or "국토부 단지"),
                        "region_name": dong_name,
                        "gu_name": gu_name,
                        "dong_name": dong_name,
                        "building_dong": "단지 전체",
                        "floor": "평균 층",
                        "area_pyeong": avg_pyeong,
                        "area_type": at,
                        "area_type_kr": translate_area_type(at),
                        "area_type_str": translate_area_type(at),
                        "build_year_str": by_str,
                        "age_years": age_int if by_val and int(by_val) > 1900 else None,
                        "brand": brand_str,
                        "subway_str": subway_str,
                        "subway_dist_m": float(comp.get("subway_dist_m")) if comp.get("subway_dist_m") is not None and float(comp.get("subway_dist_m")) <= 1500.0 and comp.get("subway_name") else None,
                        "academies_str": academies_str,
                        "academies_count": int(comp.get("academies_count")) if comp.get("academies_count") is not None else None,
                        "schools_str": schools_str,
                        "sample_count_24m": int(cas.get("trade_count_24m") or cas.get("trade_count_12m") or 0),
                        "sample_count_12m": int(cas.get("trade_count_12m") or 0),
                        "asking_price": 0,
                        "asking_price_kr": f"3M 실거래 중위 {round(float(cas.get('median_price_3m') or 0.0)/10000.0, 1)}억",
                        "price_interpretation": f"3M 실거래 중위 {round(float(cas.get('median_price_3m') or 0.0)/10000.0, 1)}억",
                        "med_3m": round(float(cas.get("median_price_3m") or 0.0), 0),
                        "median_price_3m": round(float(cas.get("median_price_3m") or 0.0), 0),
                        "peak_price": round(float(cas.get("peak_price_adj") or 0.0), 0),
                        "peak_date": str(cas.get("peak_date") or ""),
                        "drop_rate": round(float(cas.get("drop_rate") or 0.0) * 100.0, 1),
                        "excess_drop": round(float(cas.get("excess_drop_rate") or 0.0) * 100.0, 1),
                        "excess_drop_rate": round(float(cas.get("excess_drop_rate") or 0.0) * 100.0, 1),
                        "jeonse_ratio": round(float(cas["jeonse_ratio"]) * 100.0, 1) if cas.get("jeonse_ratio") is not None else None,
                        "m3": round(float(cas["m3"]), 4) if cas.get("m3") is not None else None,
                        "m6": round(float(cas["m6"]), 4) if cas.get("m6") is not None else None,
                        "m12": round(float(cas["m12"]), 4) if cas.get("m12") is not None else None,
                        "trade_count_12m": int(cas.get("trade_count_12m") or cas.get("sample_count_12m") or 0),
                        "volume_ratio": round(float(cas.get("volume_ratio") or 0.0), 2),
                        "deal_gap_pct": 0.0,
                        "change_1m": round(float(cas.get("change_1m") or 0.0) * 100.0, 1),
                        "change_3m": round(float(cas.get("change_3m") or 0.0) * 100.0, 1),
                        "change_6m": round(float(cas.get("change_6m") or 0.0) * 100.0, 1),
                        "market_score": round(market_score, 1),
                        "score_v1": round(market_score, 1),
                        "strength_sentence": generate_strength_sentence(item_dict),
                        "caution_sentence": generate_caution_sentence(item_dict),
                        "gate_status": ms.get("gate_status", "PASSED"),
                        "gate_reason": ms.get("gate_reason"),
                        "gate_reason_kr": translate_exclusion_reason(ms.get("gate_reason") or ""),
                        "has_evidence": bool(ms.get("evidence_json")),
                        "is_new_high": bool(float(cas.get("median_price_3m") or 0.0) >= float(cas.get("peak_price_adj") or 0.0) and float(cas.get("peak_price_adj") or 0.0) > 0),
                        "naver_link": ""
                    }
                    if ms.get("gate_status") == "EXCLUDED":
                        excluded_properties.append(prop_data)
                    else:
                        properties.append(prop_data)

            conn.close()
        except Exception as e:
            # 빈 목록을 200 으로 돌려주면 "매물 0건"으로 보여 실패가 감춰진다.
            print(f"[WebGUI] DB read error: {e}")
            raise HTTPException(status_code=500, detail=f"매물 데이터를 읽지 못했습니다: {e}")

    properties.sort(key=lambda x: x.get("excess_drop_rate", 0.0) or 0.0, reverse=True)
    ref_date_str = get_data_reference_date()
    days_ago = None
    data_ref_error = None
    if ref_date_str:
        try:
            days_ago = _compute_days_ago(ref_date_str)
        except ValueError as e:
            # 조용히 넘기면 기준일이 왜 안 나오는지 알 수 없다.
            # 전체 목록을 500 으로 죽이지는 않되(배너 하나 때문에 대시보드가
            # 통째로 비면 더 나쁘다), 사유를 로그와 응답 모두에 남긴다.
            print("!" * 70)
            print(f"[WebGUI] 실거래 자료 기준일을 해석하지 못했습니다: {e}")
            print("  data/raw/molit/ 아래 폴더명이 YYYY-MM-DD 형식인지 확인하세요.")
            print("!" * 70)
            data_ref_error = str(e)
    return {
        "count": len(properties),
        "excluded_count": len(excluded_properties),
        "last_updated": crawl_state["last_updated"] or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_ref_date": ref_date_str,
        "data_ref_days_ago": days_ago,
        "data_ref_error": data_ref_error,
        "properties": properties,
        "excluded_properties": excluded_properties
    }


@app.get("/api/region_stats")
def get_region_stats_api():
    """지역 및 면적 유형별 중위 하락률, 평단가 등 기초 통계를 반환합니다."""
    db_path = Path(Config.get_db_path())
    res = []
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM region_stats WHERE base_date = (SELECT MAX(base_date) FROM region_stats) ORDER BY sgg_cd, area_type")
            for r in cursor.fetchall():
                res.append(dict(r))
            conn.close()
        except Exception as e:
            print(f"[WebGUI] region_stats read error: {e}")
            raise HTTPException(status_code=500, detail=f"지역 통계를 읽지 못했습니다: {e}")
    return res

@app.get("/api/evidence")
def get_evidence_api(complex_code: str, area_type: str):
    """특정 단지 x 평형에 대한 4-Block 스코어링 근거(Evidence JSON)를 반환합니다."""
    db_path = Path(Config.get_db_path())
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT evidence_json FROM market_scores WHERE complex_code = ? AND area_type = ? ORDER BY base_date DESC LIMIT 1", (complex_code, area_type))
            row = cursor.fetchone()
            conn.close()
            if row and row["evidence_json"]:
                return json.loads(row["evidence_json"])
        except Exception as e:
            print(f"[WebGUI] evidence read error: {e}")
            raise HTTPException(status_code=500, detail=f"스코어링 근거를 읽지 못했습니다: {e}")
    return {"error": "Evidence not found"}

@app.get("/api/regions")
def get_regions():
    """config.yaml 내 활성화된 target_regions와 기본 서울 프리셋 목록을 반환합니다."""
    config_path = root_dir / "config.yaml"
    active_regions = []
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
                active_regions = cfg.get("target_regions", [])
        except Exception as e:
            # 설정을 못 읽었는데 빈 목록을 주면 "선택된 지역 없음"으로 오인된다.
            print(f"[WebGUI] Config read error: {e}")
            raise HTTPException(status_code=500, detail=f"config.yaml 을 읽지 못했습니다: {e}")

    return {
        "active_regions": active_regions,
        "presets": SEOUL_PRESETS
    }

@app.post("/api/regions")
def save_regions(payload: RegionsPayload):
    """사용자가 웹 UI에서 선택한 지역 목록을 config.yaml에 반영합니다."""
    config_path = root_dir / "config.yaml"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="config.yaml file not found")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        
        cfg["target_regions"] = [{"name": r.name, "code": r.code} for r in payload.regions]
        
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            
        return {"success": True, "message": f"{len(payload.regions)}개 지역 설정 완료", "active_regions": cfg["target_regions"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def _run_crawler_task():
    global crawl_state
    crawl_state["is_crawling"] = True
    crawl_state["error"] = None
    crawl_state["progress_msg"] = "네이버 부동산 단지 및 매물 수집 중..."
    try:
        crawler = NaverCrawler()
        crawler.run()
        
        crawl_state["progress_msg"] = "수집 완료 -> 퀀트 점수 분석(MLEngine, V2/V3) 실행 중..."
        MLEngine.run()
        _run_full_rescore()

        crawl_state["progress_msg"] = "완료"
        crawl_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        crawl_state["error"] = str(e)
        crawl_state["progress_msg"] = f"오류 발생: {e}"
        print(f"[Crawl Error] {e}")
    finally:
        crawl_state["is_crawling"] = False

@app.post("/api/crawl")
def start_crawl(background_tasks: BackgroundTasks):
    """선택된 타겟 지역에 대해 실시간 매물 수집 및 스코어링을 시작합니다."""
    if crawl_state["is_crawling"]:
        return {"success": False, "message": "이미 크롤링이 진행 중입니다."}
    
    background_tasks.add_task(_run_crawler_task)
    return {"success": True, "message": "크롤링 및 분석 작업을 시작했습니다."}

def _run_rescore_task():
    global crawl_state
    crawl_state["is_crawling"] = True
    crawl_state["error"] = None
    crawl_state["progress_msg"] = "로컬 DB 매물의 퀀트 점수(v1/v2/v3) 및 입지 가점 재계산 중 (API 미호출)..."
    try:
        MLEngine.run()
        _run_full_rescore()

        crawl_state["progress_msg"] = "퀀트 점수 재계산 완료"
        crawl_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        crawl_state["error"] = str(e)
        crawl_state["progress_msg"] = f"재계산 중 오류: {e}"
        print(f"[Rescore Error] {e}")
    finally:
        crawl_state["is_crawling"] = False

@app.post("/api/rescore")
def start_rescore(background_tasks: BackgroundTasks):
    """네이버 크롤링 없이 로컬 DB 매물들의 퀀트 점수만 즉시 재계산합니다."""
    if crawl_state["is_crawling"]:
        return {"success": False, "message": "이미 분석/크롤링 작업이 진행 중입니다."}
    
    background_tasks.add_task(_run_rescore_task)
    return {"success": True, "message": "퀀트 점수 재계산 작업을 시작했습니다."}

@app.get("/api/status")
def get_status():
    return crawl_state


def _run_refresh_task():
    """
    [최신 자료 가져오기] 버튼의 백그라운드 태스크.

      1) data/raw/molit/ 최신 폴더의 CSV 적재 (INSERT OR REPLACE 이므로 신규분만 증가)
      2) 국토부 API 증분 (MOLIT_API_KEY 가 있을 때만, 없으면 건너뛰고 안내)
      3) 단지 마스터 → 매칭 → 통계(2패스) → 점수 → 괴리율  (_run_full_rescore)
    """
    try:
        crawl_state["is_crawling"] = True
        crawl_state["error"] = None
        # ── 1단계: 로컬 CSV 적재 ────────────────────────────────
        crawl_state["progress_msg"] = "실거래 CSV 적재 중..."
        csv_res = _ingest_latest_molit_csvs()
        csv_note = ""
        if csv_res["snapshot_date"]:
            csv_note = (f"CSV {csv_res['files']}개 (매매 {csv_res['sale_rows']:,}건 · "
                        f"전월세 {csv_res['rent_rows']:,}건, 기준 {csv_res['snapshot_date']})")
            if csv_res["errors"]:
                csv_note += f" · 실패 {len(csv_res['errors'])}개"
        else:
            csv_note = "CSV 없음(data/raw/molit/)"
        print(f"[Refresh] {csv_note}")

        # ── 2단계: 국토부 API 증분 (키가 있을 때만) ─────────────
        trade_new = rent_new = trade_dup = rent_dup = 0
        api_note = ""
        if os.getenv("MOLIT_API_KEY"):
            crawl_state["progress_msg"] = f"{csv_note} — API 증분 갱신 중..."
            from oci.crawler.molit_client import run_incremental_update
            result = run_incremental_update(months=3)
            trade_new = result.get("trade_new", 0)
            rent_new = result.get("rent_new", 0)
            trade_dup = result.get("trade_dup", 0)
            rent_dup = result.get("rent_dup", 0)
            api_note = f"API 신규 {trade_new + rent_new}건 · 갱신 {trade_dup + rent_dup}건"
        else:
            # 키가 없으면 조용히 건너뛰지 않고 사용자에게 알린다.
            api_note = "API 증분 건너뜀(MOLIT_API_KEY 미설정)"
        print(f"[Refresh] {api_note}")

        # ── 3단계: 단지 마스터 → 매칭 → 통계(2패스) → 점수 → 괴리율 ──
        crawl_state["progress_msg"] = f"{csv_note} · {api_note} — 재계산 중..."
        _run_full_rescore()

        # 기준일 마커는 API 로 실제 신규 자료를 받아왔을 때만 남긴다.
        # 예전에는 무조건 오늘 날짜 폴더를 만들어, API 를 돌리지 않았거나
        # 신규분이 0건이어도 배너가 "오늘 기준"이라고 표시했다.
        # 자료 기준일은 실제 자료의 날짜여야 한다(CSV 만 적재했다면 CSV 스냅샷 날짜).
        if (trade_new + rent_new) > 0:
            today_str = datetime.now().strftime("%Y-%m-%d")
            refresh_dir = os.path.join(str(root_dir), "data", "raw", "molit", today_str)
            os.makedirs(refresh_dir, exist_ok=True)
            marker_path = os.path.join(refresh_dir, "_api_refresh.txt")
            with open(marker_path, "w", encoding="utf-8") as f:
                f.write(f"API incremental update at {datetime.now().isoformat()}\n")
                f.write(f"trade_new={trade_new}, rent_new={rent_new}, "
                        f"trade_dup={trade_dup}, rent_dup={rent_dup}\n")
        else:
            print("[Refresh] API 신규분이 없어 기준일 마커를 만들지 않습니다 "
                  "(배너는 실제 자료 날짜를 그대로 표시합니다).")

        crawl_state["progress_msg"] = f"완료 · {csv_note} · {api_note}"
        crawl_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        crawl_state["last_refresh_result"] = {
            "trade_new": trade_new,
            "rent_new": rent_new,
            "trade_dup": trade_dup,
            "rent_dup": rent_dup,
            "csv": csv_res,
            "api_skipped": not bool(os.getenv("MOLIT_API_KEY")),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        crawl_state["error"] = str(e)
        crawl_state["progress_msg"] = f"갱신 중 오류: {e}"
        print(f"[Refresh Error] {e}")
    finally:
        crawl_state["is_crawling"] = False


@app.post("/api/refresh")
def start_refresh(background_tasks: BackgroundTasks):
    """국토부 API에서 최근 3개월 데이터를 가져와 DB에 적재하고 재계산합니다."""
    if crawl_state["is_crawling"]:
        return {"success": False, "message": "이미 분석/갱신 작업이 진행 중입니다."}
    
    background_tasks.add_task(_run_refresh_task)
    return {"success": True, "message": "실거래 자료 갱신을 시작했습니다."}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(content=b"", media_type="image/x-icon", status_code=204)

@app.get("/", response_class=HTMLResponse)
def index_page():
    template_path = root_dir / "pc" / "templates" / "index.html"
    if template_path.exists():
        with open(template_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<html><body><h1>pc/templates/index.html을 찾을 수 없습니다.</h1></body></html>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("pc.web_app:app", host="127.0.0.1", port=8585, reload=True)
