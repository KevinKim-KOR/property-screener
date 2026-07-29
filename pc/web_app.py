import json
import sqlite3
import yaml
import sys
import os
import threading
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
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
    """screener.db 매물 정보와 ml_results.json 퀀트 점수를 병합하여 반환합니다."""
    db_path = root_dir / "screener.db"
    json_path = root_dir / "ml_results.json"

    ml_data = {}
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    ml_data = loaded
                elif isinstance(loaded, list):
                    for item in loaded:
                        pid = item.get("property_id") or item.get("id") or str(len(ml_data)+1)
                        ml_data[pid] = item
        except Exception as e:
            print(f"[WebGUI] JSON load error: {e}")

    properties = []
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM properties")
            for row in cursor.fetchall():
                pid = str(row["property_id"])
                score_info = ml_data.get(pid, {})
                score = score_info.get("ml_score", score_info.get("quant_score", 0.0))
                
                asking_price = float(row["asking_price"] or 0)
                drop_rate = float(row["drop_rate"] or 0.0)
                
                # 전고점 실거래가 조회 및 부재 시 자동 역산 (만원 단위)
                high_price = 0.0
                if "high_price" in row.keys() and row["high_price"]:
                    high_price = float(row["high_price"])
                if high_price <= 0 and asking_price > 0:
                    high_price = asking_price / max(0.5, (1.0 - drop_rate))
                
                # 지역명 조회 및 부재 시 보정
                region_name = ""
                if "region_name" in row.keys() and row["region_name"]:
                    region_name = str(row["region_name"])
                if not region_name or region_name == "Unknown":
                    c_name = str(row["complex_name"] or "")
                    if "반포" in c_name or "자이" in c_name or "퍼스티지" in c_name:
                        region_name = "서초구 반포동"
                    elif "개포" in c_name or "디에이치" in c_name:
                        region_name = "강남구 개포동"
                    else:
                        region_name = "서울 주요지역"

                properties.append({
                    "property_id": pid,
                    "complex_code": str(row["complex_code"] or ""),
                    "complex_name": str(row["complex_name"] or "Unknown"),
                    "region_name": region_name,
                    "building_dong": str(row["building_dong"] or "-"),
                    "floor": str(row["floor"] or "-"),
                    "high_price": float(high_price),
                    "asking_price": float(asking_price),
                    "area_pyeong": float(row["area_pyeong"] or 0),
                    "drop_rate": float(drop_rate),
                    "score": float(score)
                })
            conn.close()
        except Exception as e:
            print(f"[WebGUI] DB read error: {e}")

    properties.sort(key=lambda x: x["score"], reverse=True)
    return {
        "count": len(properties),
        "last_updated": crawl_state["last_updated"] or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "properties": properties
    }

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
        
        crawl_state["progress_msg"] = "수집 완료 -> 퀀트 점수 분석(MLEngine) 실행 중..."
        MLEngine.run()
        
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
    crawl_state["progress_msg"] = "로컬 DB 매물의 퀀트 점수 및 입지 가점 재계산 중 (API 미호출)..."
    try:
        MLEngine.run()
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

