# pc/scoring/ui_translator.py
"""
SCORING_V3.1_DESIGN.md §16 UI 명세 전면 재작성:
- §16.2 표기 변환표
- §16.3 결정론적 문장 생성 규칙 (가격 해석, 강점 1줄, 주의 1줄)
- §16.6 제외 매물 한글 사유 변환
"""
from typing import Dict, Optional

def translate_area_type(area_type: str) -> str:
    """§16.2 표기 변환표: 내부 5㎡ area_type -> 한글 통칭 표기 (25평 / 34평 / 44평+ / 실제 버킷 전용 면적)"""
    s = str(area_type or "").upper()
    mapping = {
        "A40": "18평 / 40㎡",
        "A50_55": "25평 / 53㎡",
        "A55_60": "25평 / 58㎡",
        "A59": "25평 / 59㎡",
        "A60_65": "25평 / 60㎡",
        "A65_70": "25평 / 67㎡",
        "A70_75": "34평 / 74㎡",
        "A75_80": "34평 / 77㎡",
        "A80_85": "34평 / 84㎡",
        "A84": "34평 / 84㎡",
        "A85_90": "34평 / 85㎡",
        "A90_95": "34평 / 92㎡",
        "A95_100": "34평 / 96㎡",
        "A100_105": "44평 / 102㎡",
        "A105_110": "44평 / 107㎡",
        "A110_115": "44평 / 114㎡",
        "A114": "44평 / 114㎡",
        "A115_120": "44평 / 118㎡",
        "A120_125": "44평 / 123㎡",
        "A125_130": "44평 / 127㎡",
        "A130_135": "44평 / 134㎡",
        "A135P": "44평 / 135㎡+",
    }
    if s in mapping:
        return mapping[s]
    if s.startswith("A") and "_" in s:
        parts = s[1:].split("_")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            low = int(parts[0])
            high = int(parts[1])
            rep_m2 = (low + high) // 2
            if low < 70:
                py_label = "25평"
            elif low < 100:
                py_label = "34평"
            else:
                py_label = "44평"
            return f"{py_label} / {rep_m2}㎡"
    return "34평 / 84㎡"


def translate_price_interpretation(asking_price: float, median_price_3m: float) -> str:
    """§16.3 가격 해석 (만원 단위 가격 입력 기준, 1억=10,000만원)"""
    if median_price_3m <= 0:
        return "최근 실거래 데이터가 부족합니다"
    if asking_price <= 0:
        return "실거래 중위가격 기준 평가 매물입니다"
    gap = median_price_3m - asking_price
    gap_pct = gap / float(median_price_3m)

    gap_eok = abs(gap) / 10000.0
    if gap_pct >= 0.03:
        return f"최근 실거래보다 {gap_eok:.1f}억 낮은 호가입니다"
    elif gap_pct <= -0.03:
        return f"최근 실거래보다 {gap_eok:.1f}억 높은 호가입니다"
    else:
        return "최근 실거래와 비슷한 호가입니다"


def generate_strength_sentence(item: Dict) -> Optional[str]:
    """
    §16.3 강점 (최대 1줄, 우선순위 순 첫 번째)
    """
    excess_drop = float(item.get("excess_drop_rate", 0.0) or 0.0)
    volume_ratio = float(item.get("volume_ratio", 0.0) or 0.0)
    jeonse_ratio = float(item.get("jeonse_ratio", 0.0) or 0.0)
    subway_dist = float(item.get("subway_dist_m", 9999.0) or 9999.0)
    subway_name = str(item.get("subway_name", "역") or "역")

    # excess_drop_rate는 소수점 (예: 0.05 -> +5%p 더 떨어짐)
    x_pct = round(excess_drop * 100.0, 1)

    # 1. excess_drop_rate >= +0.05 AND volume_ratio > 1.0
    if excess_drop >= 0.05 and volume_ratio > 1.0:
        return f"강남권 평균보다 {x_pct}%p 더 떨어졌는데, 거래량은 회복 중입니다"
    # 2. excess_drop_rate >= +0.05
    if excess_drop >= 0.05:
        return f"강남권 평균보다 {x_pct}%p 더 떨어졌습니다"
    # 3. jeonse_ratio 상위 20% (예: 0.55 이상)
    if jeonse_ratio >= 0.55:
        return "전세가율이 높아 실수요 지지가 탄탄합니다"
    # 4. volume_ratio > 1.3
    if volume_ratio > 1.3:
        return "최근 거래가 평소보다 활발합니다"
    # 5. subway_dist_m <= 400
    if subway_dist <= 400.0:
        walk_min = max(1, int(subway_dist / 67.0))
        return f"{subway_name} 도보 {walk_min}분 거리입니다"
    # 6. 해당 없음
    return None


