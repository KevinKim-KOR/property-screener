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

                properties.append({
                    "property_id": pid,
                    "complex_code": cc,
                    "complex_name": str(row["complex_name"] or "Unknown"),
                    "region_name": region_name,
                    "building_dong": str(row["building_dong"] or "-"),
                    "floor": str(row["floor"] or "-"),
                    "floor_grade": str(row["floor_grade"] or "MID"),
                    "area_type": at,
                    "area_pyeong": float(row["area_pyeong"] or 0),
                    "asking_price": asking_price,
                    "median_price_3m": med_3m,
                    "deal_gap_pct": deal_gap,
                    "peak_price": peak_price,
                    "excess_drop_rate": round(excess_drop, 2),
                    "change_1m": round(float(row["change_1m"] or 0.0), 2),
                    "change_3m": round(float(row["change_3m"] or 0.0), 2),
                    "change_6m": round(float(row["change_6m"] or 0.0), 2),
                    "market_score": round(market_score, 1),
                    "score_v1": round(score_v1, 1),
                    "gate_status": ms.get("gate_status", "PASSED"),
                    "gate_reason": ms.get("gate_reason"),
                    "has_evidence": bool(ms.get("evidence_json")),
                    "naver_link": f"https://new.land.naver.com/complexes/{cc}" if cc and cc.isdigit() else ""
                })
            conn.close()
        except Exception as e:
            print(f"[WebGUI] DB read error: {e}")

    properties.sort(key=lambda x: x["market_score"], reverse=True)
    return {
        "count": len(properties),
        "last_updated": crawl_state["last_updated"] or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "properties": properties
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
    html = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>부동산 퀀트 스크리너 V2 - 프로페셔널 벤치마크 대시보드</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-main: #080c14;
            --bg-card: rgba(19, 25, 36, 0.75);
            --bg-card-hover: rgba(28, 37, 51, 0.85);
            --border: rgba(255, 255, 255, 0.08);
            --primary: #3b82f6;
            --primary-glow: rgba(59, 130, 246, 0.4);
            --accent-cyan: #06b6d4;
            --accent-green: #10b981;
            --accent-rose: #f43f5e;
            --accent-amber: #f59e0b;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --font: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            --font-display: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: var(--bg-main);
            background-image: radial-gradient(circle at 10% 15%, rgba(59, 130, 246, 0.1) 0%, transparent 40%),
                              radial-gradient(circle at 90% 85%, rgba(6, 182, 212, 0.08) 0%, transparent 45%);
            color: var(--text-main);
            font-family: var(--font);
            padding: 36px 30px;
            line-height: 1.5;
            min-height: 100vh;
        }
        .container { max-width: 1480px; margin: 0 auto; }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 24px;
            margin-bottom: 30px;
        }
        h1 {
            font-family: var(--font-display);
            font-size: 30px;
            font-weight: 800;
            background: linear-gradient(135deg, #60a5fa 0%, #38bdf8 50%, #34d399 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .subtitle { font-size: 14px; color: var(--text-muted); margin-top: 6px; font-weight: 500; }
        
        /* Tabs */
        .tabs {
            display: flex;
            gap: 14px;
            margin-bottom: 28px;
        }
        .tab-btn {
            background: rgba(30, 41, 59, 0.4);
            color: var(--text-muted);
            border: 1px solid var(--border);
            padding: 12px 26px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            backdrop-filter: blur(10px);
        }
        .tab-btn:hover {
            color: #fff;
            border-color: rgba(255,255,255,0.2);
            transform: translateY(-1px);
        }
        .tab-btn.active {
            background: linear-gradient(135deg, #3b82f6 0%, #06b6d4 100%);
            color: #fff;
            border-color: transparent;
            box-shadow: 0 8px 25px rgba(59, 130, 246, 0.35);
        }
        
        /* Panels */
        .panel { display: none; }
        .panel.active { display: block; }
        
        /* Cards */
        .card {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 26px 30px;
            margin-bottom: 26px;
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.4);
            transition: border-color 0.3s ease;
        }
        .card:hover { border-color: rgba(96, 165, 250, 0.25); }
        
        /* Benchmark Widget Grid */
        .benchmark-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 16px;
            margin-top: 14px;
        }
        .bench-item {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 14px;
            padding: 18px 20px;
            transition: all 0.25s;
        }
        .bench-item:hover {
            background: rgba(255, 255, 255, 0.05);
            transform: translateY(-2px);
            border-color: rgba(59, 130, 246, 0.3);
        }
        .bench-title {
            font-weight: 700;
            color: #60a5fa;
            font-size: 15px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .bench-stats {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        .bench-stat-box {
            background: rgba(0, 0, 0, 0.25);
            padding: 8px 12px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.04);
        }
        .bench-stat-label { font-size: 11px; color: var(--text-muted); font-weight: 500; }
        .bench-stat-value { font-size: 14px; font-weight: 700; color: #fff; margin-top: 2px; }

        /* Filter group */
        .filter-section {
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            align-items: center;
            gap: 24px;
        }
        .pyeong-btn-group { display: flex; gap: 8px; }
        .py-btn {
            background: rgba(30, 41, 59, 0.5);
            color: #94a3b8;
            border: 1px solid var(--border);
            padding: 8px 20px;
            border-radius: 9999px;
            font-weight: 600;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.25s;
        }
        .py-btn:hover { color: #fff; background: rgba(51, 65, 85, 0.8); }
        .py-btn.active {
            background: linear-gradient(135deg, #3b82f6 0%, #06b6d4 100%);
            color: #fff;
            border-color: transparent;
            box-shadow: 0 0 15px rgba(59, 130, 246, 0.4);
        }

        /* Table */
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th {
            background: rgba(255, 255, 255, 0.03);
            color: #94a3b8;
            font-size: 13px;
            font-weight: 700;
            padding: 16px 18px;
            border-bottom: 1px solid var(--border);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        td {
            padding: 18px;
            border-bottom: 1px solid var(--border);
            font-size: 14px;
            vertical-align: middle;
            transition: background 0.2s;
        }
        tr:hover td { background: rgba(59, 130, 246, 0.05); }

        /* Rank Badge */
        .rank-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 32px;
            height: 32px;
            border-radius: 8px;
            font-weight: 800;
            font-size: 14px;
        }
        .rank-1 { background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: 1px solid #f59e0b; }
        .rank-2 { background: rgba(148, 163, 184, 0.2); color: #cbd5e1; border: 1px solid #94a3b8; }
        .rank-3 { background: rgba(217, 119, 6, 0.2); color: #d97706; border: 1px solid #d97706; }
        .rank-other { color: var(--text-muted); }

        /* Region tag */
        .region-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 700;
            background: rgba(59, 130, 246, 0.15);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.3);
        }

        /* Deal Gap Badges */
        .gap-badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 700;
            margin-top: 3px;
        }
        .gap-bargain { background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid #10b981; }
        .gap-discount { background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); }
        .gap-premium { background: rgba(244, 63, 94, 0.15); color: #f43f5e; border: 1px solid rgba(244, 63, 94, 0.4); }

        /* Score Pill */
        .score-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 14px;
            border-radius: 9999px;
            font-weight: 800;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.25s;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        .score-high {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.25), rgba(6, 182, 212, 0.25));
            border: 1px solid #10b981;
            color: #10b981;
        }
        .score-high:hover {
            box-shadow: 0 0 20px rgba(16, 185, 129, 0.5);
            transform: scale(1.05);
        }
        .score-mid {
            background: rgba(59, 130, 246, 0.2);
            border: 1px solid #3b82f6;
            color: #60a5fa;
        }
        .score-low {
            background: rgba(148, 163, 184, 0.15);
            border: 1px solid var(--border);
            color: #94a3b8;
        }

        /* Naver button */
        .btn-naver {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border);
            color: #f1f5f9;
            text-decoration: none;
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.2s;
            display: inline-block;
        }
        .btn-naver:hover {
            background: var(--primary);
            border-color: var(--primary);
            color: #fff;
            box-shadow: 0 4px 15px rgba(59, 130, 246, 0.4);
        }

        /* Status box */
        .status-box {
            display: none;
            background: rgba(59, 130, 246, 0.15);
            border: 1px solid var(--primary);
            color: #fff;
            padding: 16px 24px;
            border-radius: 12px;
            margin-bottom: 24px;
            font-weight: 600;
        }
        .spinner {
            display: inline-block;
            width: 18px;
            height: 18px;
            border: 3px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: #fff;
            animation: spin 1s ease-in-out infinite;
            margin-right: 12px;
            vertical-align: middle;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* Regions Grid */
        .regions-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
            gap: 14px;
            margin: 24px 0;
        }
        .region-item {
            display: flex;
            align-items: center;
            gap: 12px;
            background: rgba(255,255,255,0.03);
            border: 1px solid var(--border);
            padding: 16px;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .region-item:hover { background: rgba(255,255,255,0.07); border-color: rgba(59, 130, 246, 0.4); }
        .region-item input[type="checkbox"] { width: 18px; height: 18px; accent-color: var(--primary); }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>⚡ 부동산 퀀트 스크리너 V2 <span style="font-size:14px; background:rgba(16,185,129,0.2); color:#10b981; padding:4px 10px; border-radius:6px; font-weight:700;">4-Block 상대평가 엔진</span></h1>
                <div class="subtitle">서울 주요 아파트 실시간 국토부·네이버 매물 입지·하락률·호가 괴리율 스크리닝 대시보드</div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 13px; color: var(--text-muted);">최근 갱신 시간</div>
                <div id="lastUpdated" style="font-weight: 700; color: #fff; font-size: 15px;">-</div>
            </div>
        </header>

        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('dashboard')">📊 매물 퀀트 분석 대시보드</button>
            <button class="tab-btn" onclick="switchTab('regions')">🎯 수집 지역 선택 & 실시간 크롤링</button>
        </div>

        <div id="statusBox" class="status-box">
            <span class="spinner"></span> <span id="statusText">크롤링 진행 중...</span>
        </div>

        <!-- 1. 매물 대시보드 패널 -->
        <div id="dashboard" class="panel active">
            <!-- 0. 권역 및 자치구 벤치마크 -->
            <div class="card" style="background: linear-gradient(135deg, rgba(19, 25, 36, 0.9) 0%, rgba(30, 41, 59, 0.8) 100%);">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <h2 style="font-size: 17px; color: #fff; font-weight: 700; display: flex; align-items: center; gap: 8px;">
                        <span>🏛️ 권역(BELT) 및 자치구별 시장 실거래 벤치마크 (4-Block 기준선)</span>
                    </h2>
                    <span style="font-size: 12px; color: var(--text-muted);">※ 국토교통부 실거래 최신 스냅샷 기준</span>
                </div>
                <div id="regionStatsGrid" class="benchmark-grid">
                    <div style="color: var(--text-muted); font-size: 14px;">벤치마크 지표를 불러오는 중...</div>
                </div>
            </div>

            <!-- 조회 조건 바 -->
            <div class="card">
                <div class="filter-section">
                    <div style="display: flex; align-items: center; gap: 14px;">
                        <span style="color: #fff; font-size: 14px; font-weight: 700;">📐 평형 선택:</span>
                        <div class="pyeong-btn-group" id="pyeongFilterGroup">
                            <button class="py-btn active" onclick="setPyeongFilter('all', this)">전체 평형</button>
                            <button class="py-btn" onclick="setPyeongFilter('20', this)">20평형대</button>
                            <button class="py-btn" onclick="setPyeongFilter('30', this)">30평형대</button>
                            <button class="py-btn" onclick="setPyeongFilter('40', this)">40평형대 이상</button>
                        </div>
                    </div>

                    <div style="display: flex; align-items: center; gap: 16px; flex: 1; max-width: 480px; justify-content: flex-end;">
                        <span style="color: #fff; font-size: 14px; font-weight: 700;">💰 금액 조건 (좌우 조절):</span>
                        <input type="range" id="priceSlider" min="1500" max="6000" step="100" value="6000" oninput="onPriceSliderChange()" style="flex: 1; accent-color: var(--primary); cursor: pointer; height: 6px;" />
                        <span id="priceSliderLabel" style="font-weight: 800; color: #fff; min-width: 96px; text-align: center; background: rgba(59, 130, 246, 0.2); padding: 6px 12px; border-radius: 8px; border: 1px solid #3b82f6;">🎯 60.0억 이하</span>
                    </div>
                </div>
            </div>

            <!-- 매물 목록 테이블 -->
            <div class="card" style="padding: 24px 20px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding: 0 10px;">
                    <h2 style="font-size: 19px; font-weight: 800; color: #fff;">🏆 실시간 매물 퀀트 스크리닝 (조회 <span id="propCount" style="color:var(--accent-cyan);">0</span>건)</h2>
                    <div style="display: flex; gap: 12px;">
                        <button id="rescoreBtn" onclick="triggerRescore()" style="background: rgba(16, 185, 129, 0.2); border: 1px solid var(--accent-green); color: var(--accent-green); padding: 10px 20px; border-radius: 10px; cursor: pointer; font-weight: 700; transition: all 0.2s;">⚡ 퀀트 점수 즉시 재계산 (API 미호출)</button>
                        <button onclick="loadProperties()" style="background: rgba(255,255,255,0.05); border: 1px solid var(--border); color: #fff; padding: 10px 20px; border-radius: 10px; cursor: pointer; font-weight: 700; transition: all 0.2s;">화면 새로고침 ↻</button>
                    </div>
                </div>
                <div style="overflow-x: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>순위</th>
                                <th>지역명</th>
                                <th>단지명 (동 / 층 / 층급)</th>
                                <th>평형</th>
                                <th>현재가(호가)</th>
                                <th>기준가(3M중위)</th>
                                <th>전고점</th>
                                <th>최근 1개월</th>
                                <th>최근 3개월</th>
                                <th>최근 6개월</th>
                                <th>퀀트점수(V2 / V1)</th>
                                <th>매물확인</th>
                            </tr>
                        </thead>
                        <tbody id="propTableBody">
                            <tr><td colspan="12" style="text-align:center; padding: 50px; color: var(--text-muted);">데이터를 불러오는 중입니다...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- 2. 지역 설정 및 크롤링 패널 -->
        <div id="regions" class="panel">
            <div class="card">
                <h2 style="font-size: 20px; color: #fff; margin-bottom: 10px; font-weight: 700;">🎯 관심 지역 및 크롤링 타겟 선택</h2>
                <p style="color: var(--text-muted); font-size: 14px;">
                    아래 지역에서 스크리닝을 원하는 법정동을 선택하세요. '선택 지역 저장 후 실시간 크롤링 시작' 버튼을 누르면 즉시 네이버 부동산 매물을 갱신합니다.
                </p>
                <div class="regions-grid" id="regionCheckboxes">
                    <!-- JS loaded -->
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 28px; padding-top: 24px; border-top: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 13px;">체크된 지역의 아파트 단지만 DB에 최신 매물로 수집·분석됩니다.</span>
                    <button id="crawlBtn" onclick="saveAndCrawl()" style="background: linear-gradient(135deg, #3b82f6 0%, #06b6d4 100%); color: #fff; border: none; padding: 14px 32px; border-radius: 12px; font-size: 15px; font-weight: 700; cursor: pointer; box-shadow: 0 10px 25px rgba(59, 130, 246, 0.4);">선택 지역 저장 후 실시간 크롤링 시작 →</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Evidence Modal -->
    <div id="evidenceModal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); backdrop-filter:blur(8px); z-index:9999; justify-content:center; align-items:center;">
        <div style="background:#111827; border:1px solid rgba(255,255,255,0.15); border-radius:20px; width:720px; max-width:92%; padding:30px; box-shadow:0 25px 60px rgba(0,0,0,0.7); max-height:85vh; overflow-y:auto; position:relative;">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); padding-bottom:18px; margin-bottom:20px;">
                <h3 id="evTitle" style="color:#fff; font-size:20px; font-weight:800; display:flex; align-items:center; gap:8px;">📈 스코어링 분석 근거 (4-Block Quant Report)</h3>
                <button onclick="closeEvidenceModal()" style="background:none; border:none; color:var(--text-muted); font-size:24px; cursor:pointer;">✕</button>
            </div>
            <div id="evContent" style="color:var(--text-main); font-size:14px;">
                <!-- JS populated -->
            </div>
        </div>
    </div>

    <script>
        let currentRegions = [];
        let allProperties = [];
        let pyeongFilter = 'all';
        let maxPriceFilter = 600000;

        function switchTab(tabId) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.panel').forEach(panel => panel.classList.remove('active'));
            
            if (tabId === 'dashboard') {
                document.querySelectorAll('.tab-btn')[0].classList.add('active');
                document.getElementById('dashboard').classList.add('active');
                loadProperties();
            } else {
                document.querySelectorAll('.tab-btn')[1].classList.add('active');
                document.getElementById('regions').classList.add('active');
                loadRegions();
            }
        }

        function setPyeongFilter(val, btn) {
            pyeongFilter = val;
            document.querySelectorAll('#pyeongFilterGroup .py-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderTable();
        }

        function onPriceSliderChange() {
            const val = parseInt(document.getElementById('priceSlider').value, 10);
            maxPriceFilter = val * 100;
            document.getElementById('priceSliderLabel').textContent = `🎯 ${(val / 100).toFixed(1)}억 이하`;
            renderTable();
        }

        function formatRank(idx) {
            if (idx === 0) return '<span class="rank-badge rank-1">#1 🏆</span>';
            if (idx === 1) return '<span class="rank-badge rank-2">#2 🥈</span>';
            if (idx === 2) return '<span class="rank-badge rank-3">#3 🥉</span>';
            return `<span class="rank-badge rank-other">#${idx+1}</span>`;
        }

        function formatTrend(val) {
            if (val === null || val === undefined || val === 0) return '<span style="color:#64748b; font-weight:600;">0.0%</span>';
            if (val > 0) return `<span style="color:#10b981; font-weight:700;">▲ +${val.toFixed(1)}%</span>`;
            return `<span style="color:#f43f5e; font-weight:700;">▼ ${val.toFixed(1)}%</span>`;
        }

        function formatGap(gap) {
            if (gap === null || gap === undefined) return '<span style="color:#64748b;">-</span>';
            if (gap <= -10.0) return `<div class="gap-badge gap-bargain">▼ ${gap.toFixed(1)}% 저평가 🔥</div>`;
            if (gap < 0) return `<div class="gap-badge gap-discount">▼ ${gap.toFixed(1)}% 저렴</div>`;
            if (gap > 0) return `<div class="gap-badge gap-premium">▲ +${gap.toFixed(1)}% 고평가</div>`;
            return `<div style="color:#64748b; font-weight:600;">0.0%</div>`;
        }

        function renderTable() {
            const tbody = document.getElementById('propTableBody');
            const filtered = allProperties.filter(item => {
                if (pyeongFilter === '20' && (item.area_pyeong < 20 || item.area_pyeong >= 30)) return false;
                if (pyeongFilter === '30' && (item.area_pyeong < 30 || item.area_pyeong >= 40)) return false;
                if (pyeongFilter === '40' && item.area_pyeong < 40) return false;
                if (item.asking_price > maxPriceFilter) return false;
                return true;
            });

            document.getElementById('propCount').textContent = `${filtered.length} / ${allProperties.length}`;

            if (filtered.length === 0) {
                tbody.innerHTML = '<tr><td colspan="12" style="text-align:center; padding: 60px; color: var(--text-muted); font-size:16px;">조건에 일치하는 매물이 없습니다. 상단의 평형 선택 또는 금액 슬라이더를 변경해 주세요.</td></tr>';
                return;
            }

            tbody.innerHTML = filtered.map((item, idx) => {
                const scoreClass = item.market_score >= 80 ? 'score-high' : (item.market_score >= 65 ? 'score-mid' : 'score-low');
                const priceStr = item.asking_price >= 10000 ? `${(item.asking_price/10000).toFixed(2)}억` : `${item.asking_price.toLocaleString()}만`;
                const med3mStr = item.median_price_3m >= 10000 ? `${(item.median_price_3m/10000).toFixed(2)}억` : `${item.median_price_3m.toLocaleString()}만`;
                const peakStr = item.peak_price >= 10000 ? `${(item.peak_price/10000).toFixed(2)}억` : `${item.peak_price.toLocaleString()}만`;
                const naverUrl = item.naver_link || 'https://new.land.naver.com/';

                const dropStr = item.excess_drop_rate > 0
                    ? `<div style="color:#10b981; font-weight:700; font-size:12px; margin-top:2px;">초과하락 +${item.excess_drop_rate.toFixed(1)}%p</div>`
                    : `<div style="color:var(--text-muted); font-size:12px; margin-top:2px;">초과하락 ${item.excess_drop_rate.toFixed(1)}%p</div>`;

                const gateBadge = item.gate_status === 'EXCLUDED'
                    ? `<span style="background:rgba(239,68,68,0.2);color:#ef4444;font-size:11px;padding:2px 6px;border-radius:4px;margin-left:4px;">G-EXCL</span>`
                    : '';

                return `
                <tr>
                    <td>${formatRank(idx)}</td>
                    <td><span class="region-badge">${item.region_name || '서울 주요지역'}</span></td>
                    <td>
                        <div style="font-weight:700; color:#fff; font-size:15px; margin-bottom:3px;">${item.complex_name}</div>
                        <div style="font-size:12px; color:#94a3b8;">${item.building_dong} / ${item.floor} / <span style="font-weight:700; color:#60a5fa;">${item.floor_grade}</span></div>
                    </td>
                    <td>
                        <div style="font-weight:700; color:#fff;">${item.area_pyeong}평</div>
                        <div style="font-size:12px; color:var(--text-muted);">${item.area_type}</div>
                    </td>
                    <td>
                        <div style="font-weight:800; color:#f8fafc; font-size:17px;">${priceStr}</div>
                    </td>
                    <td>
                        <div style="color:#cbd5e1; font-weight:700; font-size:15px;">${med3mStr}</div>
                        ${formatGap(item.deal_gap_pct)}
                    </td>
                    <td>
                        <div style="color:#f1f5f9; font-weight:700; font-size:15px;">${peakStr}</div>
                        ${dropStr}
                    </td>
                    <td>${formatTrend(item.change_1m)}</td>
                    <td>${formatTrend(item.change_3m)}</td>
                    <td>${formatTrend(item.change_6m)}</td>
                    <td>
                        <div class="score-pill ${scoreClass}" onclick="openEvidenceModal('${item.complex_code}', '${item.area_type}', '${item.complex_name.replace(/'/g, "\\'")}')" title="클릭 시 4-Block 상대평가 근거 보고서 열기">
                            <span>V2: ${item.market_score.toFixed(1)}점</span> <span>🔍</span>
                        </div>
                        <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">(V1: ${item.score_v1.toFixed(1)}점) ${gateBadge}</div>
                    </td>
                    <td><a href="${naverUrl}" target="_blank" class="btn-naver">네이버 매물 ↗</a></td>
                </tr>
                `;
            }).join('');
        }

        async function loadProperties() {
            try {
                const res = await fetch('/api/properties');
                const data = await res.json();
                allProperties = data.properties || [];
                document.getElementById('lastUpdated').textContent = data.last_updated || '-';
                renderTable();
                loadRegionStats();
            } catch (err) {
                console.error(err);
            }
        }

        async function loadRegionStats() {
            try {
                const res = await fetch('/api/region_stats');
                const data = await res.json();
                const container = document.getElementById('regionStatsGrid');
                if (!container || !data || data.length === 0) {
                    container.innerHTML = '<div style="color: var(--text-muted);">지역 통계 데이터가 없습니다.</div>';
                    return;
                }
                
                const sggNames = {'11650': '서초구', '11680': '강남구', 'BELT': '강남/서초 권역(BELT)'};
                container.innerHTML = data.map(st => {
                    const nm = sggNames[st.sgg_cd] || st.sgg_cd;
                    const dropPct = (st.median_drop_rate * 100).toFixed(1);
                    return `
                    <div class="bench-item">
                        <div class="bench-title">
                            <span>${nm} - [${st.area_type}]</span>
                            <span style="font-size:11px; background:rgba(59,130,246,0.2); color:#60a5fa; padding:2px 8px; border-radius:4px;">실거래 기준선</span>
                        </div>
                        <div class="bench-stats">
                            <div class="bench-stat-box">
                                <div class="bench-stat-label">📉 중위 하락률</div>
                                <div class="bench-stat-value" style="color:#10b981;">${dropPct}%</div>
                            </div>
                            <div class="bench-stat-box">
                                <div class="bench-stat-label">💎 3M 중위 평단가</div>
                                <div class="bench-stat-value">${Math.round(st.median_ppp).toLocaleString()}만/평</div>
                            </div>
                            <div class="bench-stat-box">
                                <div class="bench-stat-label">🏠 전세가율</div>
                                <div class="bench-stat-value">${(st.median_jeonse_ratio * 100).toFixed(1)}%</div>
                            </div>
                            <div class="bench-stat-box">
                                <div class="bench-stat-label">📦 거래 샘플수</div>
                                <div class="bench-stat-value">${st.sample_n}건</div>
                            </div>
                        </div>
                    </div>
                    `;
                }).join('');
            } catch (err) {
                console.error(err);
            }
        }

        async function openEvidenceModal(complexCode, areaType, complexName) {
            const modal = document.getElementById('evidenceModal');
            const content = document.getElementById('evContent');
            const title = document.getElementById('evTitle');
            title.textContent = `📈 ${complexName || complexCode} (${areaType}) - 4-Block 스코어링 근거`;
            content.innerHTML = '<div style="text-align:center; padding:30px; color:var(--text-muted);">스코어링 근거(Evidence)를 불러오는 중...</div>';
            modal.style.display = 'flex';

            try {
                const res = await fetch(`/api/evidence?complex_code=${complexCode}&area_type=${areaType}`);
                const data = await res.json();
                if (data.error) {
                    content.innerHTML = `<div style="color:#ef4444; padding:20px;">${data.error}</div>`;
                    return;
                }

                const blocks = data.blocks || {};
                const factors = data.factors || {};
                const gStatus = data.gate_status || 'PASSED';
                const gReason = data.gate_reason || '정상 (특이사항 없음)';

                let html = `
                <div style="background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:8px; padding:15px; margin-bottom:16px;">
                    <div style="font-weight:700; color:#fff; font-size:16px; margin-bottom:6px;">최종 시장점수(V2): <span style="color:#10b981;">${data.market_score || 0}점</span> (기본점수: ${data.base_score || 0}점)</div>
                    <div style="font-size:13px; color:${gStatus==='EXCLUDED'?'#ef4444':'#60a5fa'};">게이트 심사: <strong>${gStatus}</strong> (${gReason})</div>
                    <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">비교군(Peer Group): ${data.peer_group || 'BELT_A84'}</div>
                </div>

                <h4 style="color:#fff; margin-bottom:10px;">4-Block 기여도 (가중합)</h4>
                <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:10px; margin-bottom:20px;">
                    <div style="background:rgba(78,154,241,0.1); border:1px solid #4e9af1; border-radius:8px; padding:10px; text-align:center;">
                        <div style="color:var(--text-muted); font-size:12px;">가치 (Value 35%)</div>
                        <div style="color:#fff; font-weight:700; font-size:16px; margin-top:4px;">${blocks.Value ? blocks.Value.toFixed(2) : '0.00'}</div>
                    </div>
                    <div style="background:rgba(16,185,129,0.1); border:1px solid #10b981; border-radius:8px; padding:10px; text-align:center;">
                        <div style="color:var(--text-muted); font-size:12px;">수급 (Flow 25%)</div>
                        <div style="color:#fff; font-weight:700; font-size:16px; margin-top:4px;">${blocks.Flow ? blocks.Flow.toFixed(2) : '0.00'}</div>
                    </div>
                    <div style="background:rgba(245,158,11,0.1); border:1px solid #f59e0b; border-radius:8px; padding:10px; text-align:center;">
                        <div style="color:var(--text-muted); font-size:12px;">입지 (Location 20%)</div>
                        <div style="color:#fff; font-weight:700; font-size:16px; margin-top:4px;">${blocks.Location ? blocks.Location.toFixed(2) : '0.00'}</div>
                    </div>
                    <div style="background:rgba(168,85,247,0.1); border:1px solid #a855f7; border-radius:8px; padding:10px; text-align:center;">
                        <div style="color:var(--text-muted); font-size:12px;">품격 (Quality 20%)</div>
                        <div style="color:#fff; font-weight:700; font-size:16px; margin-top:4px;">${blocks.Quality ? blocks.Quality.toFixed(2) : '0.00'}</div>
                    </div>
                </div>

                <h4 style="color:#fff; margin-bottom:10px;">세부 팩터별 Z-Score 및 통계값</h4>
                <table style="width:100%; border-collapse:collapse; font-size:13px;">
                    <thead>
                        <tr style="border-bottom:1px solid var(--border); color:var(--text-muted);">
                            <th style="padding:8px; text-align:left;">팩터명</th>
                            <th style="padding:8px; text-align:right;">원시 통계값</th>
                            <th style="padding:8px; text-align:right;">Z-Score</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;">초과하락률 (F1)</td><td style="padding:8px; text-align:right;">${((factors.F1_raw||0)*100).toFixed(2)}%p</td><td style="padding:8px; text-align:right; font-weight:700; color:#4e9af1;">${(factors.F1_z||0).toFixed(2)}</td></tr>
                        <tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;">전세가율 괴리 (F2)</td><td style="padding:8px; text-align:right;">${((factors.F2_raw||0)*100).toFixed(2)}%p</td><td style="padding:8px; text-align:right; font-weight:700; color:#4e9af1;">${(factors.F2_z||0).toFixed(2)}</td></tr>
                        <tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;">평균 거래량 비중 (F3)</td><td style="padding:8px; text-align:right;">${(factors.F3_raw||0).toFixed(2)}</td><td style="padding:8px; text-align:right; font-weight:700; color:#10b981;">${(factors.F3_z||0).toFixed(2)}</td></tr>
                        <tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;">소화 속도 (F4)</td><td style="padding:8px; text-align:right;">${(factors.F4_raw||0).toFixed(2)}</td><td style="padding:8px; text-align:right; font-weight:700; color:#10b981;">${(factors.F4_z||0).toFixed(2)}</td></tr>
                        <tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;">평단가 프리미엄 (F5)</td><td style="padding:8px; text-align:right;">${(factors.F5_raw||0).toFixed(2)}%</td><td style="padding:8px; text-align:right; font-weight:700; color:#f59e0b;">${(factors.F5_z||0).toFixed(2)}</td></tr>
                        <tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;">지하철 접근성 (F6)</td><td style="padding:8px; text-align:right;">${(factors.F6_raw||0)}</td><td style="padding:8px; text-align:right; font-weight:700; color:#f59e0b;">${(factors.F6_z||0).toFixed(2)}</td></tr>
                        <tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;">세대수 (F7)</td><td style="padding:8px; text-align:right;">${(factors.F7_raw||0)}</td><td style="padding:8px; text-align:right; font-weight:700; color:#a855f7;">${(factors.F7_z||0).toFixed(2)}</td></tr>
                        <tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;">건축 연한 (F8)</td><td style="padding:8px; text-align:right;">${(factors.F8_raw||0)}년</td><td style="padding:8px; text-align:right; font-weight:700; color:#a855f7;">${(factors.F8_z||0).toFixed(2)}</td></tr>
                    </tbody>
                </table>
                `;
                content.innerHTML = html;
            } catch (err) {
                content.innerHTML = `<div style="color:#ef4444; padding:20px;">오류: ${err.message}</div>`;
            }
        }

        function closeEvidenceModal() {
            document.getElementById('evidenceModal').style.display = 'none';
        }

        async function loadRegions() {
            try {
                const res = await fetch('/api/regions');
                const data = await res.json();
                const activeCodes = new Set(data.active_regions.map(r => r.code));

                const container = document.getElementById('regionCheckboxes');
                container.innerHTML = data.presets.map(item => {
                    const checked = activeCodes.has(item.code) ? 'checked' : '';
                    return `
                    <label class="region-item">
                        <input type="checkbox" value="${item.code}" data-name="${item.name}" ${checked} />
                        <div>
                            <div class="region-name">${item.name}</div>
                            <div class="region-code">법정동코드: ${item.code}</div>
                        </div>
                    </label>
                    `;
                }).join('');
            } catch (err) {
                console.error(err);
            }
        }

        async function triggerRescore() {
            try {
                const res = await fetch('/api/rescore', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    checkStatusLoop();
                } else {
                    alert(data.message);
                }
            } catch (err) {
                alert('오류 발생: ' + err.message);
            }
        }

        async function saveAndCrawl() {
            const checkboxes = document.querySelectorAll('#regionCheckboxes input[type="checkbox"]:checked');
            const selected = Array.from(checkboxes).map(cb => ({
                name: cb.getAttribute('data-name'),
                code: cb.value
            }));

            if (selected.length === 0) {
                alert('최소 1개 이상의 관심 지역을 선택해 주세요.');
                return;
            }

            try {
                // 1. config.yaml에 대상 지역 저장
                const saveRes = await fetch('/api/regions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ regions: selected })
                });
                if (!saveRes.ok) throw new Error('지역 저장 실패');

                // 2. 크롤링 시작 요청
                const crawlRes = await fetch('/api/crawl', { method: 'POST' });
                const crawlData = await crawlRes.json();

                if (crawlData.success) {
                    alert('선택한 지역(' + selected.length + '곳)의 아파트 매물 수집을 시작했습니다. 화면 상단 상태표시바에서 진행 상황을 확인하실 수 있습니다.');
                    checkStatusLoop();
                } else {
                    alert(crawlData.message);
                }
            } catch (err) {
                alert('오류 발생: ' + err.message);
            }
        }

        async function checkStatusLoop() {
            const statusBox = document.getElementById('statusBox');
            const statusText = document.getElementById('statusText');
            const crawlBtn = document.getElementById('crawlBtn');

            const interval = setInterval(async () => {
                try {
                    const res = await fetch('/api/status');
                    const status = await res.json();

                    if (status.is_crawling) {
                        statusBox.style.display = 'block';
                        statusText.textContent = status.progress_msg;
                        crawlBtn.disabled = true;
                        crawlBtn.textContent = '크롤링 진행 중... (대기)';
                    } else {
                        statusBox.style.display = 'none';
                        crawlBtn.disabled = false;
                        crawlBtn.textContent = '선택 지역 저장 후 실시간 크롤링 시작 →';
                        clearInterval(interval);
                        loadProperties();
                    }
                } catch (e) {
                    clearInterval(interval);
                }
            }, 1500);
        }

        // 초기 로딩
        loadProperties();
        checkStatusLoop();
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("pc.web_app:app", host="127.0.0.1", port=8585, reload=False)
