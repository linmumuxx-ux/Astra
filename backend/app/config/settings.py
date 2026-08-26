from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASTRA_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Astra"
    environment: str = "development"
    timezone: str = "Asia/Shanghai"
    database_url: str = "sqlite+aiosqlite:///./data/astra.db"
    redis_url: str = "redis://localhost:6379/0"
    workspace_root: Path = Path("./workspaces")
    config_dir: Path = Path("../configs")
    seed_demo: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"])

    scout_interval: int = 30
    dispatcher_interval: int = 5
    heartbeat_interval: int = 10
    heartbeat_timeout: int = 60
    default_max_retry_count: int = 3

    executor_type: str = "opencode_cli"
    opencode_binary: str = "opencode"
    opencode_agent: str = "maintainer"
    opencode_model: str | None = None
    opencode_timeout_seconds: int = 3600

    nr_test_system_endpoint: str = "http://localhost:8000"
    nr_test_system_discover_path: str = "/api/astra/tasks"
    nr_test_system_result_path: str = "/api/astra/tasks/{external_task_id}/result"
    nr_test_system_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
