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
) -> Tuple[List[Dict], str, int, str]:
    """
    complex_item에 대한 비교군 목록을 3단계 폴백(법정동 → 구 → 벨트)으로 결정한다.

    표본이 기준에 못 미치면 중위수와 MAD 가 불안정해져 점수가 잡음이 된다.
    따라서 기준을 낮추지 않고 폴백만 하며, 벨트에서도 채우지 못하면
    **점수를 내지 않는다**(없는 게 틀린 것보다 낫다).

    all_items 에는 **게이트를 통과한 단지만** 넘겨야 한다. 제외된 단지는
    거래가 없어 통계값이 전부 같아 MAD 가 0이 되고, 그러면 모든 편차가
    0으로 계산되어 점수가 붕괴한다(실측: 비교군 103곳 중 66곳 동일값).

    반환: (peer_items, peer_group_key, peer_group_n, level)
      level 은 "UMD" | "SGG" | "BELT" | "NONE".
      "NONE" 이면 peer_items 는 비어 있고 점수를 내지 않아야 한다.
    """
    sgg = complex_item.get("sgg_cd")
    umd = complex_item.get("umd_nm")
    at = complex_item.get("area_type")

    # 1. UMD_AREA (동일 법정동 x area_type)
    if sgg and umd and at:
        umd_peers = [x for x in all_items
                     if x.get("sgg_cd") == sgg and x.get("umd_nm") == umd and x.get("area_type") == at]
        if len(umd_peers) >= min_umd_n:
            return umd_peers, f"UMD_{sgg}_{umd}_{at}", len(umd_peers), "UMD"

    # 2. SGG_AREA (동일 시군구 x area_type)
    if sgg and at:
        sgg_peers = [x for x in all_items if x.get("sgg_cd") == sgg and x.get("area_type") == at]
        if len(sgg_peers) >= min_sgg_n:
            return sgg_peers, f"SGG_{sgg}_{at}", len(sgg_peers), "SGG"

    # 3. BELT_AREA (서초+강남 통합 x area_type)
    belt_peers = [x for x in all_items if x.get("area_type") == at]
    if len(belt_peers) >= min_belt_n:
        return belt_peers, f"BELT_{at}", len(belt_peers), "BELT"

    # 4. 벨트에서도 미달 -> 점수 산출 불가
    return [], f"NONE_{at}", len(belt_peers), "NONE"
