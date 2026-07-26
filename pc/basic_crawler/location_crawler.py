import requests
import sys
import json
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from common.config_loader import Config

CACHE_FILE = Path(__file__).resolve().parent / "location_cache.json"

class LocationCrawler:
    def __init__(self):
        self.api_key = Config.get_kakao_api_key()
        if self.api_key:
            self.headers = {"Authorization": f"KakaoAK {self.api_key.strip()}"}
        else:
            self.headers = {}
            
        self.cache = {}
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                self.cache = json.load(f)

    def _save_cache(self):
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    def get_complex_info(self, region_name, complex_name):
        """
        단지명과 지역명을 이용해 카카오 로컬 API에서 좌표와 인근 지하철역을 검색합니다.
        (캐싱이 적용되어 동일한 단지는 API를 중복 호출하지 않습니다.)
        """
        cache_key = f"{region_name} {complex_name}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        if not self.headers:
            return "카카오 API 키가 설정되지 않았습니다."

        search_url = "https://dapi.kakao.com/v2/local/search/keyword.json"
        
        # 1. 단지 좌표 검색
        res = requests.get(search_url, headers=self.headers, params={"query": cache_key})
        if res.status_code != 200:
            return f"단지 검색 API 호출 실패 (상태 코드: {res.status_code})"
            
        data = res.json()
        if not data.get("documents"):
            return "단지 좌표를 찾을 수 없습니다."
            
        complex_data = data["documents"][0]
        x = complex_data["x"]
        y = complex_data["y"]
        
        # 2. 인근 지하철역 검색 (카테고리: SW8 - 지하철역, 반경 1.5km 내)
        category_url = "https://dapi.kakao.com/v2/local/search/category.json"
        params = {
            "category_group_code": "SW8",
            "x": x,
            "y": y,
            "radius": 1500, # 1.5km
            "sort": "distance"
        }
        
        res2 = requests.get(category_url, headers=self.headers, params=params)
        if res2.status_code != 200:
            return "지하철역 검색 API 호출 실패"
            
        station_data = res2.json()
        if not station_data.get("documents"):
            result = "반경 1.5km 내에 지하철역이 없습니다."
        else:
            nearest = station_data["documents"][0]
            station_name = nearest["place_name"]
            distance = nearest["distance"] # 미터 단위
            
            # 성인 기준 도보 시간 계산 (보통 1분에 80m)
            walk_minutes = int(distance) // 80
            if walk_minutes == 0:
                walk_minutes = 1
                
            result = f"가장 가까운 지하철역은 {station_name}이며 직선거리 {distance}m (도보 약 {walk_minutes}분) 입니다."
            
        self.cache[cache_key] = result
        self._save_cache()
        return result
