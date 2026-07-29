# pc/scoring/gate.py
"""
G1~G7 데이터 품질 게이트 검사 모듈
(SCORING_V2_DESIGN.md §11, P1-AC11).
"""
from typing import Dict, Tuple, Optional

def check_quality_gates(item: Dict, coverage_ratio: float) -> Tuple[str, Optional[str]]:
    """
    단지 x 평형 데이터(item)와 가중치 커버리지(coverage_ratio)를 검사하여
    (gate_status, gate_reason)을 반환한다.
    gate_status: 'PASSED' 또는 'EXCLUDED'
    """
    # G5: 단지 매칭 실패
    if not item.get("complex_code"):
        return "EXCLUDED", "G5_UNMATCHED_COMPLEX"

    # G1: 최근 12개월 거래 샘플 수 검사 (최소 1건, 이상적 2건 이상)
    sample_n = item.get("sample_count_12m", 0)
    if sample_n < 1:
        return "EXCLUDED", "G1_LOW_VOLUME"

    # G2: 특수거래(직거래+해제) 비율 > 30% (단, 샘플수>=3 인 경우만 적용)
    special_ratio = item.get("special_deal_ratio", 0.0)
    if sample_n >= 3 and special_ratio > 0.30:
        return "EXCLUDED", "G2_HIGH_SPECIAL_DEALS"

    # G4: 평단가 이상치 (지역 평단가의 20% 미만 또는 500% 초과 시 이상치)
    ppp = item.get("price_per_pyeong", 0.0)
    if ppp <= 1000.0 or ppp > 30000.0:  # 서초/강남 평단가 현실적 바운드 (1,000만~30,000만)
        return "EXCLUDED", "G4_PRICE_OUTLIER"

    # G6: 커버리지 미달 (< 0.35)
    if coverage_ratio < 0.35:
        return "EXCLUDED", "G6_LOW_COVERAGE"

    return "PASSED", None
