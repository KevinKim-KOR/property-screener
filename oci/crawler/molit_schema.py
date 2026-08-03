# oci/crawler/molit_schema.py
"""
국토부 실거래가 CSV 및 API 수집 데이터를 내부 표준 구조체인 CanonicalTrade / CanonicalRentTrade로
정규화(Normalization)하는 어댑터 모듈 (SCORING_V2_DESIGN.md §4.1.1).
"""
import hashlib
from dataclasses import dataclass
from typing import Optional
from common.area_mapper import to_area_type


def normalize_value(val) -> Optional[str]:
    """
    CSV("-", "") 및 API(공백 한 칸 " ") 양쪽에서 빈 값을 통일하여 None으로 만든다.
    유효한 값이면 strip된 문자열을 반환한다.
    """
    if val is None:
        return None
    s = str(val).strip()
    if not s or s == "-":
        return None
    return s

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
    s = normalize_value(val)
    if s is None:
        return None
    s = s.replace(",", "")
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None

def parse_float_safe(val) -> Optional[float]:
    s = normalize_value(val)
    if s is None:
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None

def parse_date_safe(ymd_str: str, day_str: Optional[str] = None) -> str:
    """
    ymd_str="202607", day_str="16" -> "2026-07-16"
    또는 ymd_str="YY.MM.DD" / "YYYY-MM-DD" 포맷 변환
    """
    s = normalize_value(ymd_str)
    if s is None:
        return ""
    if day_str and normalize_value(day_str):
        d = normalize_value(day_str).zfill(2)
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
    land_leasehold: Optional[str]
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
        road_name = normalize_value(row.get("도로명"))
        apt_name_raw = normalize_value(row.get("단지명"))
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

        building_dong = normalize_value(row.get("동"))

        floor = parse_int_safe(row.get("층"))
        buyer_type = normalize_value(row.get("매수자"))
        seller_type = normalize_value(row.get("매도자"))
        build_year = parse_int_safe(row.get("건축년도"))

        cancel_date = parse_date_safe(row.get("해제사유발생일", ""))
        is_cancelled = 1 if cancel_date else 0

        deal_type = normalize_value(row.get("거래유형"))
        agent_region = normalize_value(row.get("중개사소재지"))
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
            land_leasehold=None,
            source="CSV",
            source_snapshot_date=source_snapshot_date
        )

    @classmethod
    def from_api_item(cls, item: dict, sgg_cd: str, deal_ymd: str, source_snapshot_date: str) -> Optional["CanonicalTrade"]:
        """
        국토부 매매 상세 API XML item(dict)으로부터 CanonicalTrade 인스턴스를 생성한다.
        API 필드명(영문)을 CSV와 동일한 canonical 구조체로 정규화한다.
        """
        apt_name_raw = normalize_value(item.get("aptNm"))
        if not apt_name_raw:
            return None

        umd_nm = normalize_value(item.get("umdNm")) or ""
        # sgg_cd는 호출자가 전달하거나 API 응답에서 읽음
        api_sgg = normalize_value(item.get("sggCd")) or sgg_cd

        # 본번/부번: API는 0패딩 문자열("0160", "0002") → 정수로 변환
        bonbun = parse_int_safe(item.get("bonbun"))
        bubun = parse_int_safe(item.get("bubun"))

        road_name = normalize_value(item.get("roadNm"))

        exclusive_area = parse_float_safe(item.get("excluUseAr"))
        if exclusive_area is None:
            return None
        area_type = to_area_type(exclusive_area)

        deal_year = normalize_value(item.get("dealYear"))
        deal_month = normalize_value(item.get("dealMonth"))
        deal_day = normalize_value(item.get("dealDay"))
        if not deal_year or not deal_month or not deal_day:
            return None
        deal_date = f"{deal_year}-{deal_month.zfill(2)}-{deal_day.zfill(2)}"

        deal_amount = parse_int_safe(item.get("dealAmount"))
        if deal_amount is None or deal_amount <= 0:
            return None

        building_dong = normalize_value(item.get("aptDong"))
        floor = parse_int_safe(item.get("floor"))
        buyer_type = normalize_value(item.get("buyerGbn"))
        seller_type = normalize_value(item.get("slerGbn"))
        build_year = parse_int_safe(item.get("buildYear"))

        # 해제사유발생일: API는 공백이면 미해제
        cancel_date_raw = normalize_value(item.get("cdealDay"))
        # cdealType도 확인 (해제여부)
        cdeal_type = normalize_value(item.get("cdealType"))
        if cancel_date_raw:
            # cdealDay는 일자만 올 수 있고, 날짜 전체가 올 수도 있음
            cancel_date = parse_date_safe(cancel_date_raw) or cancel_date_raw
            is_cancelled = 1
        elif cdeal_type and cdeal_type in ("O", "해제"):
            is_cancelled = 1
            cancel_date = None
        else:
            is_cancelled = 0
            cancel_date = None

        deal_type = normalize_value(item.get("dealingGbn"))
        agent_region = normalize_value(item.get("estateAgentSggNm"))
        registry_date = normalize_value(item.get("rgstDate"))
        if registry_date:
            registry_date = parse_date_safe(registry_date) or registry_date

        # 토지임대부 플래그
        land_leasehold_raw = normalize_value(item.get("landLeaseholdGbn"))
        land_leasehold = land_leasehold_raw  # "N" / "Y" 등

        trade_id = cls.generate_trade_id(
            api_sgg, bonbun, bubun, apt_name_raw, exclusive_area, deal_date, floor, deal_amount
        )

        return cls(
            trade_id=trade_id,
            sgg_cd=api_sgg,
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
            cancel_date=cancel_date,
            deal_type=deal_type,
            agent_region=agent_region,
            registry_date=registry_date,
            land_leasehold=land_leasehold,
            source="API",
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

        apt_name_raw = normalize_value(row.get("단지명"))
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
        contract_type = normalize_value(row.get("계약구분"))

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

    @classmethod
    def from_api_item(cls, item: dict, sgg_cd: str) -> Optional["CanonicalRentTrade"]:
        """
        국토부 전월세 API XML item(dict)으로부터 CanonicalRentTrade 인스턴스를 생성한다.
        """
        apt_name_raw = normalize_value(item.get("aptNm"))
        if not apt_name_raw:
            return None

        umd_nm = normalize_value(item.get("umdNm")) or ""
        api_sgg = normalize_value(item.get("sggCd")) or sgg_cd

        exclusive_area = parse_float_safe(item.get("excluUseAr"))
        if exclusive_area is None:
            return None
        area_type = to_area_type(exclusive_area)

        deal_year = normalize_value(item.get("dealYear"))
        deal_month = normalize_value(item.get("dealMonth"))
        deal_day = normalize_value(item.get("dealDay"))
        if not deal_year or not deal_month or not deal_day:
            return None
        deal_date = f"{deal_year}-{deal_month.zfill(2)}-{deal_day.zfill(2)}"

        deposit = parse_int_safe(item.get("deposit"))
        if deposit is None or deposit <= 0:
            return None

        monthly_rent = parse_int_safe(item.get("monthlyRent")) or 0
        floor = parse_int_safe(item.get("floor"))
        contract_type = normalize_value(item.get("contractType"))

        rent_id = cls.generate_rent_id(
            api_sgg, apt_name_raw, exclusive_area, deal_date, floor, deposit, monthly_rent
        )

        return cls(
            rent_id=rent_id,
            sgg_cd=api_sgg,
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
