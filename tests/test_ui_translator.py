# tests/test_ui_translator.py
"""
SCORING_V3.1_DESIGN.md §16.3 및 §16.2 UI 표기 변환 / 결정론적 문장 생성 단위 테스트
"""
import unittest
from pc.scoring.ui_translator import (
    translate_area_type,
    translate_price_interpretation,
    generate_strength_sentence,
    generate_caution_sentence,
    translate_exclusion_reason,
)


class TestUITranslator(unittest.TestCase):
    def test_translate_area_type(self):
        self.assertEqual(translate_area_type("A84"), "34평형 · 전용 84㎡")
        self.assertEqual(translate_area_type("A59"), "25평형 · 전용 59㎡")
        self.assertEqual(translate_area_type("A114"), "44평형 · 전용 114㎡")
        self.assertEqual(translate_area_type("UNKNOWN"), "34평형 · 전용 84㎡")

    def test_translate_price_interpretation(self):
        # 호가 80000(8억), 실거래중위 86500(8.65억) -> 0.65억 낮음 (갭 > 3%)
        msg = translate_price_interpretation(80000, 86500)
        self.assertIn("0.7억 낮은 호가입니다", msg)

        # 호가 90500(9.05억), 실거래중위 86500(8.65억) -> 0.40억 높음 (갭 < -3%)
        msg2 = translate_price_interpretation(90500, 86500)
        self.assertIn("0.4억 높은 호가입니다", msg2)

        # 호가 86000, 실거래중위 86500 -> 3% 이내
        msg3 = translate_price_interpretation(86000, 86500)
        self.assertIn("실거래와 비슷한 호가입니다", msg3)

    def test_generate_strength_sentence(self):
        # 1우선순위: excess_drop_rate >= 0.05 and volume_ratio > 1.0
        res1 = generate_strength_sentence({"excess_drop_rate": 0.06, "volume_ratio": 1.1})
        self.assertEqual(res1, "강남권 평균보다 6.0%p 더 떨어졌는데, 거래량은 회복 중입니다")

        # 3우선순위: jeonse_ratio >= 0.55
        res3 = generate_strength_sentence({"excess_drop_rate": 0.01, "volume_ratio": 0.9, "jeonse_ratio": 0.60})
        self.assertEqual(res3, "전세가율이 높아 실수요 지지가 탄탄합니다")

        # 없음
        res_none = generate_strength_sentence({"excess_drop_rate": 0.0, "volume_ratio": 1.0, "jeonse_ratio": 0.50})
        self.assertIsNone(res_none)

    def test_generate_caution_sentence(self):
        # 1우선순위: sample_count_12m < 5
        c1 = generate_caution_sentence({"sample_count_12m": 3})
        self.assertEqual(c1, "거래가 드물어 기준가 신뢰도가 낮습니다")

        # 6우선순위: age_years in [15..28]
        c6 = generate_caution_sentence({"sample_count_12m": 10, "age_years": 20})
        self.assertEqual(c6, "재건축 기대는 이르고 신축 프리미엄은 지난 연식대입니다")

    def test_translate_exclusion_reason(self):
        self.assertEqual(translate_exclusion_reason("INSUFFICIENT_TRADES"), "거래가 드물어 가격을 판단하기 어렵습니다")
        self.assertIn("호가/기준가 비율 이상", translate_exclusion_reason("V2_PRICE_RATIO_OUT_OF_BOUNDS"))


if __name__ == "__main__":
    unittest.main()
