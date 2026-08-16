# pc/scoring/scorer_v3.py
"""
L1 (시장 점수: 단지 x 평형) 4-Block Peer-Group 상대평가 기반 V3 스코어링 실행 진입점 모듈
(SCORING_V3_DESIGN.md §12.1, §13, §19 P1-AC10, P1-AC11).
"""
import uuid
import time
import math
import os
import yaml
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

from common.database import get_db_connection
from common.peer_group import select_peer_group
from .normalizer import normalize_block_a, normalize_block_b, normalize_block_c, normalize_block_d
from .gate import check_quality_gates
from .aggregator import aggregate_blocks
from .evidence import build_evidence_json

SCORER_VERSION = "3.0.0"

@dataclass(frozen=True)
class ScoreRunResult:
    run_id: str
    universe_total: int
    universe_passed: int
    excluded_by_reason: Dict[str, int]
    duration_sec: float

class ScoringConfigError(RuntimeError):
    """스코어링 설정 파일을 읽지 못해 중단한 경우."""


def load_scoring_v3_config(config_path: str = "config/scoring_v3.yaml") -> Dict:
    """
    config/scoring_v3.yaml에서 가중치·임계값을 동적 로드한다 (C2).

    설정을 못 읽으면 중단한다. 과거에는 경고 한 줄만 찍고 빈 dict 를 돌려주어
    설계와 다른 기본 가중치로 점수가 산출됐고, 화면에는 정상으로 보였다.
    점수 자체가 달라지는 문제이므로 조용히 넘어가서는 안 된다.
    """
    # CWD 에 의존하면 실행 위치에 따라 없는 파일이 되어 버린다.
    # 상대경로면 프로젝트 루트 기준으로 해석한다.
    if not os.path.isabs(config_path):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        candidate = os.path.join(root, config_path)
        if os.path.exists(candidate):
            config_path = candidate

    if not os.path.exists(config_path):
        raise ScoringConfigError(
            f"스코어링 설정 파일을 찾을 수 없습니다: '{config_path}' "
            f"(작업 디렉토리: {os.getcwd()}). 설정 없이 점수를 내면 설계와 다른 "
            f"가중치가 적용되므로 중단합니다."
        )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except Exception as e:
        raise ScoringConfigError(
            f"스코어링 설정 파일을 읽을 수 없습니다: '{config_path}' ({e}). 중단합니다."
        ) from e
    if not cfg:
        raise ScoringConfigError(
            f"스코어링 설정 파일이 비어 있습니다: '{config_path}'. 중단합니다."
        )
    return cfg

def _aggregate_blocks_v3(b_val: float, b_flw: float, b_loc: float, b_qty: float,
                         cov_a: float, cov_b: float, cov_c: float, cov_d: float,
                         w_cfg: Dict[str, float]) -> Tuple[float, float]:
    w_val = w_cfg.get("value", 0.35)
    w_flw = w_cfg.get("flow", 0.25)
    w_loc = w_cfg.get("location", 0.20)
    w_qty = w_cfg.get("quality", 0.20)
    raw_score = w_val * b_val + w_flw * b_flw + w_loc * b_loc + w_qty * b_qty
    total_cov = w_val * cov_a + w_flw * cov_b + w_loc * cov_c + w_qty * cov_d
    return raw_score, total_cov

