# pc/verification/score_distribution.py
"""
설계서 §19.0 "점수가 제대로 퍼져 있나" 판정.

판정 기준이 문서에만 있고 코드에 없어서 매 실행마다 사람이 손으로 계산해야 했다.
여기에 한 곳으로 모아 두고, 자가검증 리포트와 run 검증이 같은 값을 쓰게 한다.

기준 (v4.3 개정)
  중앙값        47 ~ 53
  90점 이상     12% 이하   (상한만 검사)
  10점 이하     12% 이하   (상한만 검사)

§9.5 의 Φ(CDF) 매핑이 정규분포를 균등분포로 바꾸므로 상위 10%가 90점을
넘는 것이 정상이다. 개정 전 기준 0~2% 는 원점수를 그대로 쓰는 전제의
값이라 Φ 매핑과 양립하지 않았고, 정상 실행에도 매번 위반으로 찍혔다.

**꼬리는 상한만 본다.** 꼬리가 두꺼운 것은 계산 붕괴 신호지만, 얇은 것은
문제가 아니다. "점수가 충분히 퍼져 있나"는 중앙값과 서로 다른 점수 개수가
이미 잡아준다. 표본이 작으면 꼬리 비율이 크게 흔들리므로(181건이면 약
2.2%p) 하한을 두면 정상 실행이 위반으로 찍힌다.
"""
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional

MEDIAN_CENTER = 50.0
MEDIAN_TOL = 3.0
TAIL_MAX_PCT = 12.0   # 상한만 검사한다 (하한 없음)
HIGH_CUT = 90.0
LOW_CUT = 10.0


@dataclass(frozen=True)
class Check:
    label: str
    value: float
    display: str
    normal_range: str
    ok: bool


@dataclass(frozen=True)
class DistributionResult:
    n: int
    checks: List[Check]

    @property
    def all_ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def failures(self) -> List[Check]:
        return [c for c in self.checks if not c.ok]


def evaluate_score_distribution(scores: List[float]) -> Optional[DistributionResult]:
    """채점된 점수 목록을 받아 §19.0 분포 판정을 수행한다."""
    scores = [s for s in scores if s is not None]
    if not scores:
        return None

    n = len(scores)
    med = statistics.median(scores)
    hi = sum(1 for s in scores if s >= HIGH_CUT)
    lo = sum(1 for s in scores if s <= LOW_CUT)
    hi_pct = hi / n * 100.0
    lo_pct = lo / n * 100.0

    checks = [
        Check("중간 점수", med, f"{med:.1f}점",
              f"{MEDIAN_CENTER - MEDIAN_TOL:.0f}~{MEDIAN_CENTER + MEDIAN_TOL:.0f}점",
              abs(med - MEDIAN_CENTER) <= MEDIAN_TOL),
        Check("90점 이상", hi_pct, f"{hi}곳 ({hi_pct:.1f}%)",
              f"{TAIL_MAX_PCT:.0f}% 이하", hi_pct <= TAIL_MAX_PCT),
        Check("10점 이하", lo_pct, f"{lo}곳 ({lo_pct:.1f}%)",
              f"{TAIL_MAX_PCT:.0f}% 이하", lo_pct <= TAIL_MAX_PCT),
    ]
    return DistributionResult(n=n, checks=checks)


def tail_sampling_sd_pct(n: int, tail_ratio: float = 0.10) -> float:
    """
    표본 n 에서 꼬리 비율의 표준편차(%p). 범위를 벗어났을 때
    "실제 이상"인지 "표본이 작아서"인지 가늠하는 데 쓴다.
    """
    if n <= 0:
        return 0.0
    return (tail_ratio * (1 - tail_ratio) / n) ** 0.5 * 100.0


def format_report_section(res: Optional[DistributionResult]) -> str:
    """§19.0 리포트 2번 항목 형식으로 출력한다."""
    if res is None:
        return "2. 점수가 제대로 퍼져 있나\n\n  채점된 단지가 없어 판정할 수 없습니다."
    lines = ["2. 점수가 제대로 퍼져 있나", ""]
    for c in res.checks:
        lines.append(f"  {c.label:10} {c.display:14} (정상: {c.normal_range})   "
                     f"{'✓' if c.ok else '✕'}")
    lines.append("")
    if res.all_ok:
        lines.append("  → 정상입니다")
    else:
        sd = tail_sampling_sd_pct(res.n)
        lines.append("  → 아래 항목이 정상 범위를 벗어났습니다: "
                     + ", ".join(c.label for c in res.failures()))
        lines.append(f"    (채점 {res.n:,}곳 기준, 꼬리 비율의 표본 흔들림은 약 {sd:.1f}%p)")
    return "\n".join(lines)


def load_latest_scores(db_path: Optional[str] = None):
    """가장 최근 base_date 의 채점 결과와 결측 건수를 읽는다."""
    import os
    import sqlite3
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
    from common.config_loader import Config

    if db_path is None:
        db_path = Config.get_db_path()
    if not os.path.exists(db_path):
        return None, [], 0

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT MAX(base_date) FROM market_scores").fetchone()
        base_date = row[0] if row else None
        if not base_date:
            return None, [], 0
        scores = [r[0] for r in conn.execute(
            "SELECT market_score FROM market_scores "
            "WHERE base_date = ? AND market_score IS NOT NULL", (base_date,))]
        missing = conn.execute(
            "SELECT COUNT(*) FROM market_scores WHERE base_date = ? "
            "AND gate_status = 'PASS' AND market_score IS NULL", (base_date,)).fetchone()[0]
        return base_date, scores, missing
    finally:
        conn.close()


def main() -> int:
    """
    python -m pc.verification.score_distribution

    현재 DB의 최신 채점 결과로 §19.0 분포 판정을 출력한다.
    재개 시 이 값을 docs/SCORING_RESUME_20260817.md 의 기준값과 비교하면
    그동안 무엇이 달라졌는지 바로 알 수 있다.
    """
    base_date, scores, missing = load_latest_scores()
    if base_date is None:
        print("채점 결과가 없습니다. 화면에서 [최신 자료 가져오기]를 먼저 실행하세요.")
        return 1

    print(f"■ 점수 분포 판정 · 기준일 {base_date}")
    print()
    print(format_report_section(evaluate_score_distribution(scores)))
    print()
    total = len(scores) + missing
    if total:
        print(f"  점수 결측(비교군 부족)  {missing:,}곳 / 게이트 통과 {total:,}곳 "
              f"({missing / total * 100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
