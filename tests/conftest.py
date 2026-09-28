import pathlib
import shutil

import pytest

from bubble_sandbox import config as bs_config


@pytest.fixture
def environments_path(tmp_path):
    result = tmp_path / "environments"
    result.mkdir()
    return result


@pytest.fixture
def sandbox_config(tmp_path) -> bs_config.Config:
    config_file_path = tmp_path / "config.yaml"

    return bs_config.Config(
        environments_pathname="environments",
        execution_timeout_seconds=5,
        config_file_path=config_file_path,
    )


@pytest.fixture
def bare_environment(sandbox_config):
    bare_path = pathlib.Path("environments/bare")

    if not (bare_path / ".venv").is_dir():  # pragma: no cover
        pytest.fail(
            f"{bare_path}/.venv is missing: the per-environment venvs are "
            "excluded from the uv workspace and must be built separately. "
            f"Run 'uv sync --python=<system python>' in {bare_path}.",
            pytrace=False,
        )

    settings_env_path = sandbox_config.environments_path
    settings_bare_path = settings_env_path / "bare"
    # Preserve interpreter symlinks when relocating the venv.
    shutil.copytree(bare_path, settings_bare_path, symlinks=True)

    yield settings_bare_path

    shutil.rmtree(settings_bare_path)
