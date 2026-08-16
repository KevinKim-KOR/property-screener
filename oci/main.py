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
    
    # 2. 텔레그램 알림 발송
    #    screener.db 의 properties / market_scores / complex_area_stats / sent_alerts 를
    #    직접 조회해 발송 대상을 고른다. ml_results.json 은 읽지 않는다.
    print("[OCI Engine] Running Telegram Notifier...")
    notifier = TelegramNotifier()
    notifier.run()
    
    print("[OCI Engine] Iteration complete.")

if __name__ == "__main__":
    main()
