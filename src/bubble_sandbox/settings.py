import functools
import logging
import pathlib

import pydantic_settings

DEFAULT_ENVIRONMENTS_PATH = pathlib.Path("environments")
DEFAULT_WORKSPACE_PATH = pathlib.Path("workspace_data")
DEFAULT_MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_ALLOWED_EXTENSIONS = (
    ".csv",
    ".json",
    ".md",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
)
DEFAULT_EXECUTION_TIMEOUT_SECS = 30
DEFAULT_SESSION_IDLE_TIMEOUT_SECS = 3600
DEFAULT_MAX_SESSION_COUNT = 50
DEFAULT_LOG_LEVEL = logging.getLevelName(logging.INFO)


class Settings(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="BUBBLE_SANDBOX_",
    )

    environments_path: pathlib.Path = DEFAULT_ENVIRONMENTS_PATH
    workspace_path: pathlib.Path = DEFAULT_WORKSPACE_PATH
    max_upload_size_bytes: int = DEFAULT_MAX_UPLOAD_SIZE_BYTES
    allowed_extensions: list[str] = list(DEFAULT_ALLOWED_EXTENSIONS)
    execution_timeout_seconds: int = DEFAULT_EXECUTION_TIMEOUT_SECS
    session_idle_timeout_seconds: int = DEFAULT_SESSION_IDLE_TIMEOUT_SECS
    max_session_count: int = DEFAULT_MAX_SESSION_COUNT
    allow_persistent_sessions: bool = True
    log_level: str = DEFAULT_LOG_LEVEL


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
