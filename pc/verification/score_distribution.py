# pc/verification/score_distribution.py
"""
설계서 §19.0 "점수가 제대로 퍼져 있나" 판정.

판정 기준이 문서에만 있고 코드에 없어서 매 실행마다 사람이 손으로 계산해야 했다.
여기에 한 곳으로 모아 두고, 자가검증 리포트와 run 검증이 같은 값을 쓰게 한다.

기준 (v4.3 개정)
  중앙값        47 ~ 53
  90점 이상     8 ~ 12%
  10점 이하     8 ~ 12%

상·하위 비율의 기준이 8~12% 인 이유: §9.5 의 Φ(CDF) 매핑이 정규분포를
균등분포로 바꾸므로, 상위 10%가 90점을 넘는 것이 정상이다. 개정 전 기준
0~2% 는 원점수를 그대로 쓰는 전제의 값이라 Φ 매핑과 양립하지 않았고,
정상 실행에도 매번 위반으로 찍혔다.
"""
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional

MEDIAN_CENTER = 50.0
MEDIAN_TOL = 3.0
TAIL_MIN_PCT = 8.0
TAIL_MAX_PCT = 12.0
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
              f"{TAIL_MIN_PCT:.0f}~{TAIL_MAX_PCT:.0f}%",
              TAIL_MIN_PCT <= hi_pct <= TAIL_MAX_PCT),
        Check("10점 이하", lo_pct, f"{lo}곳 ({lo_pct:.1f}%)",
              f"{TAIL_MIN_PCT:.0f}~{TAIL_MAX_PCT:.0f}%",
              TAIL_MIN_PCT <= lo_pct <= TAIL_MAX_PCT),
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
