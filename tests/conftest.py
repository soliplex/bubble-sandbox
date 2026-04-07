import pathlib
import shutil

import pytest

from bubble_sandbox import config as bs_config


@pytest.fixture
def sandbox_config(tmp_path: pathlib.Path) -> bs_config.Config:
    environments_path = tmp_path / "environments"
    environments_path.mkdir()
    config_file_path = tmp_path / "config.yaml"

    return bs_config.Config(
        environments_pathname="environments",
        execution_timeout_seconds=5,
        config_file_path=config_file_path,
    )


@pytest.fixture
def bare_environment(sandbox_config):
    bare_path = pathlib.Path("environments/bare")

    settings_env_path = sandbox_config.environments_path
    settings_bare_path = settings_env_path / "bare"
    shutil.copytree(bare_path, settings_bare_path)

    yield settings_bare_path

    shutil.rmtree(settings_bare_path)
