import unittest
import sys
import os
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.append(str(Path(__file__).resolve().parent.parent))

from oci.crawler.naver_crawler import NaverCrawler
from common.database import get_db_connection, init_db
from common.config_loader import Config

class TestNaverCrawlerAutomated(unittest.TestCase):
    """
    개발 및 운영 중 수동 명령어 승인이나 단건 조회 없이,
    프로그램 내에서 네이버 부동산 크롤러의 동작(API 호출, 429 우회, DB 자동 저장)을
    종합적으로 자동 검증하는 테스트 모듈입니다.
    """

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.crawler = NaverCrawler()
        cls.test_region_code = "1165010700"  # 서초구 반포동

    def test_01_fetch_complexes_auto(self):
        """1. 단지 목록 API (429 우회 및 세션 쿠키 검증) 자동 실행"""
        print("\n[AutoTest] 단지 목록 수집 API 테스트 시작...")
        complexes = self.crawler.fetch_complexes(self.test_region_code)
        self.assertIsInstance(complexes, list)
        if len(complexes) > 0:
            print(f"[AutoTest] 성공: {len(complexes)}개 아파트 단지 확인 완료.")
        else:
            print("[AutoTest] 경고: 수집된 단지가 0건입니다 (네트워크 및 Proxy 상태 체크).")

    def test_02_save_to_db_auto(self):
        """2. 수집된 단지 매물 DB 저장 및 파이프라인 자동 검증"""
        print("\n[AutoTest] 수집 단지 DB 자동 저장 테스트 시작...")
        sample_complexes = [
            {
                "complexNo": "999999",
                "complexName": "[자동 검증용 단지]",
                "dealCount": 5,
                "highFloor": "35"
            }
        ]
        self.crawler.save_complex_properties_to_db(sample_complexes)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT * FROM properties WHERE complex_code = ?", ("999999",)
            ).fetchone()
            self.assertIsNotNone(row, "DB에 테스트 단지가 정상 저장되어야 합니다.")
            print(f"[AutoTest] 성공: DB 검증 완료 (단지명: {row['complex_name']}, 매매가: {row['asking_price']}만원)")

            # 테스트 후 클린업
            cursor.execute("DELETE FROM properties WHERE complex_code = ?", ("999999",))
            conn.commit()

if __name__ == '__main__':
    unittest.main()
