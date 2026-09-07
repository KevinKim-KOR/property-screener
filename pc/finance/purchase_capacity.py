# pc/finance/purchase_capacity.py
"""
매수 가능가 상한 산출 (개발요청서 §5.4, §6.1, §6.3).

핵심은 대출 한도가 매수가 구간에 따라 계단식으로 바뀐다는 점이다.
매수가가 구간을 정하고, 구간이 대출 한도를 정하고, 대출 한도가 다시 매수
가능가를 정한다. 이 순환 때문에 단일 나눗셈(가용자금 ÷ (1+부대비용률))으로
풀면 틀린 답이 나온다. 구간마다 후보를 만들고 유효성을 따로 검사한다.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from common.tax_config import load_tax_config


class PurchaseCapacityError(RuntimeError):
    """매수 상한을 산출할 수 없는 경우."""


@dataclass
class BracketCandidate:
    index: int
    lower: float
    upper: Optional[float]
    bracket_limit: float
    candidate_price: Optional[float]
    loan: Optional[float]
    required_funds: Optional[float]
    feasible: bool
    reason: str


@dataclass
class CapacityResult:
    available_funds: float
    cost_rate: float
    max_price: Optional[float]          # 매수 가능 상한. 없으면 None
    loan_at_max: Optional[float]
    own_funds_needed: Optional[float]
    leftover: Optional[float]
    candidates: List[BracketCandidate] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def cost_rate_for(area_over_85: bool, cfg: Optional[Dict] = None) -> float:
    """매수 부대비용률. 취득세 + 지방교육세 (+ 농특세) + 중개보수×1.1"""
    cfg = cfg or load_tax_config()
    c = cfg["transaction_cost"]
    rate = (float(c["acquisition_tax_over_900m"])
            + float(c["local_education_tax"])
            + float(c["brokerage_rate_over_1_5b"]) * (1.0 + float(c["brokerage_vat_rate"])))
    if area_over_85:
        rate += float(c["rural_special_tax_over_85"])
    return rate


def _loan_for(price: float, bracket_limit: float, ltv: float) -> float:
    """실제 대출 = min(구간 한도, 주택가격 × LTV)"""
    return min(bracket_limit, price * ltv)


def _affordable(price: float, available: float, bracket_limit: float,
                ltv: float, cost_rate: float) -> bool:
    return price * (1.0 + cost_rate) <= available + _loan_for(price, bracket_limit, ltv) + 1e-6


def compute_capacity(available_funds: float, area_over_85: bool,
                     config_path: Optional[str] = None) -> CapacityResult:
    """
    가용자금으로 살 수 있는 최대 주택가격을 구간별로 탐색한다.
    유효 후보가 하나도 없으면 max_price 는 None 이다(근사값을 만들지 않는다).
    """
    cfg = load_tax_config(config_path)
    loan_cfg = cfg.get("loan_limit")
    if not loan_cfg:
        raise PurchaseCapacityError("대출 한도 설정이 없습니다.")
    ltv = float(loan_cfg["ltv"])
    brackets = loan_cfg["brackets"]
    cost_rate = cost_rate_for(area_over_85, cfg)

    candidates: List[BracketCandidate] = []
    best: Optional[float] = None
    best_bracket: Optional[Dict] = None

    for i, b in enumerate(brackets):
        lower = float(b.get("min", 0) or 0)
        upper = None if b.get("max") is None else float(b["max"])
        limit = float(b["limit"])

        # 2) 구간 한도를 다 쓴다고 보고 후보가를 만든다.
        raw = (available_funds + limit) / (1.0 + cost_rate)

        price: Optional[float] = None
        reason = ""

        if raw < lower:
            reason = "이 구간에 못 미침"
        elif upper is not None and raw >= upper:
            # 3) 구간 상단으로 클램프. 상단에서도 감당되면 (상한 - 1원)을 후보로.
            probe = upper - 1.0
            if _affordable(probe, available_funds, limit, ltv, cost_rate):
                price = probe
                reason = "구간 상단"
            else:
                reason = "구간 상단에서 자금 부족"
        else:
            price = raw
            reason = "구간 내"

        # 4) LTV 재검증. 후보가로 계산한 실제 대출로 다시 따진다.
        if price is not None and not _affordable(price, available_funds, limit, ltv, cost_rate):
            # 대출이 구간 한도가 아니라 가격×LTV 로 묶이는 구간이다.
            #   P(1+r) = 가용 + P·ltv   ->   P = 가용 / (1 + r - ltv)
            denom = 1.0 + cost_rate - ltv
            price = (available_funds / denom) if denom > 0 else None
            reason = "대출이 LTV 로 제한됨"
            if price is not None and (price < lower or (upper is not None and price >= upper)):
                price = None
                reason = "LTV 제한 후 구간을 벗어남"
            if price is not None and not _affordable(price, available_funds, limit, ltv, cost_rate):
                price = None
                reason = "자금 부족"

        # 0원 이하는 매수가가 아니다. 근사값을 만들지 않는다.
        if price is not None and price <= 0:
            price = None
            reason = "가용자금이 없어 후보를 만들 수 없음"

        loan = _loan_for(price, limit, ltv) if price is not None else None
        need = price * (1.0 + cost_rate) if price is not None else None
        candidates.append(BracketCandidate(
            index=i, lower=lower, upper=upper, bracket_limit=limit,
            candidate_price=price, loan=loan, required_funds=need,
            feasible=price is not None, reason=reason))

        if price is not None and (best is None or price > best):
            best, best_bracket = price, b

    notes: List[str] = []
    if best is None:
        notes.append("현재 가용자금으로는 매수할 수 있는 가격대가 없습니다.")
        return CapacityResult(available_funds=available_funds, cost_rate=cost_rate,
                              max_price=None, loan_at_max=None, own_funds_needed=None,
                              leftover=None, candidates=candidates, notes=notes)

    limit = float(best_bracket["limit"])
    loan = _loan_for(best, limit, ltv)
    need = best * (1.0 + cost_rate)
    return CapacityResult(
        available_funds=available_funds, cost_rate=cost_rate,
        max_price=best, loan_at_max=loan,
        own_funds_needed=need - loan,
        leftover=available_funds - (need - loan),
        candidates=candidates, notes=notes)


def evaluate_price(price: float, available_funds: float, area_over_85: bool,
                   config_path: Optional[str] = None) -> Dict:
    """§6.3 구간별 판정표의 한 행. 특정 매수가가 가능한지 본다."""
    cfg = load_tax_config(config_path)
    loan_cfg = cfg["loan_limit"]
    ltv = float(loan_cfg["ltv"])
    cost_rate = cost_rate_for(area_over_85, cfg)

    limit = None
    for b in loan_cfg["brackets"]:
        lo = float(b.get("min", 0) or 0)
        hi = b.get("max")
        if price >= lo and (hi is None or price < float(hi)):
            limit = float(b["limit"])
            break
    if limit is None:
        raise PurchaseCapacityError(f"매수가 {price:,.0f} 에 해당하는 대출 구간을 찾지 못했습니다.")

    loan = _loan_for(price, limit, ltv)
    need = price * (1.0 + cost_rate)
    return {
        "price": price,
        "loan": loan,
        "required_funds": need,
        "available_funds": available_funds,
        "feasible": need <= available_funds + loan + 1e-6,
    }
