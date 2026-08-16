# pc/keymap/matcher.py
"""
국토부 실거래 단지(sgg_cd, umd_nm, bonbun, bubun, apt_name_raw, road_name, build_year)와
내부 단지 마스터(complexes / properties)를 연결하는 4단계 지번/도로명/단지명 매칭 엔진
(SCORING_V2_DESIGN.md §5).
"""
import re
import difflib
from typing import Optional, Tuple, Dict, List
from common.database import get_db_connection

def normalize_apt_name(name: str) -> str:
    """
    아파트 단지명 정규화:
    - (주상복합), 아파트, 아파트먼트 등 불필요 접미사 제거
    - 차수(1차, 2차 -> 1, 2) 표준화
    - 공백 및 특수문자 제거
    """
    if not name:
        return ""
    s = str(name)
    # 괄호 및 내용 제거
    s = re.sub(r"\(.*?\)", "", s)
    # '아파트', 'apt', 'APT' 등 단어 제거
    s = re.sub(r"(아파트|아파트먼트|APT|apt)", "", s)
    # '차' 제거 (예: 1차 -> 1)
    s = re.sub(r"(\d+)차", r"\1", s)
    # 공백 및 특수문자 제거
    s = re.sub(r"[^가-힣a-zA-Z0-9]", "", s)
    return s.lower()

def normalize_road_name(road_name: Optional[str]) -> str:
    """
    도로명 주소 정규화 (예: '방배로 73' -> '방배로73')
    """
    if not road_name:
        return ""
    return re.sub(r"\s+", "", str(road_name)).lower()

class ComplexMatcher:
    def __init__(self):
        self.complex_list: List[Dict] = []
        self._load_master_complexes()

    def _load_master_complexes(self):
        """
        complexes 및 properties 테이블에서 단지 마스터 목록을 로드한다.
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            # complexes 테이블 확인
            cur.execute("SELECT complex_code, complex_name, sgg_cd, umd_cd, region_name, build_year, bonbun, bubun, road_name FROM complexes")
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    self.complex_list.append({
                        "complex_code": r["complex_code"],
                        "complex_name": r["complex_name"],
                        "sgg_cd": r["sgg_cd"],
                        "build_year": r["build_year"],
                        "bonbun": r["bonbun"],
                        "bubun": r["bubun"],
                        "road_name": r["road_name"],
                        "norm_name": normalize_apt_name(r["complex_name"]),
                        "norm_road": normalize_road_name(r["road_name"])
                    })
            else:
                # complexes가 비어있다면 properties의 complex_code, complex_name, region_name 활용
                cur.execute("SELECT DISTINCT complex_code, complex_name, region_name FROM properties WHERE complex_code IS NOT NULL AND complex_code != ''")
                p_rows = cur.fetchall()
                for r in p_rows:
                    self.complex_list.append({
                        "complex_code": r["complex_code"],
                        "complex_name": r["complex_name"],
                        "sgg_cd": "11650" if "서초" in str(r["region_name"]) else "11680",
                        "build_year": None,
                        "bonbun": None,
                        "bubun": None,
                        "road_name": None,
                        "norm_name": normalize_apt_name(r["complex_name"]),
                        "norm_road": ""
                    })

    def _candidates_in_sgg(self, sgg_cd: str):
        """
        같은 자치구(sgg_cd)에 속한 단지 후보만 돌려준다.

        자치구 검증은 반드시 이 함수 하나만 쓴다. 티어마다 조건을 따로 쓰면
        이번처럼 한 곳에서 빠져도 드러나지 않는다.
        """
        return [c for c in self.complex_list if c["sgg_cd"] == sgg_cd]

    def match(self, sgg_cd: str, umd_nm: str, bonbun: Optional[int], bubun: Optional[int],
              road_name: Optional[str], apt_name_raw: str, build_year: Optional[int]) -> Tuple[Optional[str], float, str]:
        """
        4단계 매칭 로직 수행.
        반환: (matched_complex_code, confidence, match_method)
        """
        norm_name = normalize_apt_name(apt_name_raw)
        norm_road = normalize_road_name(road_name)

        # 자치구(sgg_cd)가 다르면 어떤 티어에서도 같은 단지일 수 없다.
        # 티어마다 이 검사를 따로 쓰다가 TIER_3 에서만 빠져, 서울 전역에서
        # 이름이 같은 단지들이 한 덩어리로 묶였다(잠원동 '동아'에 성수동·
        # 상일동·둔촌동·상도동 거래가 붙어 하락률 -79%, 전세가율 141%).
        # 후보 자체를 한 번만 걸러서 모든 티어가 같은 후보군을 쓰게 한다.
        candidates = self._candidates_in_sgg(sgg_cd)

        # 1. Tier 1: 지번 완전 일치 (본번, 부번이 존재하고 단지명 유사)
        if bonbun is not None:
            for c in candidates:
                if (c["bonbun"] == bonbun and
                    (c["bubun"] or 0) == (bubun or 0)):
                    # 단지명 정규화 일치 시 1.0
                    if c["norm_name"] == norm_name:
                        return c["complex_code"], 1.0, "TIER_1_JIBUN"

        # 2. Tier 2: 도로명 주소 정규화 일치
        if norm_road:
            for c in candidates:
                if c["norm_road"] and c["norm_road"] == norm_road:
                    return c["complex_code"], 0.95, "TIER_2_ROAD"

        # 3. Tier 3: 단지명 정규화 일치 (+ 건축년도 선택 일치)
        for c in candidates:
            if c["norm_name"] == norm_name:
                if build_year and c["build_year"] and abs(build_year - c["build_year"]) <= 1:
                    return c["complex_code"], 0.95, "TIER_3_NAME_YEAR"
                return c["complex_code"], 0.90, "TIER_3_NAME_ONLY"

        # 4. Tier 4: Fuzzy 문자열 유사도 (difflib SequenceMatcher >= 0.85)
        best_code = None
        best_ratio = 0.0
        for c in candidates:
            ratio = difflib.SequenceMatcher(None, norm_name, c["norm_name"]).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_code = c["complex_code"]

        if best_code and best_ratio >= 0.85:
            return best_code, best_ratio, "TIER_4_FUZZY"

        return None, best_ratio, "UNMATCHED"


def run_complex_matching() -> Dict[str, int]:
    """
    trades_sale 및 trades_rent의 매칭되지 않은(complex_code IS NULL) 거래 건들에 대해
    4단계 매칭을 수행하고 complex_key_map 및 실거래 테이블의 complex_code를 갱신한다.
    """
    matcher = ComplexMatcher()
    stats = {"total": 0, "matched": 0, "unmatched": 0}

    with get_db_connection() as conn:
        cur = conn.cursor()
        # 1. trades_sale 중 매칭 필요한 고유 단지 키 조회
        cur.execute("""
            SELECT DISTINCT sgg_cd, umd_nm, bonbun, bubun, road_name, apt_name_raw, build_year
            FROM trades_sale
            WHERE complex_code IS NULL OR complex_code = ''
        """)
        rows = cur.fetchall()

        for r in rows:
            stats["total"] += 1
            code, conf, method = matcher.match(
                r["sgg_cd"], r["umd_nm"], r["bonbun"], r["bubun"],
                r["road_name"], r["apt_name_raw"], r["build_year"]
            )
            norm_name = normalize_apt_name(r["apt_name_raw"])
            status = "AUTO_MATCHED" if code else ("REVIEW_REQUIRED" if conf >= 0.70 else "UNMATCHED")

            # complex_key_map 저장/갱신
            cur.execute("""
                INSERT OR REPLACE INTO complex_key_map (
                    complex_code, sgg_cd, umd_nm, bonbun, bubun, road_name,
                    apt_name_raw, apt_name_norm, build_year, confidence,
                    match_method, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code, r["sgg_cd"], r["umd_nm"], r["bonbun"], r["bubun"], r["road_name"],
                r["apt_name_raw"], norm_name, r["build_year"], conf, method, status
            ))

            if code:
                stats["matched"] += 1
                # trades_sale 및 trades_rent 테이블 업데이트
                cur.execute("""
                    UPDATE trades_sale SET complex_code = ?
                    WHERE sgg_cd = ? AND apt_name_raw = ?
                """, (code, r["sgg_cd"], r["apt_name_raw"]))
                cur.execute("""
                    UPDATE trades_rent SET complex_code = ?
                    WHERE sgg_cd = ? AND apt_name_raw = ?
                """, (code, r["sgg_cd"], r["apt_name_raw"]))
            else:
                stats["unmatched"] += 1

        conn.commit()

    verify_matching_integrity()
    return stats


