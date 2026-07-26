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
    초기 DB 및 테이블을 생성합니다.
    """
    from .models import get_schema_queries
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for query in get_schema_queries():
            cursor.execute(query)
        conn.commit()
