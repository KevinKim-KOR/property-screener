try:
    from curl_cffi import requests as cffi_requests
    USE_CURL_CFFI = True
except ImportError:
    import requests
    USE_CURL_CFFI = False

import json
import logging
import sys
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from common.config_loader import Config
from common.database import get_db_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NaverCrawler:
    def __init__(self):
        if USE_CURL_CFFI:
            self.session = cffi_requests.Session(impersonate="chrome120")
            # 메인 페이지 접속으로 세션 쿠키 초기화
            try:
                self.session.get(
                    "https://new.land.naver.com/complexes?ms=37.481,127.037,16&a=APT&b=A1&e=RESTA",
                    headers={
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
                    }
                )
            except Exception as e:
                logger.warning(f"[Crawler] 메인 세션 초기화 경고: {e}")
        else:
            import requests
            self.session = requests.Session()

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://new.land.naver.com/',
            'Accept': 'application/json, text/plain, */*'
        }

    def fetch_complexes(self, region_code):
        url = f"https://new.land.naver.com/api/regions/complexes?cortarNo={region_code}&realEstateType=APT&tradeType=A1"
        res = self.session.get(url, headers=self.headers)
        if res.status_code == 429:
            logger.error(f"[Crawler] 네이버 부동산 API Rate limit 초과 (429). 프록시나 딜레이가 필요할 수 있습니다.")
            return []
        if res.status_code != 200:
            logger.error(f"[Crawler] API 호출 실패: {res.status_code}")
            return []
        
        try:
            data = res.json()
            return data.get('complexList', [])
        except Exception as e:
            logger.error(f"[Crawler] JSON 파싱 에러: {e}")
            return []

    def run(self):
        regions = Config.get_target_regions()
        for region in regions:
            region_code = region['code']
            logger.info(f"[Crawler] 타겟 지역 탐색 시작: {region['name']} ({region_code})")
            
            complexes = self.fetch_complexes(region_code)
            logger.info(f"[Crawler] 발견된 단지 수: {len(complexes)}")
            
            # 실제 운영 환경에서는 이 단지 목록을 순회하며 매물(Article) API를 호출해 DB에 저장해야 합니다.

            # (현재는 OCI 프레임워크 뼈대를 완성하는 단계이므로 상세 크롤링 로직은 추후 고도화합니다)
