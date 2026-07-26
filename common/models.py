def get_schema_queries():
    """
    SQLite DB 초기화에 사용될 DDL 쿼리 리스트를 반환합니다.
    """
    return [
        """
        CREATE TABLE IF NOT EXISTS properties (
            property_id TEXT PRIMARY KEY,
            complex_code TEXT,
            complex_name TEXT,
            building_dong TEXT,
            floor TEXT,
            asking_price INTEGER,
            area_pyeong REAL,
            drop_rate REAL,
            registered_date TEXT,
            updated_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sent_alerts (
            property_id TEXT PRIMARY KEY,
            asking_price INTEGER,
            sent_at TEXT,
            FOREIGN KEY(property_id) REFERENCES properties(property_id)
        )
        """
    ]
