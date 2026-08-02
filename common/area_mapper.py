# common/area_mapper.py
"""
국토부 실거래 전용면적(㎡) 및 네이버 평형 문자열을
SCORING_V2 표준 area_type (A40, A59, A84, A114, A135P)으로 변환하는 모듈.
"""
from typing import Optional

def to_area_type(exclusive_area_m2: Optional[float]) -> Optional[str]:
    """
    전용면적(㎡) 실수값을 받아서 5㎡ 단위 계산용 버킷 area_type 문자열을 반환한다.
    규칙:
      50~55 / 55~60 / ... / 130~135 (예: A80_85, A95_100)
      범위 밖 (< 50.0 또는 >= 135.0 또는 None) : None 반환
    """
    if exclusive_area_m2 is None:
        return None
    try:
        val = float(exclusive_area_m2)
    except (ValueError, TypeError):
        return None

    if val < 50.0 or val >= 135.0:
        return None

    low = int(val // 5) * 5
    high = low + 5
    return f"A{low}_{high}"


def pyeong_to_area_type(area_pyeong_val: Optional[object]) -> Optional[str]:
    """
    네이버 호가 매물에서 exclusive_area(㎡)가 부재할 경우,
    기존 area_pyeong (실수값 또는 '20PY', '30PY', '40PY' 등)을
    표준 5㎡ area_type으로 변환하는 폴백 매퍼.
    """
    if area_pyeong_val is None:
        return None
    try:
        val = float(area_pyeong_val)
        if val < 18.0:
            return None
        elif val < 28.0:
            return "A55_60"
        elif val < 38.0:
            return "A80_85"
        elif val < 50.0:
            return "A110_115"
        else:
            return None
    except (ValueError, TypeError):
        s = str(area_pyeong_val).upper()
        if "20PY" in s or "20평" in s:
            return "A55_60"
        elif "30PY" in s or "30평" in s:
            return "A80_85"
        elif "40PY" in s or "40평" in s:
            return "A110_115"
        return None
