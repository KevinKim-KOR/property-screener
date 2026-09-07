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


# §5.5 민감도. 계단 구조 때문에 증가폭이 균등하지 않다는 점이 이 표의 핵심이다.
# 문턱(2.6억 부근)이 보이도록 2.5억을 구간에 넣었다.
SENSITIVITY_STEPS = (0, 100_000_000, 200_000_000, 250_000_000, 300_000_000,
                     400_000_000, 500_000_000, 700_000_000, 1_000_000_000)


def find_threshold(base_available: float, area_over_85: bool,
                   max_extra: float = 3_000_000_000.0, tol: float = 1_000_000.0,
                   config_path: Optional[str] = None) -> Optional[float]:
    """
    "얼마를 더 넣으면 매수 상한이 오르는가" 를 이분탐색으로 찾는다.

    상한이 구간 상단에 걸려 있으면 추가 자금을 조금 넣어도 상한이 그대로다.
    그 정체 구간을 벗어나는 최소 추가 자금을 돌려준다. 끝까지 안 오르면 None.
    (매수 상한은 추가 자금에 대해 단조 비감소이므로 이분탐색이 성립한다)
    """
    def cap_at(extra: float) -> Optional[float]:
        return compute_capacity(base_available + extra, area_over_85, config_path).max_price

    base = cap_at(0.0)
    if base is None:
        return None
    if cap_at(max_extra) is None or cap_at(max_extra) <= base + tol:
        return None   # 이 범위에서는 오르지 않는다

    lo, hi = 0.0, max_extra
    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        c = cap_at(mid)
        if c is not None and c > base + tol:
            hi = mid
        else:
            lo = mid
    return hi


def sensitivity(base_available: float, area_over_85: bool,
                targets: Optional[List[Dict]] = None,
                steps: Optional[List[float]] = None,
                config_path: Optional[str] = None) -> Dict:
    """
    §6.4 민감도표.

    targets: [{"label": "25평형대", "median_price": 3_245_000_000}, ...]
             목표 지역 중위가. 매수 상한만으로는 의미를 알 수 없으므로
             '얼마가 부족한지' 를 함께 낸다.
    """
    steps = list(steps if steps is not None else SENSITIVITY_STEPS)
    threshold = find_threshold(base_available, area_over_85, config_path=config_path)
    if threshold is not None and not any(abs(threshold - s) < 1_000_000 for s in steps):
        steps.append(threshold)
        steps.sort()

    rows: List[Dict] = []
    prev: Optional[float] = None
    for extra in steps:
        cap = compute_capacity(base_available + extra, area_over_85, config_path)
        price = cap.max_price
        row = {
            "extra_fund": round(extra),
            "max_price": None if price is None else round(price),
            "increase": None if (price is None or prev is None) else round(price - prev),
            "is_threshold": threshold is not None and abs(extra - threshold) < 1_000_000,
            "shortfalls": [],
        }
        for t in (targets or []):
            med = t.get("median_price")
            if med is None or price is None:
                continue
            row["shortfalls"].append({
                "label": t["label"],
                "shortfall": round(max(0.0, med - price)),
                "reached": price >= med,
            })
        rows.append(row)
        if price is not None:
            prev = price

    # 목표 지역에 닿으려면 추가 자금이 얼마 필요한지
    needed: List[Dict] = []
    for t in (targets or []):
        med = t.get("median_price")
        if med is None:
            continue
        lo, hi = 0.0, 5_000_000_000.0
        top = compute_capacity(base_available + hi, area_over_85, config_path).max_price
        if top is None or top < med:
            needed.append({"label": t["label"], "extra_needed": None})
            continue
        while hi - lo > 1_000_000.0:
            mid = (lo + hi) / 2.0
            c = compute_capacity(base_available + mid, area_over_85, config_path).max_price
            if c is not None and c >= med:
                hi = mid
            else:
                lo = mid
        needed.append({"label": t["label"], "extra_needed": round(hi)})

    return {"threshold": None if threshold is None else round(threshold),
            "rows": rows, "extra_needed_for_targets": needed}
