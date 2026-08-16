import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager
from .config_loader import Config

@contextmanager
def get_db_connection():
    """
    SQLite 데이터베이스 커넥션을 컨텍스트 매니저로 제공합니다.
    """
    db_path = Config.get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """
    초기 DB 및 테이블을 생성하고 SCORING_V2 마이그레이션(schema_version)을 자동으로 수행합니다.
    """
    from .models import get_schema_queries
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 1. 모든 DDL 쿼리(신규 테이블, 인덱스 포함) 실행
        for query in get_schema_queries():
            cursor.execute(query)
        
        # 2. 기존 v1 컬럼 자동 마이그레이션 (멱등성 보장)
        for alter_sql in [
            "ALTER TABLE properties ADD COLUMN region_name TEXT DEFAULT '';",
            "ALTER TABLE properties ADD COLUMN high_price INTEGER DEFAULT 0;",
            "ALTER TABLE properties ADD COLUMN change_1m REAL DEFAULT 0.0;",
            "ALTER TABLE properties ADD COLUMN change_3m REAL DEFAULT 0.0;",
            "ALTER TABLE properties ADD COLUMN change_6m REAL DEFAULT 0.0;"
        ]:
            try:
                cursor.execute(alter_sql)
            except sqlite3.OperationalError:
                # 의도적 삼킴: 이미 존재하는 컬럼에 대한 ALTER 는 반드시 실패한다.
                # 이 루프는 멱등성(여러 번 실행해도 같은 결과) 보장이 목적이므로
                # 실패를 넘기는 것이 정상 동작이다. 다른 예외까지 삼키지 않도록
                # sqlite3.OperationalError 로 한정한다.
                pass
        
        # 3. schema_version 체크 및 001_scoring_v2 마이그레이션 실행
        cursor.execute("SELECT version FROM schema_version WHERE version = 1")
        row = cursor.fetchone()
        if not row:
            v2_alters = [
                "ALTER TABLE properties ADD COLUMN area_type TEXT;",
                "ALTER TABLE properties ADD COLUMN exclusive_area REAL;",
                "ALTER TABLE properties ADD COLUMN deal_gap_pct REAL;",
                "ALTER TABLE properties ADD COLUMN floor_grade TEXT;",
                "ALTER TABLE properties ADD COLUMN score_v1 REAL;",
                "ALTER TABLE properties ADD COLUMN last_seen_at TEXT;",
                "ALTER TABLE complexes ADD COLUMN bonbun INTEGER;",
                "ALTER TABLE complexes ADD COLUMN bubun INTEGER;",
                "ALTER TABLE complexes ADD COLUMN road_name TEXT;"
            ]
            for alter_sql in v2_alters:
                try:
                    cursor.execute(alter_sql)
                except sqlite3.OperationalError:
                    # 의도적 삼킴: 멱등성 보장용 (이미 존재하는 컬럼이면 실패가 정상).
                    # sqlite3.OperationalError 로 한정한다.
                    pass
            now_str = datetime.now().isoformat()
            cursor.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                (1, now_str, "001_scoring_v2 initial schema and column migration")
            )
        # 4. land_leasehold 컬럼 마이그레이션 (v4.3 API 지원)
        for alter_sql in [
            "ALTER TABLE trades_sale ADD COLUMN land_leasehold TEXT;",
        ]:
            try:
                cursor.execute(alter_sql)
            except sqlite3.OperationalError:
                # 의도적 삼킴: 이미 존재하는 컬럼에 대한 ALTER 는 반드시 실패한다.
                # 이 루프는 멱등성(여러 번 실행해도 같은 결과) 보장이 목적이므로
                # 실패를 넘기는 것이 정상 동작이다. 다른 예외까지 삼키지 않도록
                # sqlite3.OperationalError 로 한정한다.
                pass
        
        conn.commit()
