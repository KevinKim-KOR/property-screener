"""
테스트 공용 설정.

모든 테스트를 실전 screener.db 가 아닌 **임시 DB** 위에서 돌린다.

그동안 테스트는 프로젝트 루트의 screener.db 를 그대로 사용했다. 그래서
개발 중 수동 실행으로 남은 데이터에 기대어 통과하는 테스트가 생겼고
(E2E 파이프라인 테스트가 대표적이다), 반대로 테스트 실행이 실전 DB 를
수십만 건 규모로 오염시키기도 했다. 검증 장치가 상태에 오염되면
"테스트 통과"가 아무것도 보장하지 못한다.

DB 경로는 common.config_loader.Config.get_db_path() 가 호출 시점마다
환경변수 DB_PATH 를 읽으므로, 세션 시작 시 임시 파일로 지정하면 된다.
"""
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_test_db():
    tmp_dir = tempfile.mkdtemp(prefix="property-screener-test-")
    db_path = os.path.join(tmp_dir, "screener_test.db")

    prev = os.environ.get("DB_PATH")
    os.environ["DB_PATH"] = db_path
    print(f"\n[conftest] 테스트 전용 임시 DB 사용: {db_path}")

    yield db_path

    if prev is None:
        os.environ.pop("DB_PATH", None)
    else:
        os.environ["DB_PATH"] = prev

    # 임시 DB 및 디렉토리 정리
    for p in Path(tmp_dir).glob("*"):
        try:
            p.unlink()
        except OSError:
            pass
    try:
        os.rmdir(tmp_dir)
    except OSError:
        pass
