import sys
import time
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가하여 common 모듈 등을 참조할 수 있게 함
sys.path.append(str(Path(__file__).resolve().parent.parent))

from common.config_loader import Config
from pc.sync.sync_manager import SyncManager
from pc.ml_engine.scorer import MLEngine

def main():
    print("=======================================")
    print("[PC Engine] Starting PC Pipeline...")
    print("=======================================")
    
    config = Config.load()
    sync_interval_hours = config.get('pc', {}).get('sync_interval_hours', 6)
    
    while True:
        print("\n[PC Engine] Running task iteration...")
        
        # 1. OCI로부터 DB 다운로드 (현재 Mock 처리)
        print("[PC Engine] Downloading screener.db from OCI...")
        SyncManager.download_db()
        
        # 2. ML 기반 정형 데이터 분석 및 프롬프트 생성
        print("[PC Engine] Running ML Scoring & Prompt Generation...")
        results = MLEngine.run()
        
        # 3. 분석 결과 JSON을 OCI로 업로드
        print("[PC Engine] Uploading ml_results.json to OCI...")
        SyncManager.upload_results(results)
        
        print(f"[PC Engine] Iteration complete. Waiting for {sync_interval_hours} hours...")
        
        # 개발 중 빠른 테스트를 위해 sleep 대신 바로 종료할 수도 있습니다.
        # 실제 운영 시에는 아래 주석을 풀고 대기합니다.
        # time.sleep(sync_interval_hours * 3600)
        
        # 테스트용으로 1회만 돌고 종료하도록 처리 (이후 백그라운드 봇이 되면 주석 처리)
        print("[PC Engine] (Test Mode) Exiting after 1 iteration.")
        break

if __name__ == "__main__":
    main()
