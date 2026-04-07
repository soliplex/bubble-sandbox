import functools
import pathlib

import pydantic_settings

DEFAULT_ENVIRONMENTS_PATHNAME = "environments"
DEFAULT_EXECUTION_TIMEOUT_SECS = 30
DEFAULT_MAX_OUTPUT_CHARS = 100_000


class Config(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="BUBBLE_SANDBOX_",
    )

    config_file_path: pathlib.Path | None = None
    environments_pathname: str = DEFAULT_ENVIRONMENTS_PATHNAME
    execution_timeout_seconds: float = DEFAULT_EXECUTION_TIMEOUT_SECS
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS

    @property
    def environments_path(self) -> pathlib.Path:
        if self.config_file_path is not None:
            anchor = self.config_file_path.parent
        else:
            anchor = pathlib.Path.cwd()

        return anchor / self.environments_pathname


@functools.lru_cache
def get_config() -> Config:
    return Config()
