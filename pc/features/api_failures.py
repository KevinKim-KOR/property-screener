# pc/features/api_failures.py
"""
외부 API(카카오 로컬) 호출 실패를 개별로는 넘기되, 실행 끝에 집계해 보고하고
실패가 과반이면 중단하기 위한 공용 추적기.

과거에는 각 스크립트가 `except Exception: pass` 로 호출 실패를 통째로 삼켰다.
그 결과 API 키가 만료되거나 네트워크가 끊겨 전 건이 실패해도 아무 신호 없이
"입지 정보 없음"인 것처럼 DB가 채워졌다.
"""
from typing import Optional


class ApiMostlyFailedError(RuntimeError):
    """외부 API 호출이 과반 실패하여 중단한 경우."""


class ApiFailureTracker:
    def __init__(self, label: str, total: int, abort_ratio: float = 0.5):
        """
        label: 보고 문구에 쓸 작업 이름 (예: "지오코딩")
        total: 전체 대상 건수
        abort_ratio: 이 비율 이상 실패하면 중단 (기본 0.5 = 절반)
        """
        self.label = label
        self.total = total
        self.abort_ratio = abort_ratio
        self.failures = 0
        self.first_error: Optional[str] = None

    def record_failure(self, key: str, exc: BaseException) -> None:
        """개별 호출 실패를 기록한다. 과반을 넘기면 즉시 중단한다."""
        self.failures += 1
        if self.first_error is None:
            self.first_error = f"{type(exc).__name__}: {exc}"
        # 처음 몇 건은 원인을 알 수 있게 바로 출력한다.
        if self.failures <= 3:
            print(f"[{self.label}] 호출 실패 ({key}): {type(exc).__name__}: {exc}")
        self._abort_if_mostly_failed()

    def _abort_if_mostly_failed(self) -> None:
        if self.total <= 0:
            return
        if self.failures >= self.total * self.abort_ratio:
            raise ApiMostlyFailedError(
                f"{self.label}: {self.total:,}곳 중 {self.failures:,}곳 실패 "
                f"(기준: {self.abort_ratio:.0%} 이상 실패 시 중단). "
                f"첫 오류: {self.first_error}. "
                f"API 키(KAKAO_REST_API_KEY)와 네트워크 상태를 확인하세요."
            )

    def summary(self) -> str:
        """실행 끝에 출력할 집계 문구."""
        return f"{self.label} {self.total:,}곳 중 {self.failures:,}곳 실패"

    def report(self) -> None:
        print(f"[{self.label}] {self.summary()}")
