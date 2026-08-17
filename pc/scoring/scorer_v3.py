# pc/scoring/scorer_v3.py
"""
L1 (시장 점수: 단지 x 평형) 4-Block Peer-Group 상대평가 기반 V3 스코어링 실행 진입점 모듈
(SCORING_V3_DESIGN.md §12.1, §13, §19 P1-AC10, P1-AC11).
"""
import uuid
import time
import math
import statistics
import os
import yaml
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

from common.database import get_db_connection
from common.peer_group import select_peer_group
from .normalizer import normalize_block_a, normalize_block_b, normalize_block_c, normalize_block_d
from .gate import check_quality_gates, check_coverage_gate
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

class RunValidationError(RuntimeError):
    """run 단위 검증(V10/V11) 위반으로 실행을 무효 처리한 경우."""


def verify_run_level_gates(scored, base_date: str,
                           median_center: float = 50.0, median_tol: float = 3.0,
                           top_ratio: float = 0.10) -> None:
    """
    설계서 §11.5.2 run 단위 검증.

      V10  4개 블록 점수가 전부 상위 10%인 매물이 존재  -> run 실패 (정규화 미작동)
      V11  점수 중앙값이 50 ± 3 밖                      -> run 실패

    개별 매물이 아니라 실행 전체를 본다. 위반하면 예외를 던져 화면 갱신을 막는다(C14).
    이 두 검증은 설계서에 명세되어 있었으나 코드에는 구현되어 있지 않았고,
    그래서 점수가 두 값으로 붕괴한 상태가 화면에 그대로 표시됐다.
    """
    if not scored:
        return

    violations = []

    # V11: 점수 중앙값
    scores = sorted(x["market_score"] for x in scored if x["market_score"] is not None)
    if scores:
        med = statistics.median(scores)
        if abs(med - median_center) > median_tol:
            violations.append(
                f"V11 점수 중앙값 {med:.1f} (정상 {median_center - median_tol:.0f}~"
                f"{median_center + median_tol:.0f})"
            )

    # V10: 4개 블록이 모두 상위 10%인 매물
    n_blocks = 4
    cols = [[x["blocks"][i] for x in scored if x["blocks"][i] is not None] for i in range(n_blocks)]
    if all(cols):
        thr = []
        for c in cols:
            c_sorted = sorted(c)
            idx = min(len(c_sorted) - 1, int(len(c_sorted) * (1.0 - top_ratio)))
            thr.append(c_sorted[idx])
        n_all_top = sum(
            1 for x in scored
            if all(x["blocks"][i] is not None and x["blocks"][i] >= thr[i] for i in range(n_blocks))
        )
        if n_all_top > 0:
            violations.append(f"V10 4개 블록이 모두 상위 {top_ratio:.0%}인 매물 {n_all_top:,}건 (정규화 미작동 의심)")

    if violations:
        raise RunValidationError(
            f"[{base_date}] run 단위 검증 실패 — " + " / ".join(violations) +
            ". 이번 실행 결과를 반영하지 않았습니다(직전 결과 유지)."
        )


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
        # NOTE (C14): 이전 결과를 먼저 지우지 않는다. 행을 모아 두었다가
        # run 단위 검증(V10/V11)을 통과한 뒤에만 지우고 새로 쓴다.
        # 검증에 실패하면 화면은 직전 정상 run 결과를 그대로 유지한다.
        pending_rows = []
        cur.execute("""
            SELECT s.*, c.complex_name, c.sgg_cd, c.umd_cd, c.region_name AS umd_nm, c.brand, c.subway_dist_m, c.elem_school_dist_m, c.cbd_transit_min, c.total_households
            FROM complex_area_stats s
            LEFT JOIN complexes c ON s.complex_code = c.complex_code
            WHERE s.base_date = ?
        """, (base_date,))
        all_items = [dict(r) for r in cur.fetchall()]
        total_count = len(all_items)

        min_n = cfg.get("universe", {}).get("min_peer_n", 10)

        def _insert_nonscored(it, gate_status, reason, pg_key, pg_n, cov):
            pending_rows.append((
                run_id, base_date, it["complex_code"], it["area_type"],
                pg_key, pg_n,
                None, None, None, None,          # block_value/flow/location/quality
                None, None, 1.0, None,           # raw/base/risk/market_score
                gate_status, str(reason), cov, "{}"
            ))

        # ── 1단계: 품질 게이트 판정 (단지 자체 데이터만, 비교군 불필요) ──
        eligible = []
        for it in all_items:
            gate_status, gate_reason = check_quality_gates(it)
            if gate_status == "EXCLUDED":
                excluded_reasons[str(gate_reason)] += 1
                # 게이트에서 걸러졌으므로 비교군은 계산하지 않았다.
                # (peer_group_key 는 NOT NULL 이라 그 사실을 나타내는 값을 넣는다)
                _insert_nonscored(it, "EXCLUDED", gate_reason, "NOT_EVALUATED", 0, None)
                continue
            eligible.append(it)

        # ── 2단계: 비교군은 '게이트를 통과한 단지'로만 구성 ──
        #     제외된 단지를 넣으면 통계값이 전부 같아 MAD 가 0이 되고
        #     모든 편차가 0으로 계산되어 점수가 붕괴한다.
        peer_pool = eligible
        fallback_counts = {"UMD": 0, "SGG": 0, "BELT": 0, "NONE": 0}

        # ── 3단계: 점수 산출 ──
        scored_items = []
        for it in eligible:
            peers, pg_key, pg_n, pg_level = select_peer_group(it, peer_pool, min_n, min_n, min_n)
            fallback_counts[pg_level] += 1

            if pg_level == "NONE":
                # 비교군을 못 만들었다. 제외가 아니라 '점수 없음'으로 남긴다.
                # 다른 지표(하락률·전세가율 등)는 화면에 그대로 보여야 한다.
                excluded_reasons["NO_PEER_GROUP(점수결측)"] += 1
                _insert_nonscored(it, "PASS", "NO_PEER_GROUP", pg_key, pg_n, None)
                continue

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

            # ── 4단계: 커버리지 게이트는 점수를 낸 뒤에 판정 ──
            gate_status, gate_reason = check_coverage_gate(total_cov)
            if gate_status == "EXCLUDED":
                excluded_reasons[str(gate_reason)] += 1
                _insert_nonscored(it, "EXCLUDED", gate_reason, pg_key, pg_n, total_cov)
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

        print(f"[ScorerV3] 비교군 폴백 — 법정동 {fallback_counts['UMD']:,} / "
              f"구 {fallback_counts['SGG']:,} / 벨트 {fallback_counts['BELT']:,} / "
              f"실패(점수결측) {fallback_counts['NONE']:,}  (min_peer_n={min_n})")

        # Φ (CDF) 매핑 - 유니버스 내 평균/표준편차 기반 0~100 스케일
        passed_count = len(scored_items)
        scored_out = []
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

                pending_rows.append((
                    run_id, base_date, it["complex_code"], it["area_type"],
                    it["_pg_key"], it["_pg_n"],
                    it["_b_val"], it["_b_flw"], it["_b_loc"], it["_b_qty"],
                    it["_raw_score"], base_score, risk_mult, market_score,
                    "PASS", None, it["_total_cov"], evidence_json
                ))
                scored_out.append({
                    "market_score": market_score,
                    "blocks": (it["_b_val"], it["_b_flw"], it["_b_loc"], it["_b_qty"]),
                })

        # ── run 단위 검증 (V10 / V11) 후에만 반영 ──
        verify_run_level_gates(scored_out, base_date)

        cur.execute("DELETE FROM market_scores WHERE base_date = ?", (base_date,))
        cur.executemany("""
            INSERT OR REPLACE INTO market_scores (
                run_id, base_date, complex_code, area_type,
                peer_group_key, peer_group_n,
                block_value, block_flow, block_location, block_quality,
                raw_score, base_score, risk_multiplier, market_score,
                gate_status, gate_reason, coverage_ratio, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, pending_rows)

        # score_runs 이력 적재
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
