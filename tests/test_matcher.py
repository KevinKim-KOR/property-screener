# tests/test_matcher.py
import unittest
from common.database import init_db
from pc.keymap.matcher import normalize_apt_name, normalize_road_name, ComplexMatcher, run_complex_matching

class TestMatcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_normalize_functions(self):
        self.assertEqual(normalize_apt_name("반포자이(아파트)"), "반포자이")
        self.assertEqual(normalize_apt_name("서초 1차 래미안"), "서초1래미안")
        self.assertEqual(normalize_road_name("방배로 73"), "방배로73")

    def test_run_complex_matching(self):
        stats = run_complex_matching()
        self.assertIn("total", stats)
        self.assertIn("matched", stats)
        self.assertIn("unmatched", stats)
        self.assertGreaterEqual(stats["total"], 0)

if __name__ == "__main__":
    unittest.main()
