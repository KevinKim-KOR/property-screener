import json
import shutil
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from common.database import get_db_connection
from pc.basic_crawler.location_crawler import LocationCrawler

# 정상 결과를 빈 결과/급감 결과로 덮어쓰는 조용한 데이터 손실을 막기 위한 가드.
# 실제로 342건짜리 결과가 빈 DB 스코어링 때문에 0건/12건으로 두 번 덮인 적이 있다.
SHRINK_ABORT_RATIO = 0.5   # 직전 대비 이 비율 미만으로 줄면 중단


class EmptyScoringResultError(RuntimeError):
    """적격 매물이 0건이라 결과 파일을 쓰지 않고 중단한 경우."""


class ScoringResultShrinkError(RuntimeError):
    """직전 결과 대비 급감하여 결과 파일을 쓰지 않고 중단한 경우."""


def _load_previous_count(out_file: Path) -> int:
    """기존 ml_results.json 의 항목 수. 없거나 읽을 수 없으면 0."""
    if not out_file.exists():
        return 0
    try:
        with open(out_file, "r", encoding="utf-8") as f:
            prev = json.load(f)
        return len(prev) if hasattr(prev, "__len__") else 0
    except Exception as e:
        # 기존 파일이 깨져 있으면 비교를 포기한다(0으로 취급).
        # 쓰기 자체를 막지는 않는다 — 깨진 파일을 정상 결과로 대체하는 것은 손실이 아니다.
        print(f"[MLEngine] 기존 결과 파일을 읽을 수 없어 감소 검사를 건너뜁니다: {e}")
        return 0


def save_ml_results(results, out_file: Path = None) -> Path:
    """
    reports/ml_results.json 을 안전하게 갱신한다.

    다음 경우에는 파일을 쓰지 않고 예외를 던진다.
      - 적격 매물 0건 (EmptyScoringResultError)
      - 직전 결과 대비 SHRINK_ABORT_RATIO 미만으로 급감 (ScoringResultShrinkError)

    정상적으로 쓰는 경우, 덮어쓰기 직전의 파일을 ml_results.prev.json 으로 백업한다.
    """
    if out_file is None:
        out_file = Path(__file__).resolve().parent.parent.parent / "reports" / "ml_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    new_count = len(results)
    if new_count == 0:
        raise EmptyScoringResultError(
            "적격 매물이 0건입니다. 기존 결과를 빈 결과로 덮어쓰지 않고 중단합니다. "
            f"(대상 파일: {out_file}) DB에 매물이 적재되어 있는지 확인하세요."
        )

    prev_count = _load_previous_count(out_file)
    # "50% 이상 줄어들면 중단" 이므로 정확히 절반으로 준 경우도 차단한다.
    if prev_count > 0 and new_count <= prev_count * SHRINK_ABORT_RATIO:
        raise ScoringResultShrinkError(
            f"결과 건수가 직전 대비 급감했습니다: {prev_count}건 -> {new_count}건 "
            f"(기준: 직전의 {SHRINK_ABORT_RATIO:.0%} 이하로 줄면 중단). "
            f"덮어쓰지 않았습니다. 의도한 축소라면 {out_file.name} 을 직접 정리한 뒤 다시 실행하세요."
        )

    # 덮어쓰기 직전 백업
    if out_file.exists():
        backup = out_file.with_name("ml_results.prev.json")
        shutil.copy2(out_file, backup)
        print(f"[MLEngine] 이전 결과를 {backup.name} 으로 백업했습니다 ({prev_count}건).")

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"[MLEngine] Successfully saved {new_count} scored items to {out_file}")
    return out_file

