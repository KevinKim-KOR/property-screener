import json
import os
from pathlib import Path
from datetime import datetime

def generate_report():
    """
    ml_results.json 결과를 분석하여 로컬 PC에서 즉시 확인할 수 있는 
    시각적 HTML 대시보드(report.html)를 생성합니다.
    """
    root_dir = Path(__file__).resolve().parent.parent.parent
    json_path = root_dir / "ml_results.json"
    output_html_path = Path(__file__).resolve().parent / "report.html"

    if not json_path.exists():
        print(f"[ReportGenerator] ml_results.json 파일이 없습니다. 경로: {json_path}")
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ReportGenerator] JSON 파일 파싱 오류: {e}")
        return

    generated_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_count = len(data)
    top_score = data[0].get('quant_score', 0) if total_count > 0 else 0
    top_complex = data[0].get('complex_name', '-') if total_count > 0 else '-'

    rows_html = ""
    for idx, item in enumerate(data, 1):
        complex_code = item.get('complex_code', '')
        name = item.get('complex_name', 'Unknown')
        dong = item.get('building_dong', '-')
        floor = item.get('floor', '-')
        asking_price = item.get('asking_price', 0)
        price_str = f"{asking_price / 10000:.2f}억" if asking_price >= 10000 else f"{asking_price:,}만"
        score = item.get('quant_score', 0)
        drop_rate = item.get('drop_rate', 0.0) * 100
        location_score = item.get('location_score', 0.0)

        badge_class = "badge-high" if score >= 80 else ("badge-mid" if score >= 65 else "badge-low")
        naver_url = f"https://new.land.naver.com/complexes/{complex_code}" if complex_code else "https://new.land.naver.com/"

        rows_html += f"""
        <tr>
            <td class="rank-col">#{idx}</td>
            <td><strong class="complex-name">{name}</strong> <span class="sub-info">({ dong } / { floor })</span></td>
            <td><span class="price-text">{price_str}</span></td>
            <td><span class="location-score">+{location_score}점</span></td>
            <td>{drop_rate:.1f}%</td>
            <td><span class="score-badge {badge_class}">{score:.1f}점</span></td>
            <td>
                <a href="{naver_url}" target="_blank" class="naver-btn">네이버 부동산 →</a>
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
        .location-score {{
            color: #3fb950;
            font-weight: 600;
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
                <p>PC ML 스코어링 및 카카오 로컬 API 입지 가점 분석 결과 보고서</p>
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
                <div class="label">최고 종합 퀀트 점수</div>
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
                        <th>지하철역 입지 가점</th>
                        <th>전고점 대비 하락률</th>
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
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"[ReportGenerator] 로컬 대시보드가 생성되었습니다 -> {output_html_path}")
    print(f"               (탐색기나 웹 브라우저에서 report.html을 열면 그래픽으로 바로 확인 가능합니다)")

if __name__ == "__main__":
    generate_report()
