# common/peer_group.py
"""
3단계 비교군 폴백(UMD_AREA -> SGG_AREA -> BELT_AREA) 및
MAD(Median Absolute Deviation) 기반 robust z-score 정규화 모듈
(SCORING_V2_DESIGN.md §8.3, §9.2, P1-AC10).
"""
import statistics
from typing import List, Dict, Tuple, Optional

def calculate_robust_z_score(val: float, peers: List[float], clamp_min: float = -3.0, clamp_max: float = 3.0) -> float:
    """
    MAD 기반 Robust z-score 산출:
      z = (val - med) / (MAD * 1.4826)
      클램핑: [-3.0, +3.0]
    """
    if not peers or len(peers) < 2:
        return 0.0
    med = statistics.median(peers)
    devs = [abs(p - med) for p in peers]
    mad = statistics.median(devs)
    sigma = mad * 1.4826
    if sigma <= 1e-9:
        return 0.0
    z = (val - med) / sigma
    return max(clamp_min, min(clamp_max, z))


def select_peer_group(
    complex_item: Dict,
    all_items: List[Dict],
    min_umd_n: int = 5,
    min_sgg_n: int = 10,
    min_belt_n: int = 15
) -> Tuple[List[Dict], str, int]:
    """
    complex_item에 대한 비교군 목록을 3단계 폴백으로 결정한다.
    반환: (peer_items, peer_group_key, peer_group_n)
    """
    sgg = complex_item.get("sgg_cd", "11650")
    umd = complex_item.get("umd_nm", "방배동")
    at = complex_item.get("area_type", "A84")

    # 1. UMD_AREA (동일 읍면동 x area_type)
    umd_peers = [x for x in all_items if x.get("sgg_cd") == sgg and x.get("umd_nm") == umd and x.get("area_type") == at]
    if len(umd_peers) >= min_umd_n:
        return umd_peers, f"UMD_{sgg}_{umd}_{at}", len(umd_peers)

    # 2. SGG_AREA (동일 시군구 x area_type)
    sgg_peers = [x for x in all_items if x.get("sgg_cd") == sgg and x.get("area_type") == at]
    if len(sgg_peers) >= min_sgg_n:
        return sgg_peers, f"SGG_{sgg}_{at}", len(sgg_peers)

    # 3. BELT_AREA (강남/서초 통합 x area_type)
    belt_peers = [x for x in all_items if x.get("area_type") == at]
    return belt_peers, f"BELT_{at}", len(belt_peers)
