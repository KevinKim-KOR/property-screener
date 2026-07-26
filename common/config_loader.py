import os
import yaml
from pathlib import Path

try:
    from dotenv import load_dotenv
    # 상위 디렉토리의 .env 로드
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
except ImportError:
    pass

class Config:
    _config_data = None
    _base_dir = Path(__file__).resolve().parent.parent

    @classmethod
    def load(cls):
        if cls._config_data is None:
            config_path = cls._base_dir / 'config.yaml'
            with open(config_path, 'r', encoding='utf-8') as f:
                cls._config_data = yaml.safe_load(f)
        return cls._config_data

    @classmethod
    def get_db_path(cls):
        return os.environ.get('DB_PATH', str(cls._base_dir / 'screener.db'))

    @classmethod
    def get_telegram_config(cls):
        return {
            'bot_token': os.environ.get('TELEGRAM_BOT_TOKEN'),
            'chat_id': os.environ.get('TELEGRAM_CHAT_ID')
        }

    @classmethod
    def get_target_regions(cls):
        return cls.load().get('target_regions', [])

    @classmethod
    def get_budget_limits(cls):
        return cls.load().get('budget', {})

    @classmethod
    def get_area_limits(cls):
        return cls.load().get('area', {})
        
    @classmethod
    def get_drop_rate_threshold(cls):
        return cls.load().get('drop_rate_threshold', {}).get('percentage', 0.0)

    @classmethod
    def get_kakao_api_key(cls):
        return os.environ.get('KAKAO_REST_API_KEY')
