# tests/test_capital_gains.py
"""
개발요청서 매수여력_판정_v1.0 §8 검증 케이스.
Phase 1 범위: 케이스 1(양도세·가용자금)과 케이스 5(비과세).

값이 바뀌면 실패해야 한다.
"""
import unittest

from pc.finance.capital_gains import (
    CapitalGainsError, MissingInputError, compute_sale,
)

COMMON = {
    "acq_price_prior": 343_500_000,
    "right_value": 431_139_690,
    "contribution": 271_916_952,
    "member_supply_price": 703_550_000,
    "necessary_expense": 0,
    "mortgage_balance": 90_000_000,
    "hold_rate_prior": 0.40,
    "live_rate_prior": 0.20,
    "hold_rate_contrib": 0.40,
    "live_rate_contrib": 0.08,
}
CASH_ON_HAND = 70_000_000


class TestCase1(unittest.TestCase):
    """케이스 1: 매도가 25.5억, 추가자금 0"""

    def setUp(self):
        self.res = compute_sale({**COMMON, "sale_price": 2_550_000_000})

    def test_total_tax(self):
        # 기대 170,600,000 (오차 ±1,000,000)
        self.assertAlmostEqual(self.res.total_tax, 170_600_000, delta=1_000_000)

    def test_available_funds(self):
        # 가용자금 = 매도순현금 + 보유현금 (추가자금 0)
        available = self.res.net_cash + CASH_ON_HAND
        self.assertAlmostEqual(available, 2_339_800_000, delta=1_000_000)

    def test_not_exempt(self):
        self.assertFalse(self.res.is_exempt)

    def test_bracket_is_40_percent(self):
        self.assertAlmostEqual(self.res.applied_rate, 0.40, places=6)

    def test_reports_supply_price_mismatch(self):
        # 조합원 분양가 != 권리가액 + 부담금. 조용히 넘기지 않는다.
        self.assertTrue(any("조합원 분양가" in w for w in self.res.warnings),
                        self.res.warnings)


class TestCase5(unittest.TestCase):
    """케이스 5: 매도가 11억 -> 비과세"""

    def setUp(self):
        self.res = compute_sale({**COMMON, "sale_price": 1_100_000_000})

    def test_tax_is_zero(self):
        self.assertEqual(self.res.total_tax, 0.0)

    def test_marked_exempt(self):
        self.assertTrue(self.res.is_exempt)
        self.assertTrue(any("비과세" in n for n in self.res.notes), self.res.notes)


class TestInputHandling(unittest.TestCase):
    def test_missing_required_stops_calculation(self):
        data = {**COMMON, "sale_price": 2_550_000_000}
        del data["right_value"]
        with self.assertRaises(MissingInputError) as ctx:
            compute_sale(data)
        self.assertIn("권리가액", ctx.exception.missing)

    def test_empty_string_is_missing_not_zero(self):
        data = {**COMMON, "sale_price": 2_550_000_000, "mortgage_balance": ""}
        with self.assertRaises(MissingInputError):
            compute_sale(data)

    def test_missing_optional_is_noted(self):
        data = {**COMMON, "sale_price": 2_550_000_000}
        data.pop("necessary_expense")
        res = compute_sale(data)
        self.assertTrue(any("필요경비" in n for n in res.notes), res.notes)

    def test_non_numeric_raises(self):
        data = {**COMMON, "sale_price": "스물다섯억"}
        with self.assertRaises(CapitalGainsError):
            compute_sale(data)


class TestEdgeCases(unittest.TestCase):
    def test_negative_gain_after_is_clamped_and_reported(self):
        # 매도가(6억) < 조합원 분양가(7.03억) -> 인가후 양도차익이 음수
        res = compute_sale({**COMMON, "sale_price": 600_000_000})
        self.assertEqual(res.gain_after_approval, 0.0)
        self.assertTrue(any("인가후 양도차익이 음수" in n for n in res.notes), res.notes)

    def test_long_term_deduction_over_limit_warns_but_computes(self):
        res = compute_sale({**COMMON, "sale_price": 2_550_000_000,
                            "hold_rate_prior": 0.50, "live_rate_prior": 0.50})
        self.assertTrue(any("80%" in w for w in res.warnings), res.warnings)
        self.assertIsNotNone(res.total_tax)   # 막지 않는다

    def test_case1_rates_do_not_warn(self):
        res = compute_sale({**COMMON, "sale_price": 2_550_000_000})
        self.assertFalse(any("공제율" in w for w in res.warnings), res.warnings)


if __name__ == "__main__":
    unittest.main()
