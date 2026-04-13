import functools
import pathlib
import sys
import tomllib

import pydantic_settings

from bubble_sandbox import models

DEFAULT_ENVIRONMENTS_PATHNAME = "environments"
DEFAULT_EXECUTION_TIMEOUT_SECS = 30
DEFAULT_MAX_OUTPUT_CHARS = 100_000

_VENV_PYTHON = (
    pathlib.PurePosixPath("bin", "python")
    if sys.platform != "win32"
    else pathlib.PureWindowsPath("Scripts", "python.exe")
)


class InvalidEnvironmentName(ValueError):
    def __init__(self, env_name: str):
        self.env_name = env_name
        super().__init__(f"Invalid environment name: {env_name!r}")


class EnvironmentNotFound(FileNotFoundError):
    def __init__(self, env_name: str):
        self.env_name = env_name
        super().__init__(f"Environment not found: {env_name!r}")


class EnvironmentNotInitialized(FileNotFoundError):
    def __init__(self, env_name: str, venv_python: pathlib.Path):
        self.env_name = env_name
        self.venv_python = venv_python
        super().__init__(
            f"No venv found for environment {env_name!r}: "
            f"(expected {venv_python})"
        )


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

    def list_environments(self) -> list[models.EnvironmentInfo]:
        environments = []
        root = self.environments_path

        for subpath in sorted(root.glob("*")):
            if (subpath / ".venv").is_dir():
                toml_path = subpath / "pyproject.toml"

                if toml_path.is_file():
                    toml_text = toml_path.read_text()
                    toml = tomllib.loads(toml_text)
                    project = toml["project"]
                    environments.append(
                        models.EnvironmentInfo(
                            name=project["name"],
                            description=project.get("description", ""),
                            dependencies=project.get("dependencies", []),
                        )
                    )

        return environments

    def resolve_venv_path(
        self,
        environment_name: str,
    ) -> pathlib.Path:
        """Return the path to an environment's virtualenv"""

        if (
            "/" in environment_name
            or "\\" in environment_name
            or ".." in environment_name
        ):
            raise InvalidEnvironmentName(environment_name)

        environment_path = self.environments_path / environment_name

        if not environment_path.is_dir():
            raise EnvironmentNotFound(environment_path)

        venv_python = environment_path / ".venv" / _VENV_PYTHON

        if not venv_python.exists():
            raise EnvironmentNotInitialized(environment_name, venv_python)

        return environment_path / ".venv"


@functools.lru_cache
def get_config() -> Config:
    return Config()
