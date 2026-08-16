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
        
        # 1. 로컬 screener.db 확보 (OCI 다운로드는 미구현 - 설계 문서 §9 항목 29)
        print("[PC Engine] Ensuring local screener.db...")
        SyncManager.ensure_local_db()
        
        # 2. ML 기반 정형 데이터 분석 및 프롬프트 생성
        #    MLEngine.run() 이 reports/ml_results.json 을 직접 기록한다.
        print("[PC Engine] Running ML Scoring & Prompt Generation...")
        MLEngine.run()
        
        # 3. OCI 업로드 단계는 없다. 전송이 미구현이며
        #    SyncManager.upload_results() 는 호출 시 NotImplementedError 를 발생시킨다.
        
        # 4. 로컬 PC에서 즉시 열어볼 수 있는 시각적 HTML 대시보드 자동 생성
        from pc.viewer.generate_report import generate_report
        generate_report()
        
        print(f"[PC Engine] Iteration complete. Waiting for {sync_interval_hours} hours...")
        
        # 개발 중 빠른 테스트를 위해 sleep 대신 바로 종료할 수도 있습니다.
        # 실제 운영 시에는 아래 주석을 풀고 대기합니다.
        # time.sleep(sync_interval_hours * 3600)
        
        # 테스트용으로 1회만 돌고 종료하도록 처리 (이후 백그라운드 봇이 되면 주석 처리)
        print("[PC Engine] (Test Mode) Exiting after 1 iteration.")
        break

if __name__ == "__main__":
    main()