class CrossSggMatchError(RuntimeError):
    """실거래가 다른 자치구의 단지에 매칭된 경우."""


def verify_matching_integrity() -> None:
    """
    매칭 결과 검증: 실거래의 자치구와 매칭된 단지의 자치구가 하나라도
    다르면 예외를 던진다.

    조용히 통과시키면 서로 다른 동네의 거래가 한 단지로 묶여 전고점·하락률·
    전세가율이 통째로 망가진다. 실제로 그 상태가 오래 드러나지 않았다.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        for table in ("trades_sale", "trades_rent"):
            cur.execute(f"""
                SELECT t.complex_code, c.complex_name, c.sgg_cd AS complex_sgg,
                       t.sgg_cd AS trade_sgg, COUNT(*) AS n
                FROM {table} t
                JOIN complexes c ON t.complex_code = c.complex_code
                WHERE t.complex_code IS NOT NULL AND t.sgg_cd != c.sgg_cd
                GROUP BY t.complex_code, c.sgg_cd, t.sgg_cd
                ORDER BY n DESC
                LIMIT 5
            """)
            bad = [dict(r) for r in cur.fetchall()]
            if bad:
                cur.execute(f"""
                    SELECT COUNT(*) AS n FROM {table} t
                    JOIN complexes c ON t.complex_code = c.complex_code
                    WHERE t.complex_code IS NOT NULL AND t.sgg_cd != c.sgg_cd
                """)
                total = cur.fetchone()["n"]
                sample = "; ".join(
                    f"{b['complex_name']}({b['complex_sgg']}) <- 거래 {b['trade_sgg']} {b['n']}건"
                    for b in bad
                )
                raise CrossSggMatchError(
                    f"{table}: 자치구가 다른 매칭 {total:,}건이 발견되었습니다. "
                    f"서로 다른 동네의 거래가 한 단지로 묶이면 전고점·하락률·전세가율이 "
                    f"모두 잘못됩니다. 예: {sample}"
                )
