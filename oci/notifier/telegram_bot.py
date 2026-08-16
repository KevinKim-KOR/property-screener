# oci/notifier/telegram_bot.py
"""
텔레그램 알림 봇 v2 모듈
(SCORING_V2_DESIGN.md §16, P1-AC14).
Value Trap 방지 교차 검증 및 4-Block Evidence 메시지 발송 기능 구현.
"""
import sys
import json
from pathlib import Path
import requests
from typing import Dict, Any, Optional

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from common.config_loader import Config
from common.database import get_db_connection


class TelegramNotifier:
    def __init__(self):
        config = Config.get_telegram_config()
        self.bot_token = config.get('bot_token')
        self.chat_id = config.get('chat_id')
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send_message(self, text: str) -> bool:
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

    def build_alert_message(self, prop: Dict[str, Any], ms: Dict[str, Any], cas: Dict[str, Any]) -> str:
        """4-Block Evidence 기반 텔레그램 메시지 포맷을 구성합니다."""
        c_name = prop.get("complex_name", "Unknown")
        dong = prop.get("building_dong", "-")
        fl = prop.get("floor", "-")
        f_grade = prop.get("floor_grade", "MID")
        at = prop.get("area_type", "A84")
        ask = float(prop.get("asking_price", 0) or 0)
        gap_pct = prop.get("deal_gap_pct")
        score_v1 = float(prop.get("score_v1", 0.0) or 0.0)

        market_score = float(ms.get("market_score", score_v1) or score_v1)
        peer_group = ms.get("peer_group", "BELT_A84")

        med_3m = float(cas.get("median_price_3m", 0) or 0)
        price_str = f"{(ask/10000):.2f}억" if ask >= 10000 else f"{ask:,.0f}만"
        med_str = f"{(med_3m/10000):.2f}억" if med_3m >= 10000 else f"{med_3m:,.0f}만"
        gap_str = f"{gap_pct:.1f}%" if gap_pct is not None else "N/A"

        # Evidence 파싱
        ev = {}
        if ms.get("evidence_json"):
            try:
                ev = json.loads(ms["evidence_json"])
            except (ValueError, TypeError) as e:
                # 삼키면 근거(4-Block Evidence)가 빈 채로 알림이 발송된다.
                # 잘못된 근거로 매수 판단을 유도하느니 발송을 중단한다.
                raise ValueError(
                    f"스코어링 근거(evidence_json) 파싱 실패 - 알림을 발송하지 않습니다: "
                    f"{c_name} ({at}) / {e}"
                ) from e

        blocks = ev.get("blocks", {})
        val_score = blocks.get("Value", 0.0)
        flow_score = blocks.get("Flow", 0.0)
        loc_score = blocks.get("Location", 0.0)
        qual_score = blocks.get("Quality", 0.0)

        # 주의(Caution) 메시지 구성: F8_raw(건축연한) 등
        factors = ev.get("factors", {})
        age = factors.get("F8_raw", 0)
        if age >= 20:
            caution_str = f"준공 {age}년차 (노후 단지 주의)"
        elif gap_pct is not None and gap_pct > -5.0:
            caution_str = "중위 기준가 대비 호가 할인율이 높지 않음"
        else:
            caution_str = "특이 주의사항 없음 (게이트 정상 통과)"

        naver_url = f"https://new.land.naver.com/complexes/{prop.get('complex_code')}" if prop.get("complex_code") else "https://new.land.naver.com/"

        msg = f"🚨 *[강력 추천 매물 감지 (V2 스코어링)]*\n"
        msg += f"🏢 단지명: *{c_name}* ({dong} / {fl} / {f_grade})\n"
        msg += f"💰 호가: *{price_str}* (기준가: {med_str}, {gap_str} 괴리)\n"
        msg += f"📉 시장점수: *{market_score:.1f}점* (비교군: {peer_group})\n"
        msg += f"💪 [강점]: 가치 A({val_score:.1f}점), 수급 B({flow_score:.1f}점), 입지 C({loc_score:.1f}점)\n"
        msg += f"⚠️ [주의]: {caution_str}\n"
        msg += f"🔍 [네이버 부동산 매물 바로가기]({naver_url})"
        return msg

    def check_alert_condition(self, prop: Dict[str, Any], ms: Dict[str, Any]) -> bool:
        """
        발송 조건 검사 (SCORING_V2_DESIGN.md §16):
        1) G-EXCL 필터링: gate_status == 'EXCLUDED' 이면 발송 불가
        2) 점수 조건: market_score >= 80.0 또는 score_v1 >= 80.0
        3) 밸류 트랩 방지: deal_gap_pct <= -10.0% (3M중위 대비 10% 이상 저렴)
           단, deal_gap_pct 가 None 이면 score_v1 >= 80.0 일 때 발송
        """
        gate_status = ms.get("gate_status", "PASSED")
        if gate_status == "EXCLUDED":
            return False

        score_v1 = float(prop.get("score_v1", 0.0) or 0.0)
        market_score = float(ms.get("market_score", 0.0) or 0.0)
        if market_score < 80.0 and score_v1 < 80.0:
            return False

        gap = prop.get("deal_gap_pct")
        if gap is not None:
            # 기준가 대비 -10.0% 이하인 급매물만 발송
            return float(gap) <= -10.0
        else:
            return score_v1 >= 80.0

    def run(self, max_send: int = 10):
        """
        screener.db 내 properties, market_scores, complex_area_stats 를 조회하여
        발송 조건(점수, G-EXCL, 괴리율 -10%)을 만족하는 미발송 매물에 알림을 보낸다.
        """
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # sent_alerts 테이블 생성 보장
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sent_alerts (
                    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    property_id TEXT,
                    asking_price INTEGER,
                    sent_at TEXT
                )
            """)

            # market_scores 및 complex_area_stats 사전 로드
            cursor.execute("SELECT * FROM market_scores WHERE base_date = (SELECT MAX(base_date) FROM market_scores)")
            ms_map = { (str(r["complex_code"]), str(r["area_type"])): dict(r) for r in cursor.fetchall() }

            cursor.execute("SELECT * FROM complex_area_stats WHERE base_date = (SELECT MAX(base_date) FROM complex_area_stats)")
            cas_map = { (str(r["complex_code"]), str(r["area_type"])): dict(r) for r in cursor.fetchall() }

            cursor.execute("""
                SELECT p.* FROM properties p
                LEFT JOIN sent_alerts s ON p.property_id = s.property_id
                WHERE s.property_id IS NULL
            """)
            unnotified = [dict(r) for r in cursor.fetchall()]

            sent_count = 0
            for prop in unnotified:
                if sent_count >= max_send:
                    break
                pid = str(prop["property_id"])
                cc = str(prop["complex_code"] or "")
                at = str(prop["area_type"] or "A84")

                ms = ms_map.get((cc, at), {})
                cas = cas_map.get((cc, at), {})

                if self.check_alert_condition(prop, ms):
                    msg = self.build_alert_message(prop, ms, cas)
                    if self.send_message(msg):
                        cursor.execute("""
                            INSERT INTO sent_alerts (property_id, asking_price, sent_at)
                            VALUES (?, ?, datetime('now'))
                        """, (pid, prop.get("asking_price", 0)))
                        print(f"[Telegram] 급매 알림 발송 완료 -> {prop.get('complex_name')} ({pid})")
                        sent_count += 1

            conn.commit()
            print(f"[TelegramNotifier] 총 {sent_count}건 알림 처리 완료.")