class MLEngine:
    @staticmethod
    def run():
        print("[MLEngine] Starting analysis...")
        crawler = LocationCrawler()
        results = {}
        missing_location_count = 0
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
                # 도보시간을 못 구하면 기본 10점을 주지 않고 '결측'으로 둔다.
                # 과거에는 bare except 로 파싱 실패를 삼키고 조용히 10점을 부여해,
                # 입지 정보가 없는 매물과 도보 15분 매물이 같은 점수를 받았다.
                # (bare except 는 KeyboardInterrupt/SystemExit 까지 잡는 문제도 있었다.)
                location_score = None
                if "도보 약" in location_info:
                    try:
                        mins = int(location_info.split("도보 약 ")[1].split("분")[0])
                        if mins <= 5:
                            location_score = 20.0
                        elif mins <= 10:
                            location_score = 15.0
                        else:
                            location_score = 10.0
                    except (ValueError, TypeError, IndexError) as e:
                        print(f"[MLEngine] 도보시간 파싱 실패 -> 입지 결측 처리 "
                              f"({prop_id} {name}): {location_info!r} ({e})")
                
                # 4. Scale/Liquidity 팩터 (15점 만점): 단지 규모 및 거래 활성도 유동성
                # 자이, 래미안, 힐스테이트, 아크로, 푸르지오 등 대단지 브랜드 및 규모 프리미엄
                brand_keywords = ["자이", "래미안", "힐스테이트", "아크로", "푸르지오", "아이파크", "롯데캐슬", "더샵", "리센츠", "엘스", "트리지움"]
                scale_score = 15.0 if any(b in name for b in brand_keywords) else 12.0
                
                # 5. Floor 팩터 (10점 만점): 로열층/고층/중층 프리미엄
                floor_score = 10.0 if any(k in floor_str for k in ["고/", "로열/", "중/"]) else 7.0
                
                # 결측 팩터는 제외하고 남은 팩터의 가중치를 재정규화한다
                # (SCORING_DESIGN §9.4 블록 점수 결측 처리와 같은 방식).
                # 0이나 평균으로 대체하지 않으며, 만점은 항상 100 으로 유지해
                # 같은 표 안에서 점수를 비교할 수 있게 한다.
                factors = {
                    "valuation": val_score,
                    "momentum": mom_score,
                    "location": location_score,   # None 이면 결측
                    "scale": scale_score,
                    "floor": floor_score,
                }
                factor_max = {
                    "valuation": 30.0, "momentum": 25.0, "location": 20.0,
                    "scale": 15.0, "floor": 10.0,
                }
                available = {k: v for k, v in factors.items() if v is not None}
                # 남은 팩터의 만점 합으로 나눠 100점 만점으로 재정규화
                avail_max = sum(factor_max[k] for k in available)
                total_score = round(min(100.0, sum(available.values()) / avail_max * 100.0), 1)

                location_missing = location_score is None
                missing_factors = [k for k in factors if factors[k] is None]
                coverage = len(available) / len(factors)
                loc_disp = "결측" if location_missing else f"{location_score:.1f}"
                
                prompt = (
                    f"[{region_name}] {name} {area}평 매물이 {price}만원에 등록되었습니다.\n"
                    f"- 퀀트 스코어: {total_score}점 / 100점 만점"
                    f"{' (입지 결측 — 나머지 팩터로 재정규화)' if location_missing else ''}\n"
                    f"  (Val:{val_score:.1f} / Mom:{mom_score:.1f} / Loc:{loc_disp} / Scale:{scale_score:.1f} / Floor:{floor_score:.1f})\n"
                    f"- 고점 대비 변화: -{drop_rate*100:.1f}% 하락\n"
                    f"- 최근 시세 추세(1M/3M/6M): {c1m:+g}% / {c3m:+g}% / {c6m:+g}%\n"
                    f"- 입지/교통: {location_info}\n\n"
                    f"이 매물의 현재 투자가치와 향후 전망을 부동산 전문가 입장에서 분석해주세요."
                )
                
                results[prop_id] = {
                    "ml_score": total_score,          # 항상 100점 만점 기준
                    "location_missing": location_missing,
                    "missing_factors": missing_factors,
                    "coverage": round(coverage, 3),   # 사용된 팩터 비율 (화면 표시용)
                    "ai_prompt": prompt
                }
                if location_missing:
                    missing_location_count += 1
                print(f"[MLEngine] Scored {prop_id} ({name}): {total_score}/100 pts "
                      f"(Val:{val_score:.1f}|Mom:{mom_score:.1f}|Loc:{loc_disp}|Scale:{scale_score:.1f}|Floor:{floor_score:.1f})")
                
        if missing_location_count:
            print(f"[MLEngine] 입지(도보시간) 결측: {len(results)}건 중 {missing_location_count}건 "
                  f"— 남은 팩터를 재정규화해 100점 만점으로 산출했습니다 "
                  f"(결과의 location_missing / coverage 필드로 구분 가능).")

        # reports/ml_results.json 에 즉시 자동 저장.
        # 빈 결과/급감 결과는 쓰지 않고 예외를 던진다(조용한 데이터 손실 방지).
        # 실패를 삼키지 않는다 — 호출자(웹앱)가 화면에 실패로 표시한다.
        save_ml_results(results)

        return results
