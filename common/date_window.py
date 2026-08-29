# common/date_window.py
"""
기간 창(window) 시작일 계산.

날짜 계산이 파일마다 흩어져 있으면 하드코딩이 섞여 들어가도 드러나지 않는다.
실제로 build_stats.py 는 창 시작일을 고정 문자열로 두고 있었고, 시간이 지나면서
'3개월 창'이 3.9개월치가 되어 있었다(2026-08-27 기준). 아무 신호도 나지 않았다.

기간 계산은 전부 이 모듈을 통한다.
"""
from datetime import date, datetime
from typing import Union

_DateLike = Union[str, date, datetime]


def _to_date(value: _DateLike) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"날짜 형식이 올바르지 않습니다: {value!r} (YYYY-MM-DD 필요)") from e


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year + (month // 12), (month % 12) + 1, 1) - date(year, month, 1)).days


def window_start(base_date: _DateLike, months: int) -> str:
    """
    base_date 로부터 `months` 개월 전 날짜를 'YYYY-MM-DD' 로 돌려준다.

    말일 처리: 3월 31일에서 1개월 전은 2월 28/29일로 맞춘다.

    >>> window_start("2026-08-27", 3)
    '2026-05-27'
    >>> window_start("2026-03-31", 1)
    '2026-02-28'
    """
    if months < 0:
        raise ValueError(f"months 는 0 이상이어야 합니다: {months}")
    d = _to_date(base_date)
    total = (d.year * 12 + (d.month - 1)) - months
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day).isoformat()


def months_between(start: _DateLike, end: _DateLike) -> float:
    """start ~ end 사이 개월 수(소수). 창 폭을 점검할 때 쓴다."""
    a, b = _to_date(start), _to_date(end)
    return (b.year - a.year) * 12 + (b.month - a.month) + (b.day - a.day) / 30.0


def years_between(start: _DateLike, end: _DateLike) -> float:
    """연식 계산용. 연도를 코드에 박지 않기 위해 쓴다."""
    return months_between(start, end) / 12.0
