# tests/test_score_distribution.py
"""
설계서 §19.0 점수 분포 판정 기준 테스트.

기준이 문서에만 있으면 코드와 어긋나도 드러나지 않는다.
개정된 기준(꼬리는 상한만, 상한은 표본 수에 연동)을 여기에 고정한다.
"""
import unittest

from pc.verification.score_distribution import (
    evaluate_score_distribution, tail_cap_pct, tail_sampling_sd_pct,
)


def _scores(n, low, high, mid=50.0):
    """하위 low개 / 상위 high개 / 나머지는 중앙값 근처인 점수 목록."""
    out = [1.0] * low + [99.0] * high
    out += [mid] * (n - low - high)
    return out


class TestScoreDistribution(unittest.TestCase):
    def test_normal_uniform_like(self):
        # Φ 매핑이 만드는 균등분포: 양쪽 꼬리 10%
        res = evaluate_score_distribution(_scores(200, 20, 20))
        self.assertTrue(res.all_ok, [c.label for c in res.failures()])

    def test_median_out_of_range(self):
        res = evaluate_score_distribution([20.0] * 100)
        labels = [c.label for c in res.failures()]
        self.assertIn("중간 점수", labels)

    def test_median_tolerance_is_five(self):
        # (2026-08-28 개정) 허용폭 50±5. 붕괴 검출은 V10 과 꼬리 비율이 담당하며,
        # 중앙값은 Φ 매핑 특성상 원점수가 치우치면 50 에서 벗어난다.
        # 옛 허용폭(50±3)은 기간 창을 바로잡은 정상 실행(중앙값 46.6)을 반려했다.
        for med in (45.0, 46.6, 50.0, 55.0):
            res = evaluate_score_distribution([med] * 100)
            self.assertTrue(res.all_ok, f"중앙값 {med} 가 위반 처리됨")
        for med in (44.9, 55.1):
            res = evaluate_score_distribution([med] * 100)
            self.assertIn("중간 점수", [c.label for c in res.failures()],
                          f"중앙값 {med} 가 통과됨")

    def test_thin_tail_is_not_a_violation(self):
        # 꼬리가 얇은 것은 문제가 아니다. 하한을 두면 표본이 작을 때
        # 정상 실행이 위반으로 찍힌다(181건이면 흔들림이 약 2.2%p).
        res = evaluate_score_distribution(_scores(200, 2, 2))
        self.assertTrue(res.all_ok, [c.label for c in res.failures()])

    def test_thin_tail_real_case(self):
        # 실제 관측값: 채점 181곳, 10점 이하 12곳(6.6%) -> 정상이어야 한다
        res = evaluate_score_distribution(_scores(181, 12, 15))
        self.assertTrue(res.all_ok, [c.label for c in res.failures()])

    def test_tail_too_fat_is_flagged(self):
        res = evaluate_score_distribution(_scores(200, 40, 40))
        labels = [c.label for c in res.failures()]
        self.assertIn("90점 이상", labels)
        self.assertIn("10점 이하", labels)

    def test_cap_tightens_as_sample_grows(self):
        # 표본이 늘면 상한이 좁혀진다. 고정값이면 표본이 적을 때 계속 걸린다.
        self.assertGreater(tail_cap_pct(50), tail_cap_pct(167))
        self.assertGreater(tail_cap_pct(167), tail_cap_pct(1000))
        self.assertAlmostEqual(tail_cap_pct(167), 16.6, delta=0.1)
        self.assertAlmostEqual(tail_cap_pct(1000), 13.9, delta=0.1)

    def test_upper_boundary_uses_dynamic_cap(self):
        n = 200
        cap = tail_cap_pct(n)                    # 200곳이면 약 16.2%
        under = int(n * (cap - 1) / 100)
        over = int(n * (cap + 2) / 100) + 1
        self.assertTrue(evaluate_score_distribution(_scores(n, under, under)).all_ok,
                        f"상한({cap:.1f}%) 아래인데 위반 처리됨")
        self.assertFalse(evaluate_score_distribution(_scores(n, over, over)).all_ok,
                         f"상한({cap:.1f}%)을 넘었는데 통과됨")

    def test_observed_case_passes(self):
        # 실측: 채점 167곳, 90점 이상 21곳(12.6%) -> 상한 16.6% 이내
        res = evaluate_score_distribution(_scores(167, 10, 21))
        self.assertTrue(res.all_ok, [c.label for c in res.failures()])

    def test_empty_returns_none(self):
        self.assertIsNone(evaluate_score_distribution([]))

    def test_sampling_sd_shrinks_with_n(self):
        self.assertGreater(tail_sampling_sd_pct(100), tail_sampling_sd_pct(1000))


if __name__ == "__main__":
    unittest.main()
