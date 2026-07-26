import os
import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from common.config_loader import Config

class SyncManager:
    @staticmethod
    def download_db():
        print("[SyncManager] OCI SFTP is not configured yet. Using local screener.db.")
        db_path = Config.get_db_path()
        if not os.path.exists(db_path):
            print("[SyncManager] Local screener.db not found. Generating mock data...")
            from pc.mock_generator import generate_mock_data
            generate_mock_data()
            
    @staticmethod
    def upload_results(results):
        output_path = Path(Config.get_db_path()).parent / "ml_results.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[SyncManager] Results saved locally to {output_path} (Upload mocked).")
