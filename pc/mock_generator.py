import sys
from pathlib import Path
from datetime import datetime

# 프로젝트 루트 참조
sys.path.append(str(Path(__file__).resolve().parent.parent))
from common.database import get_db_connection, init_db

def generate_mock_data():
    init_db()
    mock_data = [
        ("PROP001", "1165010700", "반포자이", "101동", "15/35층", 350000, 34.0, 15.5, datetime.now().isoformat(), datetime.now().isoformat()),
        ("PROP002", "1165010700", "래미안퍼스티지", "112동", "5/28층", 380000, 34.0, 5.0, datetime.now().isoformat(), datetime.now().isoformat()),
        ("PROP003", "1165010700", "아크로리버파크", "105동", "20/38층", 450000, 34.0, 12.0, datetime.now().isoformat(), datetime.now().isoformat())
    ]
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT OR REPLACE INTO properties 
            (property_id, complex_code, complex_name, building_dong, floor, asking_price, area_pyeong, drop_rate, registered_date, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, mock_data)
        conn.commit()
    print("[Mock] Inserted 3 mock properties into screener.db")

if __name__ == "__main__":
    generate_mock_data()
