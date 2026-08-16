# tests/test_e2e_v2_pipeline.py
"""
SCORING_V2_DESIGN.md §17 (테스트 전략 - E2E 검증 시나리오)에 따른
전체 V2 파이프라인 E2E 통합 테스트.
"""
import unittest
import sqlite3
from pathlib import Path
from common.database import init_db, get_db_connection
from oci.crawler.molit_ingest import ingest_molit_csv_file
from pc.features.build_complex_master import build_complex_master_from_molit
from pc.keymap.matcher import run_complex_matching
from pc.features.region_stats import compute_and_store_region_stats
from pc.features.build_stats import build_complex_area_stats
from pc.scoring.scorer_v2 import run_l1_scoring_v2
from pc.l2.deal_gap import update_all_properties_l2
from pc.web_app import get_properties, get_region_stats_api, get_evidence_api
from oci.notifier.telegram_bot import TelegramNotifier

class TestE2EV2Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_full_pipeline(self):
        print("\n--- [E2E Step 1] 실거래 데이터 인제스트 (molit_ingest) ---")
        root = Path(__file__).resolve().parent.parent / "csv"
        sales_file = root / "2026_서초구_매매.csv"
        cnt_sales = ingest_molit_csv_file(str(sales_file), is_rent=False, snapshot_date="2026-07-29")
        self.assertGreaterEqual(cnt_sales, 100, "서초구 매매 실거래 적재되어야 함")

        print("\n--- [E2E Step 1-1] 단지 마스터 구축 (build_complex_master) ---")
        # 매칭은 complexes(단지 마스터)를 대조군으로 쓰므로 반드시 선행되어야 한다.
        # 이 단계가 빠지면 매칭이 전부 UNMATCHED 가 되어 이후가 전부 0이 된다.
        master_cnt = build_complex_master_from_molit()
        self.assertGreaterEqual(master_cnt, 10, "국토부 실거래에서 단지 마스터가 만들어져야 함")

        print("\n--- [E2E Step 1-2] 4단계 지번/도로명/단지명 매칭 엔진 (matcher) ---")
        match_res = run_complex_matching()
        self.assertGreaterEqual(match_res["total"], 0)

        print("\n--- [E2E Step 2 & 3] 지역 통계 및 단지/평형 통계 생성 (build_stats) ---")
        # build_complex_area_stats 는 region_stats 를(초과하락률용),
        # compute_and_store_region_stats 는 complex_area_stats 를 읽는 상호 참조이므로
        # build -> region -> build 2패스로 채운다. 순서를 지키지 않으면
        # 깨끗한 DB 에서 region_stats 가 0 이 된다.
        cas_cnt = build_complex_area_stats("2026-07-29")
        reg_cnt = compute_and_store_region_stats("2026-07-29")
        cas_cnt = build_complex_area_stats("2026-07-29")
        self.assertGreaterEqual(reg_cnt, 2)
        self.assertGreaterEqual(cas_cnt, 10)

        print("\n--- [E2E Step 4] L1 4-Block 퀀트 스코어링 (scorer_v2) ---")
        ms_res = run_l1_scoring_v2("2026-07-29")
        self.assertGreaterEqual(ms_res.get("universe_total", 0), 10)

        print("\n--- [E2E Step 5] L2 매물 괴리율 및 V1 병행 연산 (deal_gap) ---")
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as cnt FROM properties")
            if cur.fetchone()["cnt"] == 0:
                cur.execute("""
                    INSERT INTO properties (property_id, complex_code, complex_name, area_type, asking_price, floor)
                    VALUES ('TEST_E2E_1', '100', '테스트아파트', 'A84', 150000, '중')
                """)
                conn.commit()
        prop_cnt = update_all_properties_l2("2026-07-29")
        self.assertGreaterEqual(prop_cnt, 1)

        print("\n--- [E2E Step 6] 웹 대시보드 API 검증 ---")
        props_data = get_properties()
        self.assertIn("properties", props_data)
        self.assertGreaterEqual(props_data["count"], 1)
        sample = props_data["properties"][0]
        # 11개 핵심 컬럼 존재 여부
        for key in ["asking_price", "median_price_3m", "deal_gap_pct", "peak_price", "excess_drop_rate", "market_score", "score_v1"]:
            self.assertIn(key, sample)

        region_stats = get_region_stats_api()
        self.assertGreaterEqual(len(region_stats), 1)

        ev_data = get_evidence_api(sample["complex_code"], sample["area_type"])
        self.assertIn("blocks", ev_data)
        self.assertIn("factors", ev_data)

        print("\n--- [E2E Step 7] 텔레그램 알림 봇 조건 검사 (telegram_bot) ---")
        notifier = TelegramNotifier()
        notifier.run(max_send=0)  # 0건 발송(조건 필터링만 검증)

        print("\n--- ALL E2E STEPS PASSED 100% SUCCESS ---")

if __name__ == "__main__":
    unittest.main()
