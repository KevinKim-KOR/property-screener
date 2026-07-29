# pc/scoring/normalizer.py
"""
4-Block 팩터들의 비교군 내 MAD 기반 Robust Z-Score 산출 모듈
(SCORING_V2_DESIGN.md §9.1, §9.2).
"""
import math
from typing import Dict, List, Tuple
from common.peer_group import calculate_robust_z_score

def normalize_block_a(item: Dict, peers: List[Dict]) -> Tuple[float, float, Dict[str, float]]:
    """
    Block A (Value - 가중치 0.35) 정규화
    A1: excess_drop_rate (0.45)
    A2: jeonse_ratio (0.30)
    A3: price_per_pyeong (-z, 0.15)
    A4: rent_yield (0.10)
    반환: (block_score, coverage, factor_z_map)
    """
    weights = {"A1": 0.45, "A2": 0.30, "A3": 0.15, "A4": 0.10}
    z_map = {}

    p_a1 = [x.get("excess_drop_rate") or 0.0 for x in peers]
    z_map["A1"] = calculate_robust_z_score(item.get("excess_drop_rate") or 0.0, p_a1)

    p_a2 = [x.get("jeonse_ratio") or 0.55 for x in peers]
    z_map["A2"] = calculate_robust_z_score(item.get("jeonse_ratio") or 0.55, p_a2)

    p_a3 = [x.get("price_per_pyeong") or 5000.0 for x in peers]
    z_map["A3"] = -calculate_robust_z_score(item.get("price_per_pyeong") or 5000.0, p_a3)

    p_a4 = [x.get("rent_yield") or 0.035 for x in peers]
    z_map["A4"] = calculate_robust_z_score(item.get("rent_yield") or 0.035, p_a4)

    total_w = sum(weights.values())
    block_score = sum(z_map[k] * weights[k] for k in weights) / total_w
    return block_score, 1.0, z_map


def normalize_block_b(item: Dict, peers: List[Dict]) -> Tuple[float, float, Dict[str, float]]:
    """
    Block B (Flow/Supply - 가중치 0.25) 정규화
    B1: volume_ratio (0.35)
    B2: listing_delta_30d (-z, 0.25)
    B3: supply_pressure (-z, 0.20)
    B4: momentum_3m (0.20)
    """
    weights = {"B1": 0.35, "B2": 0.25, "B3": 0.20, "B4": 0.20}
    z_map = {}

    p_b1 = [x.get("volume_ratio") or 1.0 for x in peers]
    z_map["B1"] = calculate_robust_z_score(item.get("volume_ratio") or 1.0, p_b1)

    p_b2 = [x.get("listing_delta_30d") or 0.0 for x in peers]
    z_map["B2"] = -calculate_robust_z_score(item.get("listing_delta_30d") or 0.0, p_b2)

    p_b3 = [x.get("supply_pressure") or 0.0 for x in peers]
    z_map["B3"] = -calculate_robust_z_score(item.get("supply_pressure") or 0.0, p_b3)

    p_b4 = [x.get("momentum_3m") or 0.0 for x in peers]
    z_map["B4"] = calculate_robust_z_score(item.get("momentum_3m") or 0.0, p_b4)

    total_w = sum(weights.values())
    block_score = sum(z_map[k] * weights[k] for k in weights) / total_w
    return block_score, 1.0, z_map


def normalize_block_c(item: Dict, peers: List[Dict]) -> Tuple[float, float, Dict[str, float]]:
    """
    Block C (Location - 가중치 0.20) 정규화
    C1: subway_dist_m (-z, 0.40)
    C2: elem_school_dist_m (-z, 0.35)
    C3: cbd_transit_min (-z, 0.25)
    """
    weights = {"C1": 0.40, "C2": 0.35, "C3": 0.25}
    z_map = {}

    p_c1 = [x.get("subway_dist_m") or 500.0 for x in peers]
    z_map["C1"] = -calculate_robust_z_score(item.get("subway_dist_m") or 500.0, p_c1)

    p_c2 = [x.get("elem_school_dist_m") or 300.0 for x in peers]
    z_map["C2"] = -calculate_robust_z_score(item.get("elem_school_dist_m") or 300.0, p_c2)

    p_c3 = [x.get("cbd_transit_min") or 30.0 for x in peers]
    z_map["C3"] = -calculate_robust_z_score(item.get("cbd_transit_min") or 30.0, p_c3)

    total_w = sum(weights.values())
    block_score = sum(z_map[k] * weights[k] for k in weights) / total_w
    return block_score, 1.0, z_map


def normalize_block_d(item: Dict, peers: List[Dict]) -> Tuple[float, float, Dict[str, float]]:
    """
    Block D (Quality - 가중치 0.20) 정규화
    D1: households_log (0.35)
    D2: age_years (0.30 - 신축이나 재건축 가능 단지 우대 U자 곡선 반영)
    D3: far_score (0.20)
    D4: brand (0.15)
    """
    weights = {"D1": 0.35, "D2": 0.30, "D3": 0.20, "D4": 0.15}
    z_map = {}

    p_d1 = [x.get("households_log") or 2.5 for x in peers]
    z_map["D1"] = calculate_robust_z_score(item.get("households_log") or 2.5, p_d1)

    age = item.get("age_years") or 15.0
    age_score = 1.0 if age <= 10 or age >= 30 else 0.0
    p_d2 = [1.0 if (x.get("age_years") or 15.0) <= 10 or (x.get("age_years") or 15.0) >= 30 else 0.0 for x in peers]
    z_map["D2"] = calculate_robust_z_score(age_score, p_d2)

    p_d3 = [x.get("far_score") or 0.5 for x in peers]
    z_map["D3"] = calculate_robust_z_score(item.get("far_score") or 0.5, p_d3)

    top_brands = {"래미안", "자이", "디에이치", "아크로", "푸르지오써밋", "르엘", "트리마제", "아이파크"}
    b_score = 1.0 if any(b in str(item.get("brand", "")) for b in top_brands) else 0.0
    z_map["D4"] = b_score

    total_w = sum(weights.values())
    block_score = sum(z_map[k] * weights[k] for k in weights) / total_w
    return block_score, 1.0, z_map
