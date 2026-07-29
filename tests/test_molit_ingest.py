# tests/test_molit_ingest.py
import unittest
import os
import sqlite3
from common.database import init_db, Config
from oci.crawler.molit_ingest import ingest_molit_csv_file
from oci.crawler.molit_csv_loader import load_sale_trades_from_csv, load_rent_trades_from_csv

class TestMolitIngest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_load_and_ingest_real_csv(self):
        csv_dir = "csv"
        if not os.path.exists(csv_dir):
            self.skipTest("csv 폴더가 없습니다.")

        files = [f for f in os.listdir(csv_dir) if f.endswith(".csv")]
        self.assertGreaterEqual(len(files), 2, "2026_서초구_매매.csv 및 2026_서초구_전세.csv 파일이 있어야 합니다.")

        total_sales = 0
        total_rents = 0

        for fname in files:
            fpath = os.path.join(csv_dir, fname)
            # 파일 이름이나 내용을 기준으로 매매 vs 전세 판단
            if "매매" in fname or "sale" in fname.lower():
                count = ingest_molit_csv_file(fpath, is_rent=False, snapshot_date="2026-07-29")
                total_sales += count
            elif "전세" in fname or "rent" in fname.lower():
                count = ingest_molit_csv_file(fpath, is_rent=True, snapshot_date="2026-07-29")
                total_rents += count

        print(f"\n[TestResult] 총 매매 {total_sales}건, 전월세 {total_rents}건 적재 완료")
        self.assertGreater(total_sales, 0, "매매 데이터가 최소 1건 이상 적재되어야 합니다.")
        self.assertGreater(total_rents, 0, "전세 데이터가 최소 1건 이상 적재되어야 합니다.")

        # DB 검증
        db_path = Config.get_db_path()
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM trades_sale")
            sale_db_cnt = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM trades_rent")
            rent_db_cnt = cur.fetchone()[0]

            print(f"[DB Verification] trades_sale: {sale_db_cnt}건, trades_rent: {rent_db_cnt}건 in DB")
            self.assertGreater(sale_db_cnt, 0)
            self.assertGreater(rent_db_cnt, 0)

if __name__ == "__main__":
    unittest.main()
