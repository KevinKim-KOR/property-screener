# tests/test_peak_detector.py
import unittest
from pc.features.peak_detector import (
    calculate_percentile,
    calculate_months_elapsed,
    compute_decay_factor,
    detect_robust_peak,
    DECAY_TAU,
    DECAY_FLOOR
)

class TestPeakDetector(unittest.TestCase):
    def test_percentile(self):
        vals = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0, 180.0, 200.0]
        p90 = calculate_percentile(vals, 0.90)
        self.assertAlmostEqual(p90, 182.0, places=1)

    def test_decay_factor_bounds(self):
        self.assertEqual(compute_decay_factor(0.0), 1.0)
        # 36개월 경과 시 반감기 0.5 이지만 FLOOR=0.80 이므로 0.80 클램핑
        self.assertEqual(compute_decay_factor(36.0), 0.80)
        # 12개월 경과 시: 0.5**(12/36) = 0.5**(1/3) = ~0.793 -> FLOOR=0.80 클램핑
        # 6개월 경과 시: 0.5**(6/36) = 0.5**(1/6) = ~0.8909
        df_6m = compute_decay_factor(6.0)
        self.assertGreater(df_6m, 0.80)
        self.assertLess(df_6m, 1.0)

    def test_detect_robust_peak(self):
        trades = [
            {"deal_date": "2024-01-15", "deal_amount": 150000},
            {"deal_date": "2025-01-15", "deal_amount": 180000},
            {"deal_date": "2026-01-15", "deal_amount": 200000}, # peak candidate
            {"deal_date": "2026-06-15", "deal_amount": 170000},
        ]
        raw, adj, date_str, factor = detect_robust_peak(trades, base_date="2026-07-29")
        self.assertGreater(raw, 0.0)
        self.assertGreaterEqual(raw, adj)
        self.assertIsNotNone(date_str)

if __name__ == "__main__":
    unittest.main()
