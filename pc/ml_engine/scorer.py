import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from common.database import get_db_connection
from pc.basic_crawler.location_crawler import LocationCrawler

class MLEngine:
    @staticmethod
    def run():
        print("[MLEngine] Starting analysis...")
        crawler = LocationCrawler()
        results = {}
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM properties")
            rows = cursor.fetchall()
            
            for row in rows:
                prop_id = row["property_id"]
                price = row["asking_price"]
                area = row["area_pyeong"]
                drop_rate = row["drop_rate"]
                name = row["complex_name"]
                
                # 위치 정보 획득 (현재 반포동 지역으로 하드코딩 테스트)
                location_info = crawler.get_complex_info("서초구 반포동", name)
                
                # 단순 스코어링 로직 (하락률 기반)
                price_per_pyeong = price / area if area > 0 else 0
                base_score = 50.0
                drop_rate_score = drop_rate * 2  # 15% 하락이면 +30점
                
                # 교통 편의성에 따른 가점 부여 로직
                location_score = 0
                if "도보 약" in location_info:
                    try:
                        mins = int(location_info.split("도보 약 ")[1].split("분")[0])
                        if mins <= 5:
                            location_score = 15.0
                        elif mins <= 10:
                            location_score = 10.0
                        elif mins <= 15:
                            location_score = 5.0
                    except:
                        pass
                
                total_score = min(100.0, base_score + drop_rate_score + location_score)
                
                prompt = (
                    f"현재 반포동 {name} {area}평 매물이 {price}만원에 등록되었습니다.\n"
                    f"- 고점 대비 하락률: {drop_rate}%\n"
                    f"- 평당가: 약 {int(price_per_pyeong)}만원\n"
                    f"- 입지/교통: {location_info}\n\n"
                    f"이 매물의 현재 투자가치와 향후 전망을 부동산 전문가 입장에서 분석해주세요."
                )
                
                results[prop_id] = {
                    "ml_score": round(total_score, 2),
                    "ai_prompt": prompt
                }
                print(f"[MLEngine] Scored {prop_id} ({name}): {total_score} pts (Location Bonus: {location_score})")
                
        return results
