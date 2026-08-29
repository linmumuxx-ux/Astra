import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASTRA_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Astra"
    environment: str = "development"
    timezone: str = "Asia/Shanghai"

    # Local development uses SQLite without an external service. Production examples
    # use the explicit MySQL fields below. DATABASE_URL remains as a compatibility
    # escape hatch and takes precedence when supplied.
    database_url: str | None = None
    database_backend: str = "sqlite"
    database_host: str = "127.0.0.1"
    database_port: int = 3306
    database_name: str = "astra"
    database_username: str = "astra"
    database_password: str = ""
    database_charset: str = "utf8mb4"
    database_pool_recycle: int = 1800

    data_dir: Path = BACKEND_ROOT / "data"
    workspace_root: Path = BACKEND_ROOT / "workspaces"
    log_dir: Path = PROJECT_ROOT / ".astra" / "logs"
    runtime_dir: Path = PROJECT_ROOT / ".astra" / "run"
    config_dir: Path = PROJECT_ROOT / "configs"
    seed_demo: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    redis_url: str = "redis://localhost:6379/0"
    scout_interval: int = 30
    dispatcher_interval: int = 5
    heartbeat_interval: int = 10
    heartbeat_timeout: int = 60
    inactivity_timeout: int = 900
    recovery_interval: int = 30
    executor_type: str = "opencode_cli"
    opencode_binary: str = "opencode"
    opencode_agent: str | None = None
    opencode_model: str | None = None
    opencode_timeout_seconds: int = 3600
    ssh_connect_timeout_seconds: int = 10

    nr_test_system_endpoint: str = "http://localhost:8000"
    nr_test_system_discover_path: str = "/api/astra/tasks"
    nr_test_system_result_path: str = "/api/astra/tasks/{external_task_id}/result"
    nr_test_system_token: str | None = None

    @field_validator("database_backend")
    @classmethod
    def validate_database_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"mysql", "sqlite"}:
            raise ValueError("ASTRA_DATABASE_BACKEND 只支持 mysql 或 sqlite")
        return normalized

    @field_validator("database_charset")
    @classmethod
    def validate_database_charset(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "utf8mb4":
            raise ValueError("Astra MySQL 必须使用 utf8mb4 字符集")
        return normalized

    def absolute_path(self, value: Path) -> Path:
        expanded = Path(os.path.expandvars(str(value))).expanduser()
        if expanded.is_absolute():
            return expanded.resolve()
        return (PROJECT_ROOT / expanded).resolve()

    def employee_workspace_path(self, value: str | Path) -> Path:
        expanded = Path(os.path.expandvars(str(value))).expanduser()
        if expanded.is_absolute():
            return expanded.resolve()
        # Historical Astra services run from backend/. Keep existing relative
        # employee workspace values stable while removing current-directory reliance.
        return (BACKEND_ROOT / expanded).resolve()

    @property
    def resolved_data_dir(self) -> Path:
        return self.absolute_path(self.data_dir)

    @property
    def resolved_workspace_root(self) -> Path:
        return self.absolute_path(self.workspace_root)

    @property
    def resolved_log_dir(self) -> Path:
        return self.absolute_path(self.log_dir)

    @property
    def resolved_runtime_dir(self) -> Path:
        return self.absolute_path(self.runtime_dir)

    @property
    def resolved_config_dir(self) -> Path:
        return self.absolute_path(self.config_dir)

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url:
            if self.database_url.startswith("sqlite+aiosqlite:///./"):
                relative = self.database_url.removeprefix("sqlite+aiosqlite:///./")
                # Before configuration was centralized, Astra services ran from
                # backend/. Preserve that location for existing relative URLs.
                path = (BACKEND_ROOT / relative).resolve().as_posix()
                return f"sqlite+aiosqlite:///{path}"
            return self.database_url
        if self.database_backend == "sqlite":
            path = (self.resolved_data_dir / "astra.db").as_posix()
            return f"sqlite+aiosqlite:///{path}"

        username = quote(self.database_username, safe="")
        password = quote(self.database_password, safe="")
        credentials = username if not password else f"{username}:{password}"
        database = quote(self.database_name, safe="")
        return (
            f"mysql+asyncmy://{credentials}@{self.database_host}:{self.database_port}/"
            f"{database}?charset={self.database_charset}"
        )

    @property
    def database_description(self) -> str:
        if self.database_url:
            scheme, _, remainder = self.database_url.partition("://")
            if "@" in remainder:
                remainder = remainder.split("@", 1)[1]
            return f"{scheme}://{remainder}"
        if self.database_backend == "mysql":
            return (
                f"mysql://{self.database_host}:{self.database_port}/"
                f"{self.database_name}?charset={self.database_charset}"
            )
        return str(self.resolved_data_dir / "astra.db")

    @property
    def redis_description(self) -> str:
        scheme, _, remainder = self.redis_url.partition("://")
        if "@" in remainder:
            remainder = remainder.split("@", 1)[1]
        return f"{scheme}://{remainder}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
