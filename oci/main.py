import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from oci.crawler.naver_crawler import NaverCrawler
from oci.notifier.telegram_bot import TelegramNotifier
from common.database import init_db

def main():
    print("=======================================")
    print("[OCI Engine] Starting OCI Pipeline...")
    print("=======================================")
    
    init_db()
    
    # 1. 네이버 부동산 스캔
    print("[OCI Engine] Running Naver Crawler...")
    crawler = NaverCrawler()
    crawler.run()
    
    # 2. 텔레그램 알림 발송 (PC에서 생성한 ml_results.json 기반)
    print("[OCI Engine] Running Telegram Notifier...")
    notifier = TelegramNotifier()
    notifier.run()
    
    print("[OCI Engine] Iteration complete.")

if __name__ == "__main__":
    main()
