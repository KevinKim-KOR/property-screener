# oci/crawler/molit_schema.py
"""
국토부 실거래가 CSV 및 API 수집 데이터를 내부 표준 구조체인 CanonicalTrade / CanonicalRentTrade로
정규화(Normalization)하는 어댑터 모듈 (SCORING_V2_DESIGN.md §4.1.1).
"""
import hashlib
from dataclasses import dataclass
from typing import Optional
from common.area_mapper import to_area_type

# 서울 자치구 매핑 (서초구 11650, 강남구 11680)
SGG_NAME_TO_CODE = {
    "서초구": "11650",
    "강남구": "11680",
    "송파구": "11710",
    "용산구": "11170",
    "성동구": "11200",
    "마포구": "11440",
    "영등포구": "11560",
    "강동구": "11740",
    "동작구": "11590",
    "광진구": "11215",
    "양천구": "11470"
}

def parse_region_string(region_str: str):
    """
    "서울특별시 서초구 방배동"과 같은 문자열에서
    sgg_cd("11650"), umd_nm("방배동")을 추출한다.
    """
    if not region_str:
        return "", ""
    parts = region_str.strip().split()
    umd_nm = parts[-1] if parts else ""
    sgg_cd = ""
    for token in parts:
        if token in SGG_NAME_TO_CODE:
            sgg_cd = SGG_NAME_TO_CODE[token]
            break
    return sgg_cd, umd_nm

def parse_int_safe(val) -> Optional[int]:
    if val is None:
        return None
    s = str(val).replace(",", "").strip()
    if not s or s == "-" or s == "":
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None

def parse_float_safe(val) -> Optional[float]:
    if val is None:
        return None
    s = str(val).replace(",", "").strip()
    if not s or s == "-" or s == "":
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None

def parse_date_safe(ymd_str: str, day_str: Optional[str] = None) -> str:
    """
    ymd_str="202607", day_str="16" -> "2026-07-16"
    또는 ymd_str="YY.MM.DD" / "YYYY-MM-DD" 포맷 변환
    """
    if not ymd_str or str(ymd_str).strip() in ("-", ""):
        return ""
    s = str(ymd_str).strip()
    if day_str and str(day_str).strip() not in ("-", ""):
        d = str(day_str).strip().zfill(2)
        if len(s) == 6:  # YYYYMM
            return f"{s[:4]}-{s[4:6]}-{d}"
    if "." in s:
        parts = s.split(".")
        if len(parts) == 3:
            y = parts[0].strip()
            if len(y) == 2:
                y = "20" + y
            m = parts[1].strip().zfill(2)
            d = parts[2].strip().zfill(2)
            return f"{y}-{m}-{d}"
    return s

@dataclass(frozen=True)
class CanonicalTrade:
    trade_id: str
    sgg_cd: str
    umd_nm: str
    bonbun: Optional[int]
    bubun: Optional[int]
    road_name: Optional[str]
    apt_name_raw: str
    exclusive_area: float
    area_type: Optional[str]
    deal_date: str
    deal_amount: int
    building_dong: Optional[str]
    floor: Optional[int]
    buyer_type: Optional[str]
    seller_type: Optional[str]
    build_year: Optional[int]
    is_cancelled: int
    cancel_date: Optional[str]
    deal_type: Optional[str]
    agent_region: Optional[str]
    registry_date: Optional[str]
    source: str
    source_snapshot_date: Optional[str]

    @staticmethod
    def generate_trade_id(sgg_cd: str, bonbun: Optional[int], bubun: Optional[int],
                          apt_name: str, exclusive_area: float, deal_date: str,
                          floor: Optional[int], deal_amount: int) -> str:
        key_str = f"{sgg_cd}|{bonbun}|{bubun}|{apt_name}|{exclusive_area:.2f}|{deal_date}|{floor}|{deal_amount}"
        return hashlib.sha256(key_str.encode("utf-8")).hexdigest()[:24]

    @classmethod
    def from_csv_row(cls, row: dict, source_snapshot_date: str) -> Optional["CanonicalTrade"]:
        """
        국토부 실거래 매매 CSV row(dict)로부터 CanonicalTrade 인스턴스를 생성한다.
        """
        required_cols = ["시군구", "단지명", "전용면적(㎡)", "계약년월", "계약일", "거래금액(만원)"]
        missing = [c for c in required_cols if c not in row]
        if missing:
            raise KeyError(f"매매 CSV 필수 컬럼 누락으로 적재를 중단합니다: {missing} (현재 헤더: {list(row.keys())})")

        region_str = row.get("시군구", "")
        sgg_cd, umd_nm = parse_region_string(region_str)
        if not sgg_cd:
            return None
        
        bonbun = parse_int_safe(row.get("본번"))
        bubun = parse_int_safe(row.get("부번"))
        road_name = row.get("도로명", "").strip() or None
        apt_name_raw = row.get("단지명", "").strip()
        if not apt_name_raw:
            return None

        exclusive_area = parse_float_safe(row.get("전용면적(㎡)"))
        if exclusive_area is None:
            return None
        area_type = to_area_type(exclusive_area)

        deal_date = parse_date_safe(row.get("계약년월", ""), row.get("계약일", ""))
        if not deal_date:
            return None

        deal_amount = parse_int_safe(row.get("거래금액(만원)"))
        if deal_amount is None or deal_amount <= 0:
            return None

        building_dong = row.get("동", "").strip()
        if building_dong in ("-", ""):
            building_dong = None

        floor = parse_int_safe(row.get("층"))
        buyer_type = row.get("매수자", "").strip() or None
        seller_type = row.get("매도자", "").strip() or None
        build_year = parse_int_safe(row.get("건축년도"))

        cancel_date = parse_date_safe(row.get("해제사유발생일", ""))
        is_cancelled = 1 if cancel_date else 0

        deal_type = row.get("거래유형", "").strip() or None
        agent_region = row.get("중개사소재지", "").strip()
        if agent_region in ("-", ""):
            agent_region = None
        registry_date = parse_date_safe(row.get("등기일자", "")) or None

        trade_id = cls.generate_trade_id(
            sgg_cd, bonbun, bubun, apt_name_raw, exclusive_area, deal_date, floor, deal_amount
        )

        return cls(
            trade_id=trade_id,
            sgg_cd=sgg_cd,
            umd_nm=umd_nm,
            bonbun=bonbun,
            bubun=bubun,
            road_name=road_name,
            apt_name_raw=apt_name_raw,
            exclusive_area=exclusive_area,
            area_type=area_type,
            deal_date=deal_date,
            deal_amount=deal_amount,
            building_dong=building_dong,
            floor=floor,
            buyer_type=buyer_type,
            seller_type=seller_type,
            build_year=build_year,
            is_cancelled=is_cancelled,
            cancel_date=cancel_date or None,
            deal_type=deal_type,
            agent_region=agent_region,
            registry_date=registry_date,
            source="CSV",
            source_snapshot_date=source_snapshot_date
        )


