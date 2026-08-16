import os
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from common.config_loader import Config

# OCI 파일 동기화(SFTP/SCP)는 아직 구현되지 않았다. (설계 문서 §9 항목 29)
# 현재 OCI 는 자체적으로 크롤링해 자기 screener.db 를 만들고, 텔레그램 봇도
# 그 DB 를 직접 조회하므로 PC -> OCI 파일 전송 경로가 필요하지 않다.
#
# 과거에는 이 클래스가 전송에 성공한 것처럼 로그만 남기고 조용히 통과해
# "동기화가 동작 중"이라는 오해를 만들었다. 미구현은 소리 내어 실패해야 한다.
_NOT_IMPLEMENTED_MSG = "OCI 동기화는 아직 구현되지 않았습니다"


class SyncManager:
    @staticmethod
    def download_db():
        """OCI 서버의 screener.db 를 내려받는다. (미구현)"""
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    @staticmethod
    def upload_results(results):
        """분석 결과를 OCI 서버로 올린다. (미구현)"""
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    @staticmethod
    def ensure_local_db():
        """
        로컬 screener.db 존재를 보장한다. 없으면 목 데이터를 생성한다.
        (기존 download_db() 안에 섞여 있던 '전송과 무관한 로컬 폴백' 로직을
         이름과 함께 분리한 것으로, OCI 통신을 하지 않는다.)
        """
        db_path = Config.get_db_path()
        if not os.path.exists(db_path):
            print("[SyncManager] Local screener.db not found. Generating mock data...")
            from pc.mock_generator import generate_mock_data
            generate_mock_data()
        else:
            print(f"[SyncManager] Using local screener.db ({db_path}).")
