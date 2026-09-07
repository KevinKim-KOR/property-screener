# tests/test_purchase_capacity.py
"""
개발요청서 §5.4 구간 탐색 검증. 케이스 1~4.

핵심은 케이스 4다. 대출 한도가 매수가 구간에 따라 계단식으로 바뀌므로
단순 역산으로 구현하면 추가자금이 그대로 상한 증가로 이어진다.
1억을 더 넣었을 때 증가폭이 1억보다 작아야 맞다.
"""
import unittest

from pc.finance.capital_gains import compute_sale
from pc.finance.purchase_capacity import (
    compute_capacity, cost_rate_for, evaluate_price,
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
CASH = 70_000_000
AREA_OVER_85 = False


def available_with(extra: int) -> float:
    res = compute_sale({**COMMON, "sale_price": 2_550_000_000})
    return res.net_cash + CASH + extra


class TestCostRate(unittest.TestCase):
    def test_rates_from_config(self):
        # 85㎡ 이하 4.07%, 초과 4.27%
        self.assertAlmostEqual(cost_rate_for(False), 0.0407, places=6)
        self.assertAlmostEqual(cost_rate_for(True), 0.0427, places=6)


class TestCase1(unittest.TestCase):
    """추가자금 0 -> 25.0억 구간 상단"""

    def test_max_price(self):
        res = compute_capacity(available_with(0), AREA_OVER_85)
        # 구간 상단은 (상한 - 1원) 으로 잡는다(§5.4 3항)
        self.assertAlmostEqual(res.max_price, 2_500_000_000, delta=1)

    def test_loan_and_own_funds(self):
        res = compute_capacity(available_with(0), AREA_OVER_85)
        self.assertIsNotNone(res.loan_at_max)
        self.assertLessEqual(res.own_funds_needed, res.available_funds + 1)


class TestCase2(unittest.TestCase):
    """추가자금 1억"""

    def test_max_price(self):
        res = compute_capacity(available_with(100_000_000), AREA_OVER_85)
        self.assertAlmostEqual(res.max_price, 2_536_000_000, delta=5_000_000)


class TestCase3(unittest.TestCase):
    """추가자금 2억"""

    def test_max_price(self):
        res = compute_capacity(available_with(200_000_000), AREA_OVER_85)
        self.assertAlmostEqual(res.max_price, 2_633_000_000, delta=5_000_000)


class TestCase4Boundary(unittest.TestCase):
    """경계 검증 — 계단 구조가 실제로 나타나는지"""

    def test_boundary_at_2_5b(self):
        """
        구간은 [하한, 상한) 이므로 정확히 25.0억은 세 번째 구간이다.
        그 순간 대출 한도가 4억에서 2억으로 줄어 감당할 수 없게 된다.
        계단이 여기서 생긴다.
        """
        av = available_with(0)
        self.assertTrue(evaluate_price(2_499_999_999, av, AREA_OVER_85)["feasible"],
                        "25.0억 바로 아래는 가능해야 한다(두 번째 구간, 한도 4억)")
        self.assertFalse(evaluate_price(2_500_000_000, av, AREA_OVER_85)["feasible"],
                         "정확히 25.0억은 세 번째 구간이라 한도가 2억으로 줄어 불가")
        self.assertFalse(evaluate_price(2_550_000_000, av, AREA_OVER_85)["feasible"])

    def test_loan_drops_at_boundary(self):
        av = available_with(0)
        below = evaluate_price(2_499_999_999, av, AREA_OVER_85)["loan"]
        above = evaluate_price(2_500_000_000, av, AREA_OVER_85)["loan"]
        self.assertEqual(below, 400_000_000)
        self.assertEqual(above, 200_000_000)

    def test_extra_100m_raises_cap_by_less_than_100m(self):
        # 단순 역산이면 증가폭이 1억에 가깝게 나온다. 계단 때문에 그보다 작아야 한다.
        base = compute_capacity(available_with(0), AREA_OVER_85).max_price
        more = compute_capacity(available_with(100_000_000), AREA_OVER_85).max_price
        increase = more - base
        self.assertGreater(increase, 0)
        self.assertLess(increase, 100_000_000,
                        f"증가폭 {increase:,.0f}원이 추가자금과 같다. 구간 탐색이 아니라 단순 역산일 수 있다.")

    def test_increase_is_not_uniform(self):
        # 계단 구조라 증가폭이 균등하지 않다.
        caps = [compute_capacity(available_with(e), AREA_OVER_85).max_price
                for e in (0, 100_000_000, 200_000_000)]
        first, second = caps[1] - caps[0], caps[2] - caps[1]
        self.assertNotAlmostEqual(first, second, delta=1_000_000)

    def test_bracket_boundary_rows(self):
        av = available_with(0)
        for price in (2_490_000_000, 2_500_000_000, 2_510_000_000):
            row = evaluate_price(price, av, AREA_OVER_85)
            self.assertIn("feasible", row)


class TestNoAffordableBracket(unittest.TestCase):
    def test_returns_none_not_approximation(self):
        # 가용자금이 없으면 근사값을 만들지 않고 None 을 돌려준다.
        res = compute_capacity(0, AREA_OVER_85)
        self.assertIsNone(res.max_price)
        self.assertTrue(any("없습니다" in n for n in res.notes), res.notes)


if __name__ == "__main__":
    unittest.main()
