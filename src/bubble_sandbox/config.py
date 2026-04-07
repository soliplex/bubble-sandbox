import functools
import pathlib

import pydantic_settings

DEFAULT_ENVIRONMENTS_PATH = pathlib.Path("environments")
DEFAULT_EXECUTION_TIMEOUT_SECS = 30
DEFAULT_MAX_OUTPUT_CHARS = 100_000


class Config(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="BUBBLE_SANDBOX_",
    )

    environments_path: pathlib.Path = DEFAULT_ENVIRONMENTS_PATH
    execution_timeout_seconds: float = DEFAULT_EXECUTION_TIMEOUT_SECS
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS


@functools.lru_cache
def get_config() -> Config:
    return Config()