def run_scoring(base_date: Optional[str] = None, config_path: str = "config/scoring_v3.yaml") -> ScoreRunResult:
    """
    L1 스코어링 전체 파이프라인. market_scores/score_runs 적재 후 요약 반환.
    """
    start_t = time.time()
    if not base_date:
        base_date = datetime.now().strftime("%Y-%m-%d")

    cfg = load_scoring_v3_config(config_path)
    run_id = f"RUN_{uuid.uuid4().hex[:12].upper()}"

    excluded_reasons = defaultdict(int)
    passed_count = 0
    total_count = 0

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM market_scores WHERE base_date = ?", (base_date,))
        cur.execute("""
            SELECT s.*, c.complex_name, c.sgg_cd, c.umd_cd, c.region_name AS umd_nm, c.brand, c.subway_dist_m, c.elem_school_dist_m, c.cbd_transit_min, c.total_households
            FROM complex_area_stats s
            LEFT JOIN complexes c ON s.complex_code = c.complex_code
            WHERE s.base_date = ?
        """, (base_date,))
        all_items = [dict(r) for r in cur.fetchall()]
        total_count = len(all_items)

        min_n = cfg.get("universe", {}).get("min_peer_n", 10)

        # 1. Block 점수 및 품질 게이트 판정
        scored_items = []
        for it in all_items:
            peers, pg_key, pg_n = select_peer_group(it, all_items, min_n, min_n, min_n)

            b_val, cov_a, map_a = normalize_block_a(it, peers)
            b_flw, cov_b, map_b = normalize_block_b(it, peers)
            b_loc, cov_c, map_c = normalize_block_c(it, peers)
            b_qty, cov_d, map_d = normalize_block_d(it, peers)

            w_cfg = {
                "value": cfg.get("blocks", {}).get("value", {}).get("weight", 0.35),
                "flow": cfg.get("blocks", {}).get("flow", {}).get("weight", 0.25),
                "location": cfg.get("blocks", {}).get("location", {}).get("weight", 0.20),
                "quality": cfg.get("blocks", {}).get("quality", {}).get("weight", 0.20),
            }
            raw_score, total_cov = _aggregate_blocks_v3(b_val, b_flw, b_loc, b_qty, cov_a, cov_b, cov_c, cov_d, w_cfg)

            # 품질 게이트 검사 (G1~G7)
            gate_status, gate_reason = check_quality_gates(it, total_cov)
            if gate_status == "EXCLUDED":
                excluded_reasons[str(gate_reason)] += 1
                cur.execute("""
                    INSERT OR REPLACE INTO market_scores (
                        run_id, base_date, complex_code, area_type,
                        peer_group_key, peer_group_n,
                        block_value, block_flow, block_location, block_quality,
                        raw_score, base_score, risk_multiplier, market_score,
                        gate_status, gate_reason, coverage_ratio, evidence_json
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, 1.0, NULL, 'EXCLUDED', ?, ?, '{}')
                """, (
                    run_id, base_date, it["complex_code"], it["area_type"],
                    pg_key, pg_n, str(gate_reason), total_cov
                ))
                continue

            it["_pg_key"] = pg_key
            it["_pg_n"] = pg_n
            it["_b_val"] = b_val
            it["_b_flw"] = b_flw
            it["_b_loc"] = b_loc
            it["_b_qty"] = b_qty
            it["_raw_score"] = raw_score
            it["_total_cov"] = total_cov
            it["_map_a"] = map_a
            it["_map_b"] = map_b
            it["_map_c"] = map_c
            it["_map_d"] = map_d
            scored_items.append(it)

        # 2. Φ (CDF) 매핑 - 유니버스 내 평균/표준편차 기반 0~100 스케일
        passed_count = len(scored_items)
        if passed_count > 0:
            raw_vals = [it["_raw_score"] for it in scored_items if it["_raw_score"] is not None]
            u_mean = sum(raw_vals) / len(raw_vals) if raw_vals else 0.0
            u_var = sum((v - u_mean) ** 2 for v in raw_vals) / len(raw_vals) if raw_vals else 1.0
            u_std = math.sqrt(u_var) if u_var > 1e-9 else 1.0

            for it in scored_items:
                raw_z = (it["_raw_score"] - u_mean) / u_std
                # 표준정규분포 CDF (0.5 * (1 + erf(x / sqrt(2))))
                cdf_val = 0.5 * (1.0 + math.erf(raw_z / math.sqrt(2.0)))
                base_score = round(cdf_val * 100.0, 1)
                risk_mult = 1.0  # Phase 1: risk multiplier = 1.0 (§8.1)
                market_score = round(base_score * risk_mult, 1)

                block_scores = {"A": it["_b_val"], "B": it["_b_flw"], "C": it["_b_loc"], "D": it["_b_qty"]}
                z_maps = {"A": it["_map_a"], "B": it["_map_b"], "C": it["_map_c"], "D": it["_map_d"]}

                evidence_json = build_evidence_json(
                    it["complex_code"], it["area_type"], it["_pg_key"], it["_pg_n"],
                    block_scores, z_maps, it["_raw_score"], base_score,
                    risk_mult, market_score, "PASS", None
                )

                cur.execute("""
                    INSERT OR REPLACE INTO market_scores (
                        run_id, base_date, complex_code, area_type,
                        peer_group_key, peer_group_n,
                        block_value, block_flow, block_location, block_quality,
                        raw_score, base_score, risk_multiplier, market_score,
                        gate_status, gate_reason, coverage_ratio, evidence_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PASS', NULL, ?, ?)
                """, (
                    run_id, base_date, it["complex_code"], it["area_type"],
                    it["_pg_key"], it["_pg_n"],
                    it["_b_val"], it["_b_flw"], it["_b_loc"], it["_b_qty"],
                    it["_raw_score"], base_score, risk_mult, market_score,
                    it["_total_cov"], evidence_json
                ))

        # 3. score_runs 이력 적재
        duration = time.time() - start_t
        cur.execute("""
            INSERT OR REPLACE INTO score_runs (
                run_id, run_at, base_date, config_hash,
                scorer_version, universe_total, universe_passed,
                excluded_count, duration_sec
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), base_date,
            "CFG_V3_HASH", SCORER_VERSION, total_count, passed_count,
            total_count - passed_count, round(duration, 3)
        ))
        conn.commit()

    # Gate Summary Report 출력 (§11.4, P1-AC11)
    print(f"\n[RUN {run_id}] base_date={base_date} universe={total_count} passed={passed_count} excluded={total_count - passed_count}")
    for k, v in sorted(excluded_reasons.items(), key=lambda x: -x[1]):
        print(f"  {k:25s}: {v}")

    return ScoreRunResult(
        run_id=run_id,
        universe_total=total_count,
        universe_passed=passed_count,
        excluded_by_reason=dict(excluded_reasons),
        duration_sec=round(duration, 3)
    )
