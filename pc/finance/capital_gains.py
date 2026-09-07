# pc/finance/capital_gains.py
"""
매도 시 양도소득세 및 매도 순현금 산출 (1세대 1주택, 재건축 조합원 취득).

개발요청서 매수여력_판정_v1.0 §5.1~5.3, §6.2.

원칙
  - 필수 입력이 비면 계산하지 않는다. 0 이나 임의 기본값으로 대체하지 않는다.
  - 계산이 실패하면 세금을 0 으로 두지 않는다. 실패를 그대로 올려보낸다.
  - 세율·공제·부대비용률은 config/tax_and_loan.yaml 에서만 읽는다.
  - 중간 계산은 실수로 유지하고, 원 단위 반올림은 표시 단계에서 한다.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from common.tax_config import find_bracket, load_tax_config

# 화면에 그대로 쓰는 한글 이름. 사용자에게 내부 필드명을 보이지 않기 위함이다.
REQUIRED_FIELDS: Dict[str, str] = {
    "sale_price": "매도 예상가",
    "acq_price_prior": "종전주택 취득가액",
    "right_value": "권리가액",
    "contribution": "부담금",
    "member_supply_price": "조합원 분양가",
    "mortgage_balance": "상환할 주택담보대출 잔액",
    "hold_rate_prior": "기존건물분 보유공제율",
    "live_rate_prior": "기존건물분 거주공제율",
    "hold_rate_contrib": "청산금분 보유공제율",
    "live_rate_contrib": "청산금분 거주공제율",
}
OPTIONAL_FIELDS: Dict[str, str] = {
    "necessary_expense": "필요경비",
}


class MissingInputError(ValueError):
    """필수 입력이 비어 계산을 수행하지 않은 경우."""

    def __init__(self, missing: List[str]):
        self.missing = missing
        super().__init__("필수 입력이 비어 있습니다: " + ", ".join(missing))


class CapitalGainsError(RuntimeError):
    """양도세를 산출할 수 없는 경우. 세금을 0 으로 두지 않는다."""


@dataclass
class SaleResult:
    # 양도차익 안분 (§5.1)
    gain_before_approval: float          # 인가전 양도차익
    gain_after_approval: float           # 인가후 양도차익
    contribution_ratio: float            # 청산금비율
    gain_prior_building: float           # 기존건물분
    gain_contribution: float             # 청산금분
    gain_total: float                    # 총 양도차익 (안분 합계)

    # 장기보유특별공제 (§5.2)
    taxable_ratio: float                 # 과세비율
    taxable_prior: float
    taxable_contribution: float
    long_term_deduction: float

    # 세액 (§5.3)
    taxable_income: float                # 양도소득금액
    tax_base: float                      # 과세표준
    applied_rate: float
    applied_deduction: float
    calculated_tax: float                # 산출세액
    local_income_tax: float
    total_tax: float                     # 양도세총액

    # 매도 내역 (§6.2)
    brokerage_fee: float
    net_cash: float                      # 매도 순현금

    # 화면에 함께 보여줄 사실들
    notes: List[str] = field(default_factory=list)      # 알려야 할 사실
    warnings: List[str] = field(default_factory=list)   # 확인이 필요한 사항
    basis: Dict[str, str] = field(default_factory=dict) # 적용 기준 시점·출처
    is_exempt: bool = False                             # 비과세 여부


def _to_number(value, label: str) -> Optional[float]:
    """빈 값은 None. 숫자가 아니면 예외(조용히 0 으로 만들지 않는다)."""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if s == "":
            return None
        value = s
    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise CapitalGainsError(f"'{label}' 에 숫자가 아닌 값이 들어왔습니다: {value!r}") from e


def compute_sale(raw: Dict, config_path: Optional[str] = None) -> SaleResult:
    """
    매도 관련 입력으로 양도세와 매도 순현금을 산출한다.
    필수 입력이 하나라도 비면 MissingInputError 를 던지고 아무 값도 만들지 않는다.
    """
    cfg = load_tax_config(config_path)
    tax_cfg = cfg["capital_gains_tax"]
    cost_cfg = cfg["transaction_cost"]

    values: Dict[str, Optional[float]] = {}
    missing: List[str] = []
    for key, label in REQUIRED_FIELDS.items():
        v = _to_number(raw.get(key), label)
        if v is None:
            missing.append(label)
        values[key] = v
    if missing:
        raise MissingInputError(missing)

    notes: List[str] = []
    warnings: List[str] = []

    nec = _to_number(raw.get("necessary_expense"), OPTIONAL_FIELDS["necessary_expense"])
    if nec is None:
        nec = 0.0
        notes.append("필요경비 미입력 — 0원으로 계산됨")

    sale = values["sale_price"]
    acq = values["acq_price_prior"]
    right = values["right_value"]
    contrib = values["contribution"]
    supply = values["member_supply_price"]
    mortgage = values["mortgage_balance"]

    if sale <= 0:
        raise CapitalGainsError("매도 예상가가 0 이하입니다.")
    if supply <= 0:
        raise CapitalGainsError("조합원 분양가가 0 이하라 청산금 비율을 구할 수 없습니다.")

    # ── §5.1 양도차익 안분 ──────────────────────────────────
    # NOTE: 취득가액합계 = 종전주택 취득가액 + 부담금.
    #   요청서 §5.1 에 정의되어 있으나 §5.2~5.3 에서 쓰이지 않는다.
    #   아래 안분 합계와 493,358원 차이가 나며(조합원 분양가 != 권리가액 + 부담금),
    #   어느 쪽이 정본인지 세무 확인 중이다. 확인되면 이 값을 쓰도록 바꿔야 하므로
    #   삭제하지 않고 남긴다.
    acq_total = acq + contrib

    gain_before = right - acq
    gain_after = sale - supply - nec

    if gain_before < 0:
        notes.append("인가전 양도차익이 음수입니다 (권리가액 < 종전주택 취득가액) — 0으로 처리")
        gain_before = 0.0
    if gain_after < 0:
        notes.append("인가후 양도차익이 음수입니다 (매도가 < 조합원 분양가) — 0으로 처리")
        gain_after = 0.0

    ratio = contrib / supply
    gain_contrib = gain_after * ratio
    gain_prior = gain_before + gain_after * (1.0 - ratio)
    gain_total = gain_prior + gain_contrib

    # 입력값 내부 불일치. 조용히 넘기면 세무 상담에서 숫자가 맞지 않는다.
    supply_gap = supply - (right + contrib)
    if abs(supply_gap) >= 1:
        warnings.append(
            f"조합원 분양가({supply:,.0f}원)와 권리가액＋부담금({right + contrib:,.0f}원)이 "
            f"{abs(supply_gap):,.0f}원 다릅니다. 입력값 확인이 필요합니다.")

    # ── §5.2 장기보유특별공제 ───────────────────────────────
    exemption_limit = float(tax_cfg["one_house_exemption_limit"])
    warn_over = float(tax_cfg.get("long_term_deduction_warn_over", 0.80))
    for label, rates in (("기존건물분", (values["hold_rate_prior"], values["live_rate_prior"])),
                         ("청산금분", (values["hold_rate_contrib"], values["live_rate_contrib"]))):
        if sum(rates) > warn_over:
            warnings.append(
                f"{label} 공제율 합계가 {sum(rates) * 100:.0f}%로 "
                f"{warn_over * 100:.0f}%를 초과합니다. 확인이 필요합니다.")

    if sale <= exemption_limit:
        taxable_ratio = 0.0
        notes.append(f"매도가가 비과세 기준({exemption_limit / 100000000:.0f}억) 이하라 양도세가 없습니다.")
    else:
        taxable_ratio = (sale - exemption_limit) / sale

    taxable_prior = gain_prior * taxable_ratio
    taxable_contrib = gain_contrib * taxable_ratio
    deduction = (taxable_prior * (values["hold_rate_prior"] + values["live_rate_prior"])
                 + taxable_contrib * (values["hold_rate_contrib"] + values["live_rate_contrib"]))

    # ── §5.3 세액 ───────────────────────────────────────────
    taxable_income = (taxable_prior + taxable_contrib) - deduction
    basic_deduction = float(tax_cfg["basic_deduction"])
    tax_base = max(0.0, taxable_income - basic_deduction)

    if tax_base <= 0:
        applied_rate = applied_ded = calculated = 0.0
    else:
        bracket = find_bracket(tax_cfg["brackets"], tax_base)
        applied_rate = float(bracket["rate"])
        applied_ded = float(bracket["deduction"])
        calculated = max(0.0, tax_base * applied_rate - applied_ded)

    local_tax = calculated * float(tax_cfg["local_income_tax_rate"])
    total_tax = calculated + local_tax

    # ── §6.2 매도 내역 ──────────────────────────────────────
    brokerage = (sale * float(cost_cfg["brokerage_rate_over_1_5b"])
                 * (1.0 + float(cost_cfg["brokerage_vat_rate"])))
    net_cash = sale - brokerage - total_tax - mortgage

    if net_cash < 0:
        warnings.append("매도 순현금이 음수입니다. 대출 잔액과 세금이 매도가를 넘습니다.")

    return SaleResult(
        gain_before_approval=gain_before,
        gain_after_approval=gain_after,
        contribution_ratio=ratio,
        gain_prior_building=gain_prior,
        gain_contribution=gain_contrib,
        gain_total=gain_total,
        taxable_ratio=taxable_ratio,
        taxable_prior=taxable_prior,
        taxable_contribution=taxable_contrib,
        long_term_deduction=deduction,
        taxable_income=taxable_income,
        tax_base=tax_base,
        applied_rate=applied_rate,
        applied_deduction=applied_ded,
        calculated_tax=calculated,
        local_income_tax=local_tax,
        total_tax=total_tax,
        brokerage_fee=brokerage,
        net_cash=net_cash,
        notes=notes,
        warnings=warnings,
        basis={
            "capital_gains_effective_from": str(tax_cfg.get("effective_from", "")),
            "capital_gains_source": str(tax_cfg.get("source", "")),
            "transaction_cost_effective_from": str(cost_cfg.get("effective_from", "")),
        },
        is_exempt=(taxable_ratio == 0.0),
    )
