# common/tax_config.py
"""
세제·대출 규제 파라미터 로더.

세율과 한도를 코드에 직접 쓰지 않는다. config/tax_and_loan.yaml 한 곳에서만
읽고, 각 항목의 시행일과 출처를 함께 들고 다닌다. 화면에 어느 시점 기준으로
계산했는지 표시하기 위해서다.
"""
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

_BASE_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _BASE_DIR / "config" / "tax_and_loan.yaml"


class TaxConfigError(RuntimeError):
    """세제·대출 설정을 읽지 못한 경우. 기본값으로 대체하지 않는다."""


_cache: Optional[Dict] = None


def load_tax_config(path: Optional[str] = None) -> Dict:
    """
    설정을 읽는다. 없거나 비어 있으면 예외를 던진다.
    설정 없이 기본값으로 계산하면 어떤 기준으로 나온 세금인지 알 수 없다.
    """
    global _cache
    p = Path(path) if path else _CONFIG_PATH
    if path is None and _cache is not None:
        return _cache

    if not os.path.exists(p):
        raise TaxConfigError(f"세제·대출 설정 파일을 찾을 수 없습니다: {p}")
    try:
        with open(p, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except Exception as e:
        raise TaxConfigError(f"세제·대출 설정을 읽을 수 없습니다: {p} ({e})") from e
    if not cfg:
        raise TaxConfigError(f"세제·대출 설정이 비어 있습니다: {p}")

    for key in ("capital_gains_tax", "transaction_cost"):
        if key not in cfg:
            raise TaxConfigError(f"세제·대출 설정에 '{key}' 항목이 없습니다: {p}")

    if path is None:
        _cache = cfg
    return cfg


def find_bracket(brackets: List[Dict], amount: float) -> Dict:
    """금액이 속한 구간을 찾는다. 못 찾으면 예외(조용히 0을 쓰지 않는다)."""
    for b in brackets:
        lo = b.get("min", 0) or 0
        hi = b.get("max")
        if amount >= lo and (hi is None or amount < hi):
            return b
    raise TaxConfigError(f"금액 {amount:,.0f} 에 해당하는 구간을 설정에서 찾지 못했습니다.")


def config_basis() -> Tuple[str, str]:
    """화면에 표시할 '기준 시점' 문구용. (양도세 시행일, 대출 시행일)"""
    cfg = load_tax_config()
    return (str(cfg["capital_gains_tax"].get("effective_from", "")),
            str(cfg.get("loan_limit", {}).get("effective_from", "")))