@dataclass(frozen=True)
class CanonicalRentTrade:
    rent_id: str
    sgg_cd: str
    umd_nm: str
    apt_name_raw: str
    exclusive_area: float
    area_type: Optional[str]
    deal_date: str
    deposit: int
    monthly_rent: int
    floor: Optional[int]
    contract_type: Optional[str]

    @staticmethod
    def generate_rent_id(sgg_cd: str, apt_name: str, exclusive_area: float,
                         deal_date: str, floor: Optional[int], deposit: int, monthly_rent: int) -> str:
        key_str = f"{sgg_cd}|{apt_name}|{exclusive_area:.2f}|{deal_date}|{floor}|{deposit}|{monthly_rent}"
        return hashlib.sha256(key_str.encode("utf-8")).hexdigest()[:24]

    @classmethod
    def from_csv_row(cls, row: dict) -> Optional["CanonicalRentTrade"]:
        """
        국토부 실거래 전월세 CSV row(dict)로부터 CanonicalRentTrade 인스턴스를 생성한다.
        """
        required_cols = ["시군구", "단지명", "전용면적(㎡)", "계약년월", "계약일", "보증금(만원)", "월세금(만원)"]
        missing = [c for c in required_cols if c not in row]
        if missing:
            raise KeyError(f"전월세 CSV 필수 컬럼 누락으로 적재를 중단합니다: {missing} (현재 헤더: {list(row.keys())})")

        region_str = row.get("시군구", "")
        sgg_cd, umd_nm = parse_region_string(region_str)
        if not sgg_cd:
            return None

        apt_name_raw = row.get("단지명", "").strip()
        if not apt_name_raw:
            return None

        exclusive_area = parse_float_safe(row.get("전용면적(㎡)"))
        if exclusive_area is None:
            return None
        area_type = to_area_type(exclusive_area)

        deal_date = parse_date_safe(row.get("계약년월", ""), row.get("계약일", ""))
        if not deal_date:
            return None

        deposit = parse_int_safe(row.get("보증금(만원)"))
        if deposit is None or deposit <= 0:
            return None

        monthly_rent = parse_int_safe(row.get("월세금(만원)")) or 0
        floor = parse_int_safe(row.get("층"))
        contract_type = row.get("계약구분", "").strip() or None

        rent_id = cls.generate_rent_id(
            sgg_cd, apt_name_raw, exclusive_area, deal_date, floor, deposit, monthly_rent
        )

        return cls(
            rent_id=rent_id,
            sgg_cd=sgg_cd,
            umd_nm=umd_nm,
            apt_name_raw=apt_name_raw,
            exclusive_area=exclusive_area,
            area_type=area_type,
            deal_date=deal_date,
            deposit=deposit,
            monthly_rent=monthly_rent,
            floor=floor,
            contract_type=contract_type
        )
