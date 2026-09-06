# common/my_property.py
"""
보유 주택(내 집) 한 채에 대한 유니버스 예외.

분석 유니버스는 서초구(11650)·강남구(11680)로 제한되어 있다(C8).
내 집은 영등포구라 그 밖이지만, 매도 검토를 위해 같은 기준으로 시세를
추적해야 한다. **유니버스 확장이 아니라 한 채짜리 허용 목록**이다.

판별은 반드시 이 모듈의 함수만 쓴다. 조건이 여러 파일에 흩어지면
한 곳이 빠져도 드러나지 않는다(기간 창 하드코딩 때 겪은 문제).

계층별 처리
  포함  단지 마스터 / 단지 매칭 / 단지x평형 통계   <- 시세를 내야 하므로
  제외  지역 중위 통계 / 비교군 / 게이트 / 점수·V10·V11
"""
from typing import Dict, List, Optional, Tuple

from .config_loader import Config

TARGET_SGG: Tuple[str, ...] = ("11650", "11680")


class ForeignSggError(RuntimeError):
    """강남권 계산에 유니버스 밖 자치구가 섞인 경우."""


def get_my_property() -> Optional[Dict]:
    """config.yaml 의 my_property. 설정이 없으면 None."""
    cfg = (Config.load() or {}).get("my_property")
    if not cfg or not cfg.get("sgg_cd") or not cfg.get("apt_name"):
        return None
    return dict(cfg)


def my_property_sgg() -> Optional[str]:
    mp = get_my_property()
    return str(mp["sgg_cd"]) if mp else None


def allowed_sgg_codes() -> Tuple[str, ...]:
    """단지 마스터에 존재해도 되는 자치구. 유니버스 + 내 집."""
    sgg = my_property_sgg()
    return TARGET_SGG + ((sgg,) if sgg and sgg not in TARGET_SGG else ())


def is_my_property(sgg_cd, umd_nm=None, apt_name=None) -> bool:
    """
    내 집 단지인지 판별한다. 자치구·법정동·단지명이 모두 일치해야 한다.
    (같은 영등포구의 다른 단지가 통과하면 안 된다)
    """
    mp = get_my_property()
    if not mp:
        return False
    if str(sgg_cd or "") != str(mp["sgg_cd"]):
        return False
    if umd_nm is not None and str(umd_nm or "").strip() != str(mp["umd_nm"]).strip():
        return False
    if apt_name is not None and str(apt_name or "").strip() != str(mp["apt_name"]).strip():
        return False
    return True


def is_in_universe(sgg_cd) -> bool:
    """강남권 분석 유니버스에 속하는가. 내 집은 여기서 False."""
    return str(sgg_cd or "") in TARGET_SGG


def exclude_my_property(items: List[Dict], key: str = "sgg_cd") -> List[Dict]:
    """
    비교군·게이트·점수 산출에 넘기기 전 내 집을 걸러낸다.
    자치구만 보면 되므로(마스터에 내 집 외 영등포구 단지는 없다) 단순 필터로 충분하지만,
    그 전제가 깨지면 verify_no_foreign_sgg() 가 잡는다.
    """
    return [x for x in items if is_in_universe(x.get(key))]


def verify_no_foreign_sgg(base_date: Optional[str] = None) -> None:
    """
    강남권 계산에 유니버스 밖 자치구가 섞였는지 검사한다.
    하나라도 걸리면 ForeignSggError 를 던진다. 조용히 통과시키지 않는다.

    1. 단지 마스터에 허용 목록 밖 자치구가 있는가
    2. 단지 마스터의 유니버스 밖 단지가 내 집 하나뿐인가
    3. 지역 중위 통계에 유니버스 밖 자치구가 있는가
    4. 채점된 점수에 유니버스 밖 단지가 있는가
    5. 단지x평형 통계에 '내 집 외' 유니버스 밖 단지가 있는가
    """
    from .database import get_db_connection

    allowed = allowed_sgg_codes()
    mp = get_my_property()
    problems = []

    with get_db_connection() as conn:
        cur = conn.cursor()
        ph = ",".join("?" * len(allowed))

        # 1
        cur.execute(f"SELECT sgg_cd, COUNT(*) n FROM complexes "
                    f"WHERE sgg_cd NOT IN ({ph}) GROUP BY sgg_cd", allowed)
        for r in cur.fetchall():
            problems.append(f"[1] 단지 마스터에 허용 밖 자치구 {r['sgg_cd']} {r['n']:,}곳")

        # 2
        cur.execute("SELECT complex_code, sgg_cd, region_name, complex_name FROM complexes "
                    "WHERE sgg_cd NOT IN ('11650','11680')")
        outside = [dict(r) for r in cur.fetchall()]
        if mp is None and outside:
            problems.append(f"[2] my_property 설정이 없는데 유니버스 밖 단지 {len(outside)}곳")
        elif mp is not None:
            bad = [o for o in outside
                   if not is_my_property(o["sgg_cd"], o["region_name"], o["complex_name"])]
            if bad:
                problems.append(
                    "[2] 유니버스 밖 단지가 내 집 외에도 있습니다: "
                    + ", ".join(f"{b['region_name']}/{b['complex_name']}" for b in bad[:5]))
            if len(outside) > 1:
                problems.append(f"[2] 유니버스 밖 단지가 {len(outside)}곳입니다(1곳이어야 함)")

        # 3
        cur.execute("SELECT DISTINCT sgg_cd FROM region_stats WHERE sgg_cd NOT IN ('11650','11680','BELT')")
        rows = [r["sgg_cd"] for r in cur.fetchall()]
        if rows:
            problems.append(f"[3] 지역 중위 통계에 유니버스 밖 자치구: {rows}")

        # 4
        sql4 = ("SELECT c.sgg_cd, COUNT(*) n FROM market_scores m "
                "JOIN complexes c ON m.complex_code = c.complex_code "
                "WHERE c.sgg_cd NOT IN ('11650','11680')")
        params4: tuple = ()
        if base_date:
            sql4 += " AND m.base_date = ?"
            params4 = (base_date,)
        cur.execute(sql4 + " GROUP BY c.sgg_cd", params4)
        for r in cur.fetchall():
            problems.append(f"[4] 점수 산출에 유니버스 밖 자치구 {r['sgg_cd']} {r['n']:,}건")

        # 5
        sql5 = ("SELECT c.sgg_cd, c.region_name, c.complex_name, COUNT(*) n "
                "FROM complex_area_stats s JOIN complexes c ON s.complex_code = c.complex_code "
                "WHERE c.sgg_cd NOT IN ('11650','11680')")
        params5: tuple = ()
        if base_date:
            sql5 += " AND s.base_date = ?"
            params5 = (base_date,)
        cur.execute(sql5 + " GROUP BY c.complex_code", params5)
        for r in cur.fetchall():
            if not is_my_property(r["sgg_cd"], r["region_name"], r["complex_name"]):
                problems.append(
                    f"[5] 단지x평형 통계에 내 집 외 유니버스 밖 단지: "
                    f"{r['region_name']}/{r['complex_name']} {r['n']}건")

    if problems:
        raise ForeignSggError(
            "강남권 계산이 유니버스 밖 자료로 오염되었습니다:\n  " + "\n  ".join(problems))
