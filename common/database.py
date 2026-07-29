import sqlite3
import os
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
    초기 DB 및 테이블을 생성하고 컬럼 마이그레이션을 자동으로 수행합니다.
    """
    from .models import get_schema_queries
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for query in get_schema_queries():
            cursor.execute(query)
        # 자동 스키마 마이그레이션 (region_name, high_price 컬럼 추가)
        for alter_sql in [
            "ALTER TABLE properties ADD COLUMN region_name TEXT DEFAULT '';",
            "ALTER TABLE properties ADD COLUMN high_price INTEGER DEFAULT 0;"
        ]:
            try:
                cursor.execute(alter_sql)
            except Exception:
                pass
        conn.commit()
