# tests/test_telegram_bot_v2.py
import unittest
from oci.notifier.telegram_bot import TelegramNotifier
from common.database import init_db

class TestTelegramBotV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_check_alert_condition(self):
        notifier = TelegramNotifier()
        # 1. EXCLUDED 케이스 -> False
        self.assertFalse(notifier.check_alert_condition({"score_v1": 90, "deal_gap_pct": -15.0}, {"gate_status": "EXCLUDED", "market_score": 90}))
        # 2. 점수 80 미만 -> False
        self.assertFalse(notifier.check_alert_condition({"score_v1": 70, "deal_gap_pct": -15.0}, {"gate_status": "PASSED", "market_score": 75}))
        # 3. 괴리율이 -10%보다 큼(-5%) -> False (Value trap)
        self.assertFalse(notifier.check_alert_condition({"score_v1": 85, "deal_gap_pct": -5.0}, {"gate_status": "PASSED", "market_score": 85}))
        # 4. 괴리율 -12%, 점수 85, PASSED -> True
        self.assertTrue(notifier.check_alert_condition({"score_v1": 85, "deal_gap_pct": -12.0}, {"gate_status": "PASSED", "market_score": 85}))

    def test_build_alert_message(self):
        notifier = TelegramNotifier()
        prop = {
            "complex_name": "서초 반포자이",
            "building_dong": "101동",
            "floor": "15층",
            "floor_grade": "HIGH",
            "area_type": "A84",
            "asking_price": 295000,
            "deal_gap_pct": -11.1,
            "score_v1": 85.0
        }
        ms = {
            "market_score": 85.4,
            "peer_group": "서초구_A84",
            "evidence_json": '{"blocks": {"Value": 32.1, "Flow": 24.0, "Location": 18.5, "Quality": 15.0}, "factors": {"F8_raw": 18}}'
        }
        cas = {"median_price_3m": 332000}
        msg = notifier.build_alert_message(prop, ms, cas)
        self.assertIn("강력 추천 매물 감지", msg)
        self.assertIn("29.50억", msg)
        self.assertIn("-11.1%", msg)

if __name__ == "__main__":
    unittest.main()
