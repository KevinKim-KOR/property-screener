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
                drop_rate = row["drop_rate"] or 0.0
                name = row["complex_name"]
                region_name = row["region_name"] or "서울 주요지역"
                floor_str = row["floor"] or ""
                c1m = row["change_1m"] or 0.0
                c3m = row["change_3m"] or 0.0
                c6m = row["change_6m"] or 0.0
                
                # 위치 정보 획득
                location_info = crawler.get_complex_info(region_name, name)
                
                # ==========================================
                # [5-Factor Advanced Real Estate Quant Model]
                # ==========================================
                # 1. Valuation 팩터 (30점 만점): 고점 대비 하락 매력도 + 평당가 합리성
                val_score = min(30.0, max(10.0, (drop_rate * 100.0) * 1.5))
                
                # 2. Momentum 팩터 (25점 만점): 최근 1m/3m/6m 추세(회복 및 상승 탄력성)
                # 시세 변동 평균이 양수거나 안정적이면 가점
                trend_avg = (c1m + c3m + c6m) / 3.0
                mom_score = min(25.0, max(5.0, 15.0 + (trend_avg * 2.5)))
                
                # 3. Location 팩터 (20점 만점): 지하철역 도보 접근성
                location_score = 10.0
                if "도보 약" in location_info:
                    try:
                        mins = int(location_info.split("도보 약 ")[1].split("분")[0])
                        if mins <= 5:
                            location_score = 20.0
                        elif mins <= 10:
                            location_score = 15.0
                        elif mins <= 15:
                            location_score = 10.0
                    except:
                        pass
                
                # 4. Scale/Liquidity 팩터 (15점 만점): 단지 규모 및 거래 활성도 유동성
                # 자이, 래미안, 힐스테이트, 아크로, 푸르지오 등 대단지 브랜드 및 규모 프리미엄
                brand_keywords = ["자이", "래미안", "힐스테이트", "아크로", "푸르지오", "아이파크", "롯데캐슬", "더샵", "리센츠", "엘스", "트리지움"]
                scale_score = 15.0 if any(b in name for b in brand_keywords) else 12.0
                
                # 5. Floor 팩터 (10점 만점): 로열층/고층/중층 프리미엄
                floor_score = 10.0 if any(k in floor_str for k in ["고/", "로열/", "중/"]) else 7.0
                
                total_score = round(min(100.0, val_score + mom_score + location_score + scale_score + floor_score), 1)
                
                prompt = (
                    f"[{region_name}] {name} {area}평 매물이 {price}만원에 등록되었습니다.\n"
                    f"- 퀀트 스코어: {total_score}점 (Val:{val_score:.1f} / Mom:{mom_score:.1f} / Loc:{location_score:.1f} / Scale:{scale_score:.1f} / Floor:{floor_score:.1f})\n"
                    f"- 고점 대비 변화: -{drop_rate*100:.1f}% 하락\n"
                    f"- 최근 시세 추세(1M/3M/6M): {c1m:+g}% / {c3m:+g}% / {c6m:+g}%\n"
                    f"- 입지/교통: {location_info}\n\n"
                    f"이 매물의 현재 투자가치와 향후 전망을 부동산 전문가 입장에서 분석해주세요."
                )
                
                results[prop_id] = {
                    "ml_score": total_score,
                    "ai_prompt": prompt
                }
                print(f"[MLEngine] Scored {prop_id} ({name}): {total_score} pts (Val:{val_score:.1f}|Mom:{mom_score:.1f}|Loc:{location_score:.1f}|Scale:{scale_score:.1f}|Floor:{floor_score:.1f})")
                
        # ml_results.json에 즉시 자동 저장
        try:
            import json
            out_file = Path(__file__).resolve().parent.parent.parent / "ml_results.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"[MLEngine] Successfully saved {len(results)} scored items to {out_file}")
        except Exception as e:
            print(f"[MLEngine] Warning: could not write ml_results.json: {e}")

        return results