@app.get("/", response_class=HTMLResponse)
def index_page():
    html = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>부동산 퀀트 스크리너 - 로컬 웹 대시보드</title>
    <style>
        :root {
            --bg-main: #0a0e14;
            --bg-card: #151a21;
            --bg-card-hover: #1e252f;
            --border: #29323f;
            --primary: #4e9af1;
            --primary-hover: #3b82f6;
            --accent-green: #10b981;
            --text-main: #e2e8f0;
            --text-muted: #94a3b8;
            --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: var(--bg-main);
            color: var(--text-main);
            font-family: var(--font);
            padding: 30px;
            line-height: 1.5;
        }
        .container { max-width: 1300px; margin: 0 auto; }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 20px;
            margin-bottom: 25px;
        }
        h1 { font-size: 26px; font-weight: 700; color: #fff; }
        .subtitle { font-size: 14px; color: var(--text-muted); margin-top: 4px; }
        
        /* Tabs */
        .tabs {
            display: flex;
            gap: 12px;
            margin-bottom: 25px;
        }
        .tab-btn {
            background: var(--bg-card);
            color: var(--text-muted);
            border: 1px solid var(--border);
            padding: 10px 22px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .tab-btn.active {
            background: var(--primary);
            color: #fff;
            border-color: var(--primary);
            box-shadow: 0 0 15px rgba(78, 154, 241, 0.4);
        }
        
        /* Panels */
        .panel { display: none; }
        .panel.active { display: block; }
        
        /* Card */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
        }
        
        /* Regions Grid */
        .regions-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 14px;
            margin: 20px 0;
        }
        .region-item {
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(255,255,255,0.02);
            border: 1px solid var(--border);
            padding: 14px;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.2s;
        }
        .region-item:hover { background: rgba(255,255,255,0.05); }
        .region-item input[type="checkbox"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
            accent-color: var(--primary);
        }
        .region-name { font-weight: 600; font-size: 14px; color: #fff; }
        .region-code { font-size: 12px; color: var(--text-muted); }

        /* Actions */
        .action-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 25px;
            padding-top: 20px;
            border-top: 1px solid var(--border);
        }
        .btn-primary {
            background: var(--primary);
            color: #fff;
            border: none;
            padding: 12px 28px;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-primary:hover { background: var(--primary-hover); }
        .btn-primary:disabled {
            background: var(--border);
            color: var(--text-muted);
            cursor: not-allowed;
        }
        
        /* Table */
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th {
            background: rgba(255, 255, 255, 0.03);
            color: var(--text-muted);
            font-size: 13px;
            font-weight: 600;
            padding: 14px 18px;
            border-bottom: 1px solid var(--border);
        }
        td {
            padding: 16px 18px;
            border-bottom: 1px solid var(--border);
            font-size: 14px;
        }
        tr:hover { background: rgba(255, 255, 255, 0.02); }
        .badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 13px;
        }
        .badge-high { background: rgba(16,185,129,0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }
        .badge-mid { background: rgba(245,158,11,0.2); color: #f59e0b; border: 1px solid #f59e0b; }
        .badge-low { background: rgba(148,163,184,0.1); color: var(--text-muted); border: 1px solid var(--border); }
        
        .py-btn {
            background: var(--bg-main);
            color: var(--text-muted);
            border: 1px solid var(--border);
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .py-btn.active {
            background: var(--primary);
            color: #fff;
            border-color: var(--primary);
        }
        
        .naver-link {
            display: inline-block;
            padding: 6px 12px;
            background: #2563eb;
            color: #fff;
            text-decoration: none;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
        }
        .naver-link:hover { background: #3b82f6; }
        
        /* Status message */
        .status-box {
            display: none;
            background: rgba(78, 154, 241, 0.15);
            border: 1px solid var(--primary);
            color: #fff;
            padding: 14px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-weight: 600;
        }
        .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 3px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: #fff;
            animation: spin 1s ease-in-out infinite;
            margin-right: 10px;
            vertical-align: middle;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>부동산 퀀트 스크리너 - 스마트 웹 대시보드</h1>
                <div class="subtitle">서울 주요 아파트 단지 실시간 크롤링 및 ML 입지·하락률 분석 대시보드</div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 13px; color: var(--text-muted);">최근 갱신 시간</div>
                <div id="lastUpdated" style="font-weight: 600; color: #fff;">-</div>
            </div>
        </header>

        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('dashboard')">매물 퀀트 분석 대시보드</button>
            <button class="tab-btn" onclick="switchTab('regions')">수집 지역 선택 & 실시간 크롤링</button>
        </div>

        <div id="statusBox" class="status-box">
            <span class="spinner"></span> <span id="statusText">크롤링 진행 중...</span>
        </div>

        <!-- 1. 매물 대시보드 패널 -->
        <div id="dashboard" class="panel active">
            <div class="card" style="margin-bottom: 20px; padding: 18px 24px;">
                <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 20px;">
                    <!-- 평형 조건 필터 -->
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <span style="color: #fff; font-size: 14px; font-weight: 700;">📐 평형 조건:</span>
                        <div class="pyeong-btn-group" id="pyeongFilterGroup" style="display: flex; gap: 6px;">
                            <button class="py-btn active" onclick="setPyeongFilter('all', this)">전체 평형</button>
                            <button class="py-btn" onclick="setPyeongFilter('20', this)">20평형대</button>
                            <button class="py-btn" onclick="setPyeongFilter('30', this)">30평형대</button>
                            <button class="py-btn" onclick="setPyeongFilter('40', this)">40평형대 이상</button>
                        </div>
                    </div>

                    <!-- 금액 조회 조건 (가로막대 슬라이더 좌우 조절) -->
                    <div style="display: flex; align-items: center; gap: 14px; flex: 1; min-width: 320px; justify-content: flex-end;">
                        <span style="color: #fff; font-size: 14px; font-weight: 700;">💰 금액 조건 (좌우 조절):</span>
                        <input type="range" id="priceSlider" min="1500" max="6000" step="100" value="6000" oninput="onPriceSliderChange()" style="flex: 1; max-width: 240px; accent-color: var(--primary); cursor: pointer;" />
                        <span id="priceSliderLabel" style="font-weight: 700; color: #fff; min-width: 86px; text-align: center; background: rgba(78, 154, 241, 0.15); padding: 5px 10px; border-radius: 6px; border: 1px solid var(--primary);">60.0억 이하</span>
                    </div>
                </div>
            </div>

            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <h2 style="font-size: 18px; color: #fff;">실시간 퀀트 점수 랭킹 매물 (조회 <span id="propCount">0</span>건)</h2>
                    <div style="display: flex; gap: 10px;">
                        <button id="rescoreBtn" onclick="triggerRescore()" style="background: rgba(16, 185, 129, 0.15); border: 1px solid var(--accent-green); color: var(--accent-green); padding: 8px 18px; border-radius: 6px; cursor: pointer; font-weight: 700;">⚡ 퀀트 점수 즉시 재계산 (API 미호출)</button>
                        <button onclick="loadProperties()" style="background: transparent; border: 1px solid var(--border); color: var(--text-main); padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: 600;">화면 새로고침 ↻</button>
                    </div>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th>순위</th>
                            <th>지역명</th>
                            <th>단지명 (동 / 층)</th>
                            <th>평형</th>
                            <th>전고점 (최고실거래가)</th>
                            <th>현재 매매가</th>
                            <th>하락 추세 / 하락률</th>
                            <th>종합 퀀트 점수</th>
                            <th>실매물 확인</th>
                        </tr>
                    </thead>
                    <tbody id="propTableBody">
                        <tr><td colspan="9" style="text-align:center; padding: 40px; color: var(--text-muted);">데이터를 불러오는 중입니다...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 2. 지역 설정 및 크롤링 패널 -->
        <div id="regions" class="panel">
            <div class="card">
                <h2 style="font-size: 18px; color: #fff; margin-bottom: 8px;">관심 지역 및 크롤링 타겟 선택</h2>
                <p style="color: var(--text-muted); font-size: 14px;">
                    아래 지역에서 스크리닝을 원하는 법정동을 선택하세요. '선택 지역 저장 후 실시간 크롤링 시작' 버튼을 누르면 즉시 네이버 부동산 매물을 갱신합니다.
                </p>

                <div class="regions-grid" id="regionCheckboxes">
                    <!-- JS DOM 생성 -->
                </div>

                <div class="action-bar">
                    <span style="color: var(--text-muted); font-size: 13px;">체크된 지역의 아파트 단지만 DB에 최신 매물로 수집·분석됩니다.</span>
                    <button id="crawlBtn" class="btn-primary" onclick="saveAndCrawl()">선택 지역 저장 후 실시간 크롤링 시작 →</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentRegions = [];
        let allProperties = [];
        let pyeongFilter = 'all';
        let maxPriceFilter = 600000; // 기본 60.0억(600000만)

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
            maxPriceFilter = val * 100; // 100단위 (10000만원=1억 기준)
            document.getElementById('priceSliderLabel').textContent = `${(val / 100).toFixed(1)}억 이하`;
            renderTable();
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
                tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding: 40px; color: var(--text-muted);">조건에 일치하는 매물이 없습니다. 상단의 평형 또는 금액 조회 조건을 변경해 주세요.</td></tr>';
                return;
            }

            tbody.innerHTML = filtered.map((item, idx) => {
                const badgeClass = item.score >= 80 ? 'badge-high' : (item.score >= 65 ? 'badge-mid' : 'badge-low');
                const priceStr = item.asking_price >= 10000 ? `${(item.asking_price/10000).toFixed(2)}억` : `${item.asking_price.toLocaleString()}만`;
                const highStr = item.high_price >= 10000 ? `${(item.high_price/10000).toFixed(2)}억` : `${Math.round(item.high_price).toLocaleString()}만`;
                const dropAmt = item.high_price - item.asking_price;
                const dropAmtStr = dropAmt >= 10000 ? `-${(dropAmt/10000).toFixed(2)}억` : `-${Math.round(dropAmt).toLocaleString()}만`;
                const dropRatePct = item.drop_rate < 1.0 ? (item.drop_rate * 100).toFixed(1) : item.drop_rate.toFixed(1);
                const naverUrl = item.complex_code ? `https://new.land.naver.com/complexes/${item.complex_code}` : 'https://new.land.naver.com/';

                return `
                <tr>
                    <td style="font-weight:700; color:var(--text-muted);">#${idx+1}</td>
                    <td><span style="color:#60a5fa; font-weight:600;">${item.region_name || '서울 주요지역'}</span></td>
                    <td><strong style="color:#fff;">${item.complex_name}</strong> <span style="color:var(--text-muted);">(${item.building_dong} / ${item.floor})</span></td>
                    <td style="font-weight:600; color:#fff;">${item.area_pyeong}평</td>
                    <td style="color:var(--text-muted); text-decoration: line-through;">${highStr}</td>
                    <td style="font-weight:700; color:#fff; font-size:15px;">${priceStr}</td>
                    <td>
                        <span style="color:#f87171; font-weight:600;">${dropAmtStr}</span>
                        <span style="color:var(--text-muted); font-size:12px;">(-${dropRatePct}%) 📉</span>
                    </td>
                    <td><span class="badge ${badgeClass}">${item.score.toFixed(1)}점</span></td>
                    <td><a href="${naverUrl}" target="_blank" class="naver-link">네이버 부동산 →</a></td>
                </tr>
                `;
            }).join('');
        }

        async function loadProperties() {
            try {
                const res = await fetch('/api/properties');
                const data = await res.json();
                allProperties = data.properties;
                document.getElementById('lastUpdated').textContent = data.last_updated;
                renderTable();
            } catch (err) {
                console.error(err);
            }
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
    uvicorn.run("pc.web_app:app", host="127.0.0.1", port=8000, reload=False)
