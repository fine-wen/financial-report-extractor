from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")

    app_name: str = "企业财务资料工作台"
    database_url: str = "sqlite:///./data/enterprise_knowledge.db"
    storage_dir: Path = Path("./storage")
    max_upload_mb: int = 100
    mineru_api_url: str | None = None
    mineru_timeout_seconds: int = 900
    mineru_retry_count: int = 2
    mineru_poll_seconds: int = 5
    mineru_max_task_seconds: int = 172800


settings = Settings()
