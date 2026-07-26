import sys
import json
from pathlib import Path
import requests

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from common.config_loader import Config
from common.database import get_db_connection

class TelegramNotifier:
    def __init__(self):
        config = Config.get_telegram_config()
        self.bot_token = config.get('bot_token')
        self.chat_id = config.get('chat_id')
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send_message(self, text):
        if not self.bot_token or not self.chat_id:
            print("[Telegram] 봇 토큰이나 Chat ID가 설정되지 않아 발송을 스킵합니다.")
            return False
            
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        res = requests.post(self.api_url, json=payload)
        if res.status_code == 200:
            return True
        else:
            print(f"[Telegram] 발송 실패: {res.text}")
            return False

    def run(self):
        # 1. PC에서 업로드한 ml_results.json 읽기
        ml_path = Path(Config.get_db_path()).parent / "ml_results.json"
        if not ml_path.exists():
            print("[Telegram] ml_results.json 파일이 없습니다. PC 분석이 아직 완료되지 않았습니다.")
            return
            
        with open(ml_path, "r", encoding="utf-8") as f:
            ml_results = json.load(f)
            
        # 2. DB에서 알림을 보내지 않은(미발송) 신규 매물 조회
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.* FROM properties p
                LEFT JOIN sent_alerts s ON p.property_id = s.property_id
                WHERE s.property_id IS NULL
            """)
            unnotified = cursor.fetchall()
            
            for row in unnotified:
                prop_id = row["property_id"]
                if prop_id in ml_results:
                    data = ml_results[prop_id]
                    
                    msg = f"*{row['complex_name']} 급매 알림!*\n\n"
                    msg += f"- 📊 ML 퀀트 점수: *{data['ml_score']}점*\n\n"
                    msg += f"🤖 *AI 질문 프롬프트*\n```\n{data['ai_prompt']}\n```"
                    
                    if self.send_message(msg):
                        # 발송 성공 시 중복 발송 방지를 위해 DB에 이력 기록
                        cursor.execute("INSERT INTO sent_alerts (property_id, asking_price, sent_at) VALUES (?, ?, datetime('now'))", 
                                     (prop_id, row["asking_price"]))
                        print(f"[Telegram] {prop_id} 알림 발송 완료.")
            conn.commit()
