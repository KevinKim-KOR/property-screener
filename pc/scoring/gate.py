# pc/scoring/gate.py
"""
G1~G7 데이터 품질 게이트 및 V1~V6 가격 정합성 검증 모듈
(SCORING_V3.1_DESIGN.md §11, §11.5, P1-AC11, P1-AC12d).
"""
import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)

def check_quality_gates(item: Dict, coverage_ratio: float) -> Tuple[str, Optional[str]]:
    """
    단지 x 평형 데이터(item)와 가중치 커버리지(coverage_ratio)를 검사하여
    (gate_status, gate_reason)을 반환한다.
    gate_status: 'PASSED' 또는 'EXCLUDED'
    """
    # G5: 단지 매칭 실패
    if not item.get("complex_code"):
        return "EXCLUDED", "G5_UNMATCHED_COMPLEX"

    # G0: 토지임대부 단지 제외
    if "토지임대부" in str(item.get("complex_name", "")):
        return "EXCLUDED", "G0_LAND_LEASE"

    # G1: 최근 12개월 3건 미만 또는 24개월 8건 미만 (v4.2 §4 제외 규칙)
    sample_n = item.get("sample_count_12m", 0)
    sample_n_24m = item.get("sample_count_24m", 0)
    if sample_n < 3 or sample_n_24m < 8:
        return "EXCLUDED", "G1_LOW_VOLUME"

    # G2: 직거래·해제 비중 30% 초과 (§4 제외 규칙)
    special_ratio = item.get("special_deal_ratio", 0.0)
    if special_ratio > 0.30:
        return "EXCLUDED", "G2_HIGH_SPECIAL_DEALS"

    # G3: 전고점을 못 구함 또는 실거래가 없음 (§4 제외 규칙)
    if item.get("peak_price_raw", 0.0) <= 0 or item.get("median_price_3m", 0.0) <= 0:
        return "EXCLUDED", "G3_NO_PEAK_PRICE"

    # G3_INVERTED_PRICE: 최근 거래가가 전고점 × 1.10보다 큰 경우 (가격 자료가 앞뒤가 맞지 않음)
    med_3m = item.get("median_price_3m", 0.0) or 0.0
    peak_adj = item.get("peak_price_adj", 0.0) or item.get("peak_price_raw", 0.0) or 0.0
    if med_3m > (peak_adj * 1.10) and peak_adj > 0:
        return "EXCLUDED", "G3_INVERTED_PRICE"

    # G4: 평단가 이상치 (지역 평단가의 20% 미만 또는 500% 초과 시 이상치)
    ppp = item.get("price_per_pyeong", 0.0)
    if ppp <= 1000.0 or ppp > 30000.0:
        return "EXCLUDED", "G4_PRICE_OUTLIER"

    # G6: 커버리지 미달 (< 0.35)
    if coverage_ratio < 0.35:
        return "EXCLUDED", "G6_LOW_COVERAGE"

    return "PASSED", None


def check_l1_price_sanity_gates(
    stat_item: Dict,
    peer_p1: float = 1000.0,
    peer_p99: float = 35000.0
) -> Tuple[str, Optional[str]]:
    """
    L1 (단지 x 평형) 시세 통계의 가격 정합성 게이트(V1, V3, V4, V6) 검증
    반환: (status, reason)
    """
    med_3m = stat_item.get("median_price_3m", 0.0) or 0.0
    peak_adj = stat_item.get("peak_price_adj", 0.0) or 0.0
    ppp = stat_item.get("price_per_pyeong", 0.0) or 0.0

    # V6 check for base statistics
    if med_3m <= 0 or peak_adj <= 0:
        return "EXCLUDED", "V6_INVALID_PRICE_ZERO_OR_NULL"

    # V1: 기준가 > 전고점
    if med_3m > peak_adj:
        return "EXCLUDED", "V1_PEAK_BELOW_MEDIAN"

    # V3: 기준가 산출에 쓰인 거래의 area_type이 단일하지 않음
    if stat_item.get("mixed_area_types", False):
        return "EXCLUDED", "V3_MIXED_AREA_TYPES"

    # V4: 평당가가 비교군 [P1, P99] 밖
    if ppp < peer_p1 or ppp > peer_p99:
        return "EXCLUDED", "V4_PPP_OUT_OF_BOUNDS"

    return "PASSED", None


def check_l2_price_sanity_gates(
    prop_item: Dict,
    median_price_3m: float,
    peak_price: float,
    stat_meta: Optional[Dict] = None
) -> Tuple[bool, Optional[str]]:
    """
    L2 매물 단위 가격 정합성 게이트(V2, V6) 검증
    반환: (is_valid: bool, violation_reason: Optional[str])
    """
    asking_price = prop_item.get("asking_price", 0.0) or 0.0
    if asking_price <= 0 or median_price_3m <= 0 or peak_price <= 0:
        return False, "V6_INVALID_PRICE_ZERO_OR_NULL"

    ratio = asking_price / float(median_price_3m)
    if ratio < 0.6 or ratio > 1.8:
        # SCORING_V3.1_DESIGN.md §11.5 필수 진단 절차 로그 출력
        cc = prop_item.get("complex_code", "UNKNOWN")
        at = prop_item.get("area_type", "UNKNOWN")
        ex_area = prop_item.get("exclusive_area", "None")
        match_method = prop_item.get("match_method", "UNKNOWN")
        confidence = prop_item.get("confidence", "UNKNOWN")

        stat_meta = stat_meta or {}
        trades_count = stat_meta.get("sample_count_12m", "UNKNOWN")
        min_ex = stat_meta.get("min_ex_area", "UNKNOWN")
        max_ex = stat_meta.get("max_ex_area", "UNKNOWN")

        logger.warning(
            f"[V2 VIOLATION] complex_code={cc} area_type={at} ratio={ratio:.2f}\n"
            f"  호가측  : exclusive_area={ex_area}, area_type={at}, source=naver\n"
            f"  기준가측: area_type={at}, 산출 거래 수={trades_count}, exclusive_area 범위=[{min_ex}, {max_ex}]\n"
            f"  매칭    : match_method={match_method}, confidence={confidence}"
        )
        return False, "V2_PRICE_RATIO_OUT_OF_BOUNDS"

    return True, None
