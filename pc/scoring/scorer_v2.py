# pc/scoring/scorer_v2.py
"""
L1 (시장 점수: 단지 x 평형) 4-Block Peer-Group 스코어링 실행 진입점 모듈
(SCORING_V2_DESIGN.md §14, P1-AC10, P1-AC11, P1-AC12).
"""
import uuid
import time
from datetime import datetime
from typing import Optional, Dict, List
from common.database import get_db_connection
from common.peer_group import select_peer_group
from .normalizer import normalize_block_a, normalize_block_b, normalize_block_c, normalize_block_d
from .gate import check_quality_gates, check_coverage_gate
from .aggregator import aggregate_blocks
from .evidence import build_evidence_json

SCORER_VERSION = "2.1.0"

def run_l1_scoring_v2(base_date: Optional[str] = None) -> Dict:
    """
    단지 x area_type별 L1 시장 점수를 산출하여 market_scores 테이블에 적재한다.
    반환: 실행 요약 통계 딕셔너리
    """
    start_t = time.time()
    if not base_date:
        base_date = datetime.now().strftime("%Y-%m-%d")

    run_id = f"RUN_{uuid.uuid4().hex[:12].upper()}"
    stats = {
        "run_id": run_id,
        "base_date": base_date,
        "universe_total": 0,
        "universe_passed": 0,
        "excluded_count": 0,
        "duration_sec": 0.0
    }

    with get_db_connection() as conn:
        cur = conn.cursor()
        # 1. 단지마스터 조인된 complex_area_stats 조회
        cur.execute("""
            SELECT s.*, c.sgg_cd, c.umd_cd, c.brand, c.subway_dist_m, c.elem_school_dist_m, c.cbd_transit_min
            FROM complex_area_stats s
            LEFT JOIN complexes c ON s.complex_code = c.complex_code
            WHERE s.base_date = ?
        """, (base_date,))
        all_items = [dict(r) for r in cur.fetchall()]

        stats["universe_total"] = len(all_items)

        for item in all_items:
            cc = item["complex_code"]
            at = item["area_type"]

            # 비교군 선택 (UMD -> SGG -> BELT)
            # NOTE: v3 가 같은 base_date 의 market_scores 를 지우고 다시 쓰므로
            #       화면에 실제로 반영되는 것은 v3 결과다. 여기서는 시그니처만 맞춘다.
            peers, pg_key, pg_n, _pg_level = select_peer_group(item, all_items)

            # Block 정규화
            score_a, cov_a, z_a = normalize_block_a(item, peers)
            score_b, cov_b, z_b = normalize_block_b(item, peers)
            score_c, cov_c, z_c = normalize_block_c(item, peers)
            score_d, cov_d, z_d = normalize_block_d(item, peers)

            total_cov = (0.35 * cov_a) + (0.25 * cov_b) + (0.20 * cov_c) + (0.20 * cov_d)

            # 게이트 검사 (품질 게이트는 비교군과 무관, 커버리지는 별도 판정)
            gate_status, gate_reason = check_quality_gates(item)
            if gate_status == "PASSED":
                gate_status, gate_reason = check_coverage_gate(total_cov)

            block_scores = {"A": score_a, "B": score_b, "C": score_c, "D": score_d}
            z_maps = {"A": z_a, "B": z_b, "C": z_c, "D": z_d}

            if gate_status == "EXCLUDED":
                stats["excluded_count"] += 1
                raw_score = 0.0
                base_score = 0.0
                market_score = None
            else:
                stats["universe_passed"] += 1
                raw_score, base_score, market_score = aggregate_blocks(block_scores, risk_multiplier=1.0)

            ev_json = build_evidence_json(
                cc, at, pg_key, pg_n, block_scores, z_maps,
                raw_score, base_score, 1.0, market_score or 0.0,
                gate_status, gate_reason
            )

            cur.execute("""
                INSERT OR REPLACE INTO market_scores (
                    run_id, base_date, complex_code, area_type,
                    peer_group_key, peer_group_n,
                    block_value, block_flow, block_location, block_quality,
                    raw_score, base_score, risk_multiplier, market_score,
                    gate_status, gate_reason, coverage_ratio, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, base_date, cc, at, pg_key, pg_n,
                score_a, score_b, score_c, score_d,
                raw_score, base_score, 1.0, market_score,
                gate_status, gate_reason, total_cov, ev_json
            ))

        # 2. score_runs 기록
        dur = time.time() - start_t
        stats["duration_sec"] = round(dur, 3)
        now_str = datetime.now().isoformat()
        cur.execute("""
            INSERT INTO score_runs (
                run_id, run_at, base_date, config_hash, scorer_version,
                universe_total, universe_passed, excluded_count, duration_sec
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, now_str, base_date, "V2_DEFAULT", SCORER_VERSION,
            stats["universe_total"], stats["universe_passed"], stats["excluded_count"], stats["duration_sec"]
        ))

        conn.commit()

    return stats
