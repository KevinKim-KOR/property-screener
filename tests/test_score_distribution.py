# tests/test_score_distribution.py
"""
설계서 §19.0 점수 분포 판정 기준 테스트.

기준이 문서에만 있으면 코드와 어긋나도 드러나지 않는다.
개정된 기준(꼬리는 상한 12%만 검사, 하한 없음)을 여기에 고정한다.
"""
import unittest

from pc.verification.score_distribution import (
    evaluate_score_distribution, tail_sampling_sd_pct,
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

    def test_upper_boundary_inclusive(self):
        # 정확히 12% 는 정상, 그 위는 위반
        res = evaluate_score_distribution(_scores(200, 24, 24))
        self.assertTrue(res.all_ok, "12%에서 위반 처리됨")
        res = evaluate_score_distribution(_scores(200, 26, 26))
        self.assertFalse(res.all_ok, "13%인데 통과됨")

    def test_empty_returns_none(self):
        self.assertIsNone(evaluate_score_distribution([]))

    def test_sampling_sd_shrinks_with_n(self):
        self.assertGreater(tail_sampling_sd_pct(100), tail_sampling_sd_pct(1000))


if __name__ == "__main__":
    unittest.main()
