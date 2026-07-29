# tests/test_scorer_v2.py
import unittest
import sqlite3
from common.database import init_db, Config
from pc.scoring.normalizer import normalize_block_a
from pc.scoring.aggregator import aggregate_blocks, calculate_normal_cdf
from pc.scoring.scorer_v2 import run_l1_scoring_v2

class TestScorerV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_normal_cdf(self):
        self.assertAlmostEqual(calculate_normal_cdf(0.0), 0.5, places=3)
        self.assertGreater(calculate_normal_cdf(1.0), 0.8)

    def test_aggregate_blocks(self):
        blocks = {"A": 1.0, "B": 1.0, "C": 0.5, "D": 0.5}
        raw, base, market = aggregate_blocks(blocks, 1.0)
        self.assertGreater(raw, 0.0)
        self.assertGreaterEqual(base, 50.0)
        self.assertGreaterEqual(market, 50.0)

    def test_run_l1_scoring_v2(self):
        res = run_l1_scoring_v2("2026-07-29")
        self.assertIn("run_id", res)
        self.assertIn("universe_total", res)
        print(f"\n[ScorerV2 TestResult] {res}")

        # DB 검증
        db_path = Config.get_db_path()
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM market_scores WHERE run_id = ?", (res["run_id"],))
            cnt = cur.fetchone()[0]
            self.assertEqual(cnt, res["universe_total"])

if __name__ == "__main__":
    unittest.main()
