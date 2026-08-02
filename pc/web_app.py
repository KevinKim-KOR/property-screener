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
    "last_updated": None
}

class RegionItem(BaseModel):
    name: str
    code: str

class RegionsPayload(BaseModel):
    regions: List[RegionItem]

@app.get("/api/properties")
def get_properties():
    """screener.db 매물 정보와 v2/v1 스코어링 정보를 반환합니다."""
    db_path = root_dir / "screener.db"
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

            cursor.execute("SELECT * FROM properties")
            for row in cursor.fetchall():
                pid = str(row["property_id"])
                cc = str(row["complex_code"] or "")
                at = str(row["area_type"] or "A84")

                ms = ms_map.get((cc, at), {})
                cas = cas_map.get((cc, at), {})

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

                region_name = str(row["region_name"] or "")
                if not region_name or region_name == "Unknown":
                    region_name = "서초구 반포동" if "반포" in str(row["complex_name"]) else "서울 주요지역"

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
                    "building_dong": str(row["building_dong"] or "-"),
                    "floor": str(row["floor"] or "-"),
                    "floor_grade": str(row["floor_grade"] or "MID"),
                    "area_type": at,
                    "area_type_str": translate_area_type(at),
                    "area_pyeong": float(row["area_pyeong"] or 0),
                    "asking_price": asking_price,
                    "median_price_3m": med_3m,
                    "price_interpretation": translate_price_interpretation(asking_price, med_3m),
                    "deal_gap_pct": deal_gap,
                    "peak_price": peak_price,
                    "peak_date": str(cas.get("peak_date") or ""),
                    "drop_rate": round(float(cas.get("drop_rate") or 0.0) * 100.0, 1),
                    "excess_drop_rate": round(excess_drop, 2),
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

                    prop_data = {
                        "property_id": f"L1_{cc}_{at}",
                        "complex_code": cc,
                        "complex_name": str(comp.get("complex_name") or "국토부 단지"),
                        "region_name": str(comp.get("region_name") or "서울"),
                        "building_dong": "단지 전체",
                        "floor": "평균 층",
                        "area_pyeong": avg_pyeong,
                        "area_type": at,
                        "area_type_kr": translate_area_type(at),
                        "area_type_str": translate_area_type(at),
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
            print(f"[WebGUI] DB read error: {e}")

    properties.sort(key=lambda x: x.get("excess_drop_rate", 0.0) or 0.0, reverse=True)
    return {
        "count": len(properties),
        "excluded_count": len(excluded_properties),
        "last_updated": crawl_state["last_updated"] or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "properties": properties,
        "excluded_properties": excluded_properties
    }


@app.get("/api/region_stats")
def get_region_stats_api():
    """지역 및 면적 유형별 중위 하락률, 평단가 등 기초 통계를 반환합니다."""
    db_path = root_dir / "screener.db"
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
    return res

@app.get("/api/evidence")
def get_evidence_api(complex_code: str, area_type: str):
    """특정 단지 x 평형에 대한 4-Block 스코어링 근거(Evidence JSON)를 반환합니다."""
    db_path = root_dir / "screener.db"
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
            print(f"[WebGUI] Config read error: {e}")

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
    crawl_state["progress_msg"] = "네이버 부동산 단지 및 매물 수집 중..."
    try:
        crawler = NaverCrawler()
        crawler.run()
        
        crawl_state["progress_msg"] = "수집 완료 -> 퀀트 점수 분석(MLEngine, V2/V3) 실행 중..."
        MLEngine.run()
        try:
            from pc.scoring.scorer_v2 import run_l1_scoring_v2
            from pc.scoring.scorer_v3 import run_scoring
            from pc.l2.deal_gap import update_all_properties_l2
            run_l1_scoring_v2()
            run_scoring()
            update_all_properties_l2()
        except Exception as e_sc:
            print(f"[Crawl Scorer Error] {e_sc}")

        # HTML 뷰어 보고서도 갱신
        try:
            from pc.viewer.generate_report import generate_report
            generate_report()
        except:
            pass

        crawl_state["progress_msg"] = "완료"
        crawl_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        crawl_state["progress_msg"] = f"오류 발생: {e}"
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
    crawl_state["progress_msg"] = "로컬 DB 매물의 퀀트 점수(v1/v2/v3) 및 입지 가점 재계산 중 (API 미호출)..."
    try:
        MLEngine.run()
        try:
            from pc.scoring.scorer_v2 import run_l1_scoring_v2
            from pc.scoring.scorer_v3 import run_scoring
            from pc.l2.deal_gap import update_all_properties_l2
            run_l1_scoring_v2()
            run_scoring()
            update_all_properties_l2()
        except Exception as e2:
            print(f"[Rescore V3/V2 Error] {e2}")

        try:
            from pc.viewer.generate_report import generate_report
            generate_report()
        except:
            pass
        crawl_state["progress_msg"] = "퀀트 점수 재계산 완료"
        crawl_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        crawl_state["progress_msg"] = f"재계산 중 오류: {e}"
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
    uvicorn.run("pc.web_app:app", host="127.0.0.1", port=8585, reload=False)
