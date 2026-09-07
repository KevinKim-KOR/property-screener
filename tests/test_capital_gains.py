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
        # 기대 170,591,291 (오차 ±10,000)
        # 허용 오차를 좁혔다. 계산이 결정론적이라 느슨할 이유가 없고,
        # 옛 ±100만원 기준은 조합원 분양가 오적용(493,358원 차이)을 그냥 통과시켰다.
        self.assertAlmostEqual(self.res.total_tax, 170_591_291, delta=10_000)

    def test_available_funds(self):
        # 가용자금 = 매도순현금 + 보유현금 (추가자금 0)
        available = self.res.net_cash + CASH_ON_HAND
        self.assertAlmostEqual(available, 2_339_773_709, delta=10_000)

    def test_not_exempt(self):
        self.assertFalse(self.res.is_exempt)

    def test_bracket_is_40_percent(self):
        self.assertAlmostEqual(self.res.applied_rate, 0.40, places=6)

    def test_reports_supply_price_mismatch(self):
        # 조합원 분양가는 계산에 쓰지 않지만, 권리가액＋부담금과 다르면 경고한다.
        self.assertTrue(any("조합원 분양가" in w for w in self.res.warnings),
                        self.res.warnings)

    def test_supply_price_does_not_affect_result(self):
        # 조합원 분양가를 바꿔도 세액이 달라지지 않아야 한다(계산 경로에서 제외).
        other = compute_sale({**COMMON, "sale_price": 2_550_000_000,
                              "member_supply_price": 999_999_999})
        self.assertAlmostEqual(other.total_tax, self.res.total_tax, delta=0.01)


class TestCase5(unittest.TestCase):
    """케이스 5: 매도가 11억 -> 비과세"""

    def setUp(self):
        self.res = compute_sale({**COMMON, "sale_price": 1_100_000_000})

    def test_tax_is_zero(self):
        self.assertEqual(self.res.total_tax, 0.0)

    def test_marked_exempt(self):
        self.assertTrue(self.res.is_exempt)
        self.assertTrue(any("비과세" in n for n in self.res.notes), self.res.notes)


class TestCase6Identity(unittest.TestCase):
    """케이스 6: 안분 항등식. 1원이라도 벌어지면 실패."""

    def test_identity_holds(self):
        for sale in (2_550_000_000, 1_500_000_000, 3_000_000_000, 800_000_000):
            with self.subTest(sale=sale):
                res = compute_sale({**COMMON, "sale_price": sale})
                if any("음수" in n for n in res.notes):
                    continue   # 음수 절사가 있으면 항등식이 성립하지 않는다
                expected = sale - (COMMON["acq_price_prior"] + COMMON["contribution"]) \
                           - COMMON["necessary_expense"]
                self.assertAlmostEqual(
                    res.gain_prior_building + res.gain_contribution, expected, delta=1.0,
                    msg=f"매도가 {sale:,} 에서 안분 합계가 취득가액 기준과 어긋남")

    def test_identity_with_necessary_expense(self):
        res = compute_sale({**COMMON, "sale_price": 2_550_000_000,
                            "necessary_expense": 30_000_000})
        expected = 2_550_000_000 - (COMMON["acq_price_prior"] + COMMON["contribution"]) - 30_000_000
        self.assertAlmostEqual(res.gain_prior_building + res.gain_contribution,
                               expected, delta=1.0)


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

    def test_deduction_over_combined_limit_stops(self):
        # 합계 80% 초과 -> 자동으로 잘라내지 않고 중단한다.
        with self.assertRaises(CapitalGainsError) as ctx:
            compute_sale({**COMMON, "sale_price": 2_550_000_000,
                          "hold_rate_prior": 0.40, "live_rate_prior": 0.41})
        self.assertIn("합계", str(ctx.exception))

    def test_deduction_over_individual_limit_stops(self):
        with self.assertRaises(CapitalGainsError) as ctx:
            compute_sale({**COMMON, "sale_price": 2_550_000_000, "hold_rate_prior": 0.45})
        self.assertIn("보유공제율", str(ctx.exception))

    def test_negative_deduction_rate_stops(self):
        with self.assertRaises(CapitalGainsError):
            compute_sale({**COMMON, "sale_price": 2_550_000_000, "live_rate_contrib": -0.01})

    def test_deduction_at_limit_is_allowed(self):
        res = compute_sale({**COMMON, "sale_price": 2_550_000_000,
                            "hold_rate_prior": 0.40, "live_rate_prior": 0.40})
        self.assertGreater(res.long_term_deduction, 0)

    def test_case1_rates_pass_limits(self):
        res = compute_sale({**COMMON, "sale_price": 2_550_000_000})
        self.assertFalse(any("공제율" in w for w in res.warnings), res.warnings)


if __name__ == "__main__":
    unittest.main()
