import requests
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
        # 네이버 API 차단 방지를 위한 User-Agent 및 Referer 세팅
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://new.land.naver.com/'
        }

    def fetch_complexes(self, region_code):
        url = f"https://new.land.naver.com/api/regions/complexes?cortarNo={region_code}&realEstateType=APT&tradeType=A1"
        res = requests.get(url, headers=self.headers)
        if res.status_code == 429:
            logger.error(f"[Crawler] 네이버 부동산 API Rate limit 초과 (429). 프록시나 딜레이가 필요할 수 있습니다.")
            return []
        if res.status_code != 200:
            logger.error(f"[Crawler] API 호출 실패: {res.status_code}")
            return []
        
        try:
            data = res.json()
            return data.get('complexList', [])
        except:
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
