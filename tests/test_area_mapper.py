# tests/test_area_mapper.py
import unittest
from common.area_mapper import to_area_type, pyeong_to_area_type

class TestAreaMapper(unittest.TestCase):
    def test_to_area_type_boundary_cases(self):
        # 미달 (< 33.0)
        self.assertIsNone(to_area_type(32.99))
        self.assertIsNone(to_area_type(0.0))
        self.assertIsNone(to_area_type(None))

        # A40 : 33.0 <= x < 50.0
        self.assertEqual(to_area_type(33.0), "A40")
        self.assertEqual(to_area_type(49.99), "A40")

        # A59 : 50.0 <= x < 70.0
        self.assertEqual(to_area_type(50.0), "A59")
        self.assertEqual(to_area_type(59.99), "A59")
        self.assertEqual(to_area_type(69.99), "A59")

        # A84 : 70.0 <= x < 100.0
        self.assertEqual(to_area_type(70.0), "A84")
        self.assertEqual(to_area_type(84.93), "A84")
        self.assertEqual(to_area_type(99.99), "A84")

        # A114 : 100.0 <= x < 135.0
        self.assertEqual(to_area_type(100.0), "A114")
        self.assertEqual(to_area_type(114.5), "A114")
        self.assertEqual(to_area_type(134.99), "A114")

        # A135P : 135.0 <= x
        self.assertEqual(to_area_type(135.0), "A135P")
        self.assertEqual(to_area_type(200.0), "A135P")

    def test_pyeong_to_area_type_fallback(self):
        self.assertEqual(pyeong_to_area_type("20PY"), "A59")
        self.assertEqual(pyeong_to_area_type("30PY"), "A84")
        self.assertEqual(pyeong_to_area_type("40PY"), "A114")
        self.assertEqual(pyeong_to_area_type("20평형대"), "A59")
        self.assertIsNone(pyeong_to_area_type(None))

if __name__ == "__main__":
    unittest.main()
