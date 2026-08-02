# tests/test_area_mapper.py
import unittest
from common.area_mapper import to_area_type, pyeong_to_area_type

class TestAreaMapper(unittest.TestCase):
    def test_to_area_type_boundary_cases(self):
        # 미달 (< 50.0) 또는 초과 (>= 135.0)
        self.assertIsNone(to_area_type(49.99))
        self.assertIsNone(to_area_type(0.0))
        self.assertIsNone(to_area_type(None))
        self.assertIsNone(to_area_type(135.0))
        self.assertIsNone(to_area_type(200.0))

        # 50~55
        self.assertEqual(to_area_type(50.0), "A50_55")
        self.assertEqual(to_area_type(54.99), "A50_55")

        # 55~60
        self.assertEqual(to_area_type(59.96), "A55_60")

        # 80~85
        self.assertEqual(to_area_type(84.93), "A80_85")

        # 95~100
        self.assertEqual(to_area_type(99.99), "A95_100")

        # 100~105
        self.assertEqual(to_area_type(100.0), "A100_105")

        # 130~135
        self.assertEqual(to_area_type(134.99), "A130_135")

    def test_pyeong_to_area_type_fallback(self):
        self.assertEqual(pyeong_to_area_type("20PY"), "A55_60")
        self.assertEqual(pyeong_to_area_type("30PY"), "A80_85")
        self.assertEqual(pyeong_to_area_type("40PY"), "A110_115")
        self.assertEqual(pyeong_to_area_type("20평형대"), "A55_60")
        self.assertIsNone(pyeong_to_area_type(None))

if __name__ == "__main__":
    unittest.main()