def generate_caution_sentence(item: Dict) -> Optional[str]:
    """
    §16.3 주의 (최대 1줄, 우선순위 순 첫 번째)
    """
    sample_count = int(item.get("sample_count_12m", 10) or 10)
    jeonse_ratio = float(item.get("jeonse_ratio", 0.50) or 0.50)
    excess_drop = float(item.get("excess_drop_rate", 0.0) or 0.0)
    volume_ratio = float(item.get("volume_ratio", 1.0) or 1.0)
    coverage_ratio = float(item.get("coverage_ratio", 1.0) or 1.0)
    age_years = int(item.get("age_years", 10) or 10)

    # 1. sample_count_12m < 5
    if sample_count < 5:
        return "거래가 드물어 기준가 신뢰도가 낮습니다"
    # 2. jeonse_ratio 하위 20% (예: 0.45 미만)
    if jeonse_ratio < 0.45:
        return "전세가율이 낮아 하방 지지가 약합니다 (강남권 하위 20%)"
    # 3. excess_drop_rate <= -0.05
    if excess_drop <= -0.05:
        return "강남권 평균보다 덜 떨어져 가격 매력은 낮습니다"
    # 4. volume_ratio < 0.6
    if volume_ratio < 0.6:
        return "거래가 뜸해져 매도까지 오래 걸릴 수 있습니다"
    # 5. coverage_ratio < 0.60
    if coverage_ratio < 0.60:
        return "일부 지표를 산출하지 못해 점수 신뢰도가 낮습니다"
    # 6. age_years in [15, 28] -> 15~28년 사이
    if 15 <= age_years <= 28:
        return "재건축 기대는 이르고 신축 프리미엄은 지난 연식대입니다"
    # 7. 해당 없음
    return None


def translate_exclusion_reason(reason_code: str) -> str:
    """
    §16.6 제외 매물 한글 사유 변환
    """
    mapping = {
        "INSUFFICIENT_TRADES": "거래가 드물어 가격을 판단하기 어렵습니다",
        "G1_LOW_VOLUME": "거래가 드물어 가격을 판단하기 어렵습니다",
        "HIGH_SPECIAL_DEAL_RATIO": "직거래·취소 거래가 많아 가격을 믿기 어렵습니다",
        "G2_HIGH_SPECIAL_DEALS": "직거래·취소 거래가 많아 가격을 믿기 어렵습니다",
        "G3_NO_PEAK_PRICE": "과거 거래가 부족해 비교 기준을 잡지 못했습니다",
        "HIGH_UNREGISTERED_RATIO": "등기가 완료되지 않은 거래가 많습니다",
        "KEY_MATCH_FAILED": "실거래 데이터와 연결하지 못했습니다",
        "G0_LAND_LEASE": "토지임대부 아파트는 소유 구조가 달라 일반 아파트와 비교할 수 없습니다",
        "G3_INVERTED_PRICE": "가격 자료가 앞뒤가 맞지 않습니다",
        "PRICE_SANITY_FAILED": "가격 정합성 검증을 통과하지 못했습니다",
        "V1_PEAK_BELOW_MEDIAN": "가격 정합성 검증을 통과하지 못했습니다 (기준가 > 전고점)",
        "V2_PRICE_RATIO_OUT_OF_BOUNDS": "가격 정합성 검증을 통과하지 못했습니다 (호가/기준가 비율 이상)",
        "V3_MIXED_AREA_TYPES": "가격 정합성 검증을 통과하지 못했습니다 (혼합 평형)",
        "V4_PPP_OUT_OF_BOUNDS": "가격 정합성 검증을 통과하지 못했습니다 (평단가 이상치)",
        "G4_PRICE_OUTLIER": "가격 정합성 검증을 통과하지 못했습니다 (평단가 이상치)",
        "G6_LOW_COVERAGE": "일부 필수 지표가 결측되어 스코어를 산출할 수 없습니다",
    }
    return mapping.get(str(reason_code or "").strip(), f"데이터 품질 검증을 통과하지 못했습니다 ({reason_code})")
