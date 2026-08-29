# tests/test_date_window.py
"""
기간 창 계산 및 하드코딩 날짜 재유입 방지.

build_stats.py 가 창 시작일을 고정 문자열로 두고 있어 '3개월 창'이 실제
3.9개월치가 되어 있었다(2026-08-27 기준). 아무 신호도 나지 않았고, 시간이
갈수록 조용히 나빠지는 종류였다. 같은 게 다시 들어오는 것을 막는다.
"""
import pathlib
import re
import unittest

from common.date_window import window_start, months_between, years_between

SRC_ROOT = pathlib.Path(__file__).resolve().parent.parent
# 날짜를 다루는 것이 본업이거나, 문서/예시로 날짜가 필요한 파일은 제외한다.
ALLOWED = {
    "common/date_window.py",       # 이 모듈이 날짜 계산의 유일한 출처
    "oci/crawler/molit_schema.py", # docstring 의 변환 예시
}
DATE_LITERAL = re.compile(r"""['"]20\d{2}-\d{2}-\d{2}['"]""")


class TestWindowStart(unittest.TestCase):
    def test_basic_months(self):
        self.assertEqual(window_start("2026-08-27", 3), "2026-05-27")
        self.assertEqual(window_start("2026-08-27", 6), "2026-02-27")
        self.assertEqual(window_start("2026-08-27", 12), "2025-08-27")
        self.assertEqual(window_start("2026-08-27", 24), "2024-08-27")

    def test_zero_months_is_base_date(self):
        self.assertEqual(window_start("2026-08-27", 0), "2026-08-27")

    def test_month_end_clamped(self):
        self.assertEqual(window_start("2026-03-31", 1), "2026-02-28")
        self.assertEqual(window_start("2024-03-31", 1), "2024-02-29")   # 윤년
        self.assertEqual(window_start("2026-05-31", 1), "2026-04-30")

    def test_year_boundary(self):
        self.assertEqual(window_start("2026-01-15", 1), "2025-12-15")
        self.assertEqual(window_start("2026-01-15", 13), "2024-12-15")

    def test_window_width_is_exact(self):
        # 창 폭이 라벨과 일치해야 한다. 이게 틀렸던 것이 이번 문제였다.
        for m in (3, 6, 12, 24):
            width = months_between(window_start("2026-08-27", m), "2026-08-27")
            self.assertAlmostEqual(width, m, places=6,
                                   msg=f"{m}개월 창의 실제 폭이 {width:.2f}개월")

    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            window_start("2026/08/27", 3)
        with self.assertRaises(ValueError):
            window_start("2026-08-27", -1)

    def test_years_between(self):
        self.assertAlmostEqual(years_between("2016-01-01", "2026-01-01"), 10.0, places=6)


class TestNoHardcodedDates(unittest.TestCase):
    def test_source_has_no_date_literals(self):
        """
        소스에 'YYYY-MM-DD' 리터럴이 있으면 실패한다.
        기간 계산은 common.date_window.window_start() 를 쓴다.
        (테스트 코드에서 기준일을 명시하는 것은 의도된 사용이라 검사 대상이 아니다.)
        """
        offenders = []
        for pkg in ("common", "pc", "oci"):
            for path in sorted((SRC_ROOT / pkg).rglob("*.py")):
                rel = path.relative_to(SRC_ROOT).as_posix()
                if rel in ALLOWED:
                    continue
                for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if DATE_LITERAL.search(line):
                        offenders.append(f"{rel}:{lineno}: {line.strip()[:90]}")
        self.assertEqual(
            offenders, [],
            "소스에 하드코딩된 날짜가 있습니다. common.date_window.window_start() 를 쓰세요:\n  "
            + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()
