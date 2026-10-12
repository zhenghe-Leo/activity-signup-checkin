"""配置项（01-spec §7.2、03 §10.3）。

从环境变量和项目根目录下的 .env 读取；所有项都有默认值。
密钥用 SecretStr 保存，打印 Settings 时不会显示明文。
"""
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/backend/app/config.py → 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 预置标签库（BR-23）。不是可配置项：改动会影响种子数据和评测集。
TAG_LIBRARY = ["讲座", "竞赛", "志愿服务", "文体", "学术", "就业", "社团", "培训", "展览", "其他"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_port: int = 8000
    app_timezone: str = "Asia/Shanghai"

    database_path: str = "./data/app.db"
    db_busy_timeout_ms: int = 5000

    checkin_open_before_minutes: int = 30
    capacity_max: int = 1000
    title_max_len: int = 50
    summary_max_len: int = 500
    notes_max_items: int = 5
    note_max_len: int = 100
    tags_min: int = 1
    tags_max: int = 5

    ai_timeout_seconds: float = 15
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"

    @property
    def db_file(self) -> Path:
        """数据库文件的绝对路径；相对路径以项目根目录为基准。"""
        p = Path(self.database_path)
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

    @property
    def tz(self) -> ZoneInfo:
        """日期边界与页面展示用的时区（Windows 需要 tzdata 包提供时区数据）。"""
        return ZoneInfo(self.app_timezone)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.deepseek_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
