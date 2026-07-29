# tests/test_scorer_v3.py
"""
SCORING_V3_DESIGN.md §12.1, P1-AC10, P1-AC11:
V3 공식 스코어링 모듈 단위 및 통합 테스트.
"""
import unittest
import os
import sqlite3
from pc.scoring.scorer_v3 import run_scoring, load_scoring_v3_config, ScoreRunResult
from common.database import get_db_connection

class TestScorerV3(unittest.TestCase):
    def test_load_scoring_v3_config(self):
        """V3 YAML config 동적 로드 검증 (C2)"""
        cfg = load_scoring_v3_config("config/scoring_v3.yaml")
        self.assertEqual(cfg.get("version"), "3.0.0")
        self.assertEqual(cfg["universe"]["target_sgg"], ["11650", "11680"])
        self.assertIn("value", cfg["blocks"])
        self.assertIn("flow", cfg["blocks"])
        self.assertIn("location", cfg["blocks"])
        self.assertIn("quality", cfg["blocks"])

    def test_run_scoring_pipeline(self):
        """run_scoring 실행 및 ScoreRunResult 반환, DB 적재 검증"""
        res = run_scoring("2026-07-29")
        self.assertIsInstance(res, ScoreRunResult)
        self.assertTrue(res.run_id.startswith("RUN_"))
        self.assertEqual(res.universe_total, res.universe_passed + sum(res.excluded_by_reason.values()))

        # DB 검증
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT scorer_version, universe_total, universe_passed FROM score_runs WHERE run_id = ?", (res.run_id,))
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["scorer_version"], "3.0.0")
            self.assertEqual(row["universe_total"], res.universe_total)
            self.assertEqual(row["universe_passed"], res.universe_passed)

            # market_scores 레코드 수 검증
            cur.execute("SELECT COUNT(*) as cnt FROM market_scores WHERE run_id = ?", (res.run_id,))
            ms_row = cur.fetchone()
            self.assertEqual(ms_row["cnt"], res.universe_total)

if __name__ == "__main__":
    unittest.main()
