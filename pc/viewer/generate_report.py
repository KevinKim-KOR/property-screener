import json
from urllib.parse import quote
import re
import sqlite3
from pathlib import Path
from datetime import datetime

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from common.config_loader import Config

def build_naver_link(complex_code, complex_name, region_name=""):
    """
    네이버 부동산 링크를 만든다.

    complex_code 가 숫자면 네이버 단지 번호이므로 단지 페이지로 바로 보낸다.
    숫자가 아니면 국토부 실거래에서 만든 해시(MOLIT_11680_...)이며 네이버에서
    통하지 않는다. 그 값을 URL 에 붙이면 네이버가 조용히 버리고 기본 지도를
    띄워, 어느 단지를 눌러도 같은 곳이 열린다. 그래서 검색으로 보낸다.
    (네이버 단지 번호를 제대로 붙이려면 크롤러 실연동 필요 — 설계서 §9 항목 17~19)
    """
    code = str(complex_code or "")
    if code.isdigit() and code != "0":
        return f"https://new.land.naver.com/complexes/{code}"

    name = re.sub(r"\([^)]*\)", " ", str(complex_name or ""))
    name = re.sub(r"[^\w가-힣\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return "https://new.land.naver.com/"
    query = f"{str(region_name or '').strip()} {name}".strip()
    return "https://new.land.naver.com/search?sk=" + quote(query)


def generate_report():
    """
    screener.db (properties 테이블)의 단지 매물 메타정보와
    ml_results.json의 퀀트 스코어를 조인하여 시각적 HTML 대시보드(report.html)를 생성합니다.
    """
    root_dir = Path(__file__).resolve().parent.parent.parent
    # 생성물은 코드 폴더(pc/)가 아닌 산출물 전용 디렉토리(reports/)에 둔다.
    reports_dir = root_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    db_path = Path(Config.get_db_path())
    json_path = reports_dir / "ml_results.json"
    output_html_path = reports_dir / "report.html"

    # 1. ml_results.json 로드 (딕셔너리 또는 리스트 형태 모두 호환 처리)
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
            # 리포트 생성기는 부가 기능이므로 본체를 막지 않는다.
            # 다만 조용히 넘어가지 않도록 터미널에 눈에 띄게 출력한다.
            print("!" * 70)
            print(f"[ReportGenerator] 경고: ml_results.json 을 읽지 못했습니다 -> {e}")
            print("  점수 없이 리포트를 생성합니다. reports/report.html 의 퀀트점수는 신뢰할 수 없습니다.")
            print("!" * 70)

    # 2. screener.db 에서 단지 정보 로드
    properties = []
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM properties")
            for row in cursor.fetchall():
                pid = str(row["property_id"])
                # ml_results.json의 점수와 조인 (없으면 기본값)
                score_info = ml_data.get(pid, {})
                score = score_info.get("ml_score", score_info.get("quant_score", 0.0))
                
                properties.append({
                    "property_id": pid,
                    "complex_code": str(row["complex_code"] or ""),
                    "complex_name": str(row["complex_name"] or "Unknown"),
                    "building_dong": str(row["building_dong"] or "-"),
                    "floor": str(row["floor"] or "-"),
                    "asking_price": float(row["asking_price"] or 0),
                    "area_pyeong": float(row["area_pyeong"] or 0),
                    "drop_rate": float(row["drop_rate"] or 0.0),
                    "score": float(score)
                })
            if not properties:
                cursor.execute("SELECT * FROM complexes")
                comp_map = {str(r["complex_code"]): dict(r) for r in cursor.fetchall()}
                cursor.execute("SELECT * FROM market_scores WHERE base_date = (SELECT MAX(base_date) FROM market_scores)")
                for row in cursor.fetchall():
                    cc = str(row["complex_code"] or "")
                    at = str(row["area_type"] or "")
                    comp = comp_map.get(cc, {})
                    min_a = float(comp.get("area_min_m2") or 0.0)
                    max_a = float(comp.get("area_max_m2") or 0.0)
                    avg_pyeong = round((min_a + max_a) / 2.0 / 3.30578, 1) if max_a > 0 else 32.0
                    properties.append({
                        "property_id": f"L1_{cc}_{at}",
                        "complex_code": cc,
                        "complex_name": str(comp.get("complex_name") or "국토부 단지"),
                        "building_dong": "- (단지 전체)",
                        "floor": "- (전체 평균)",
                        "asking_price": 0,
                        "area_pyeong": avg_pyeong,
                        "drop_rate": 0.0,
                        "score": float(row["market_score"] or 0.0)
                    })
            conn.close()
        except Exception as e:
            print("!" * 70)
            print(f"[ReportGenerator] 경고: screener.db 를 조회하지 못했습니다 -> {e}")
            print("  단지 정보가 빠진 채로 리포트가 생성됩니다.")
            print("!" * 70)

    # 만약 DB가 비어있지만 ml_data에 항목이 있다면 ml_data 기준으로 복원
    if not properties and ml_data:
        for pid, val in ml_data.items():
            if isinstance(val, dict):
                properties.append({
                    "property_id": pid,
                    "complex_code": "",
                    "complex_name": str(val.get("complex_name", pid)),
                    "building_dong": str(val.get("building_dong", "-")),
                    "floor": str(val.get("floor", "-")),
                    "asking_price": float(val.get("asking_price", 0)),
                    "area_pyeong": 34.0,
                    "drop_rate": float(val.get("drop_rate", 0.0)),
                    "score": float(val.get("ml_score", val.get("quant_score", 0.0)))
                })

    # 3. 점수 높은 순으로 정렬
    properties.sort(key=lambda x: x["score"], reverse=True)

    generated_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_count = len(properties)
    top_score = properties[0]["score"] if total_count > 0 else 0.0
    top_complex = properties[0]["complex_name"] if total_count > 0 else "-"

    rows_html = ""
    if total_count == 0:
        rows_html = """
        <tr>
            <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 40px;">
                현재 수집되거나 분석된 아파트 매물 데이터가 없습니다. oci/main.py 또는 크롤러를 실행해 데이터를 수집해주세요.
            </td>
        </tr>
        """
    else:
        for idx, item in enumerate(properties, 1):
            complex_code = item["complex_code"]
            name = item["complex_name"]
            dong = item["building_dong"]
            floor = item["floor"]
            asking_price = item["asking_price"]
            price_str = f"{asking_price / 10000:.2f}억" if asking_price >= 10000 else f"{int(asking_price):,}만"
            score = item["score"]
            drop_rate_pct = item["drop_rate"] * 100 if item["drop_rate"] < 1.0 else item["drop_rate"]

            badge_class = "badge-high" if score >= 80 else ("badge-mid" if score >= 65 else "badge-low")
            naver_url = build_naver_link(complex_code, name, item["region_name"] if "region_name" in item.keys() else "")

            rows_html += f"""
            <tr>
                <td class="rank-col">#{idx}</td>
                <td><strong class="complex-name">{name}</strong> <span class="sub-info">({dong} / {floor})</span></td>
                <td><span class="price-text">{price_str}</span></td>
                <td>{item['area_pyeong']}평</td>
                <td>{drop_rate_pct:.1f}%</td>
                <td><span class="score-badge {badge_class}">{score:.1f}점</span></td>
                <td>
                    <a href="{naver_url}" target="_blank" rel="noopener" class="naver-btn">네이버 부동산 →</a>
                </td>
            </tr>
            """

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>부동산 퀀트 스크리너 - PC 분석 대시보드</title>
    <style>
        :root {{
            --bg-color: #0d1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --text-color: #c9d1d9;
            --text-muted: #8b949e;
            --primary-color: #58a6ff;
            --accent-green: #238636;
            --accent-gold: #d29922;
            --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: var(--font-family);
            padding: 40px 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .title h1 {{
            font-size: 28px;
            color: #ffffff;
            font-weight: 700;
        }}
        .title p {{
            color: var(--text-muted);
            font-size: 14px;
            margin-top: 5px;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 20px;
            margin-bottom: 35px;
        }}
        .summary-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }}
        .summary-card .label {{
            font-size: 13px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .summary-card .value {{
            font-size: 28px;
            color: #ffffff;
            font-weight: 700;
            margin-top: 8px;
        }}
        .table-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        th {{
            background: rgba(255, 255, 255, 0.03);
            color: var(--text-muted);
            font-size: 13px;
            font-weight: 600;
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-color);
        }}
        td {{
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-color);
            font-size: 14px;
        }}
        tr:last-child td {{
            border-bottom: none;
        }}
        tr:hover {{
            background: rgba(255, 255, 255, 0.02);
        }}
        .rank-col {{
            font-weight: 700;
            color: var(--text-muted);
            width: 60px;
        }}
        .complex-name {{
            color: #ffffff;
            font-size: 15px;
        }}
        .sub-info {{
            color: var(--text-muted);
            font-size: 13px;
        }}
        .price-text {{
            font-weight: 600;
            color: #ffffff;
        }}
        .score-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 13px;
        }}
        .badge-high {{
            background: rgba(35, 134, 54, 0.2);
            color: #3fb950;
            border: 1px solid #238636;
        }}
        .badge-mid {{
            background: rgba(210, 153, 34, 0.2);
            color: #e3b341;
            border: 1px solid #d29922;
        }}
        .badge-low {{
            background: rgba(139, 148, 158, 0.1);
            color: #8b949e;
            border: 1px solid #30363d;
        }}
        .naver-btn {{
            display: inline-block;
            padding: 6px 14px;
            background: #1f6feb;
            color: #ffffff;
            text-decoration: none;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            transition: background 0.2s;
        }}
        .naver-btn:hover {{
            background: #388bfd;
        }}
        .footer {{
            margin-top: 30px;
            text-align: center;
            color: var(--text-muted);
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">
                <h1>부동산 퀀트 스크리너 대시보드</h1>
                <p>PC ML 스코어링 및 실거래 하락률 분석 결과 보고서</p>
            </div>
            <div>
                <span style="color: var(--text-muted); font-size: 13px;">생성 일시: {generated_time}</span>
            </div>
        </div>

        <div class="summary-grid">
            <div class="summary-card">
                <div class="label">총 분석된 아파트 매물 수</div>
                <div class="value">{total_count}건</div>
            </div>
            <div class="summary-card">
                <div class="label">최고 퀀트 점수</div>
                <div class="value" style="color: #3fb950;">{top_score:.1f}점</div>
            </div>
            <div class="summary-card">
                <div class="label">1위 추천 단지명</div>
                <div class="value" style="font-size: 24px;">{top_complex}</div>
            </div>
        </div>

        <div class="table-card">
            <table>
                <thead>
                    <tr>
                        <th>순위</th>
                        <th>단지명 (동/층)</th>
                        <th>추정 매매가</th>
                        <th>평형</th>
                        <th>고점 대비 하락률</th>
                        <th>종합 퀀트 점수</th>
                        <th>실매물 확인</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>

        <div class="footer">
            PC-OCI 하이브리드 부동산 퀀트 스크리너 (Local Analysis Viewer)
        </div>
    </div>
</body>
</html>
"""
    output_html_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"[ReportGenerator] 로컬 대시보드 생성 성공 -> {output_html_path}")

if __name__ == "__main__":
    generate_report()
