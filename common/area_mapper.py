# common/area_mapper.py
"""
국토부 실거래 전용면적(㎡) 및 네이버 평형 문자열을
SCORING_V2 표준 area_type (A40, A59, A84, A114, A135P)으로 변환하는 모듈.
"""
from typing import Optional

def to_area_type(exclusive_area_m2: Optional[float]) -> Optional[str]:
    """
    전용면적(㎡) 실수값을 받아서 SCORING_V2_DESIGN.md §3.4 기준에 따른
    area_type 문자열을 반환한다.
    
    규칙:
      A40  : 33.0 <= x < 50.0
      A59  : 50.0 <= x < 70.0  (20평형대)
      A84  : 70.0 <= x < 100.0 (30평형대)
      A114 : 100.0 <= x < 135.0 (40평형대)
      A135P: 135.0 <= x
      범위 밖 (< 33.0 또는 None) : None 반환
    """
    if exclusive_area_m2 is None:
        return None
    try:
        val = float(exclusive_area_m2)
    except (ValueError, TypeError):
        return None

    if val < 33.0:
        return None
    elif val < 50.0:
        return "A40"
    elif val < 70.0:
        return "A59"
    elif val < 100.0:
        return "A84"
    elif val < 135.0:
        return "A114"
    else:
        return "A135P"


def pyeong_to_area_type(area_pyeong_str: Optional[str]) -> Optional[str]:
    """
    네이버 호가 매물에서 exclusive_area(㎡)가 부재할 경우,
    기존 area_pyeong (예: '20PY', '30PY', '40PY', '20평형대' 등)을
    표준 area_type으로 변환하는 폴백 매퍼.
    """
    if not area_pyeong_str:
        return None
    s = str(area_pyeong_str).upper().strip()
    if "20" in s:
        return "A59"
    elif "30" in s:
        return "A84"
    elif "40" in s or "50" in s:
        return "A114"
    return None
