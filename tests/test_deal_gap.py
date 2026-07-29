# tests/test_deal_gap.py
import unittest
from pc.l2.deal_gap import classify_floor_grade, calculate_deal_gap, update_all_properties_l2
from common.database import init_db

class TestDealGap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_classify_floor_grade(self):
        self.assertEqual(classify_floor_grade("1층"), ("LOW", 0.95))
        self.assertEqual(classify_floor_grade("지하1층"), ("LOW", 0.95))
        self.assertEqual(classify_floor_grade("로열층"), ("HIGH", 1.03))
        self.assertEqual(classify_floor_grade("20층"), ("HIGH", 1.03))
        self.assertEqual(classify_floor_grade("8층"), ("MID", 1.00))

    def test_calculate_deal_gap(self):
        # 호가 200,000 / 3M중위 180,000 / MID(1.00) => (200000 - 180000)/180000 = +11.11%
        gap = calculate_deal_gap(200000, 180000, 1.00)
        self.assertAlmostEqual(gap, 11.11, places=2)

    def test_update_all_properties_l2(self):
        cnt = update_all_properties_l2("2026-07-29")
        self.assertGreaterEqual(cnt, 0)

if __name__ == "__main__":
    unittest.main()
