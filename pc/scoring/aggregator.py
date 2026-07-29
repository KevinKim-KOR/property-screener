# pc/scoring/aggregator.py
"""
4-Block 가중합 산출 및 정규분포 CDF(Φ) 변환 기반 0~100점 점수화 모듈
(SCORING_V2_DESIGN.md §10.1, §10.2).
"""
import math
from typing import Dict, Tuple

W_A = 0.35
W_B = 0.25
W_C = 0.20
W_D = 0.20

def calculate_normal_cdf(z: float) -> float:
    """
    표준정규분포 누적분포함수 Φ(z) 연산
    Φ(z) = 0.5 * (1 + erf(z / sqrt(2)))
    """
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def aggregate_blocks(block_scores: Dict[str, float], risk_multiplier: float = 1.0) -> Tuple[float, float, float]:
    """
    4-Block 가중합을 계산하고,
    정규분포 CDF 변환으로 100점 만점 점수(base_score, market_score)를 산출한다.
    반환: (raw_score, base_score, market_score)
    """
    a = block_scores.get("A", 0.0)
    b = block_scores.get("B", 0.0)
    c = block_scores.get("C", 0.0)
    d = block_scores.get("D", 0.0)

    raw_score = (W_A * a) + (W_B * b) + (W_C * c) + (W_D * d)
    base_score = calculate_normal_cdf(raw_score) * 100.0
    market_score = round(base_score * risk_multiplier, 1)

    return raw_score, base_score, market_score
