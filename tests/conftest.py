import pathlib
import shutil

import pytest

from bubble_sandbox import settings as bs_settings


@pytest.fixture
def sandbox_settings(tmp_path: pathlib.Path) -> bs_settings.Settings:
    environments_path = tmp_path / "environments"
    environments_path.mkdir()

    return bs_settings.Settings(
        environments_path=environments_path,
        execution_timeout_seconds=5,
    )


@pytest.fixture
def bare_environment(sandbox_settings):
    bare_path = pathlib.Path("environments/bare")

    settings_env_path = sandbox_settings.environments_path
    settings_bare_path = settings_env_path / "bare"
    shutil.copytree(bare_path, settings_bare_path)

    yield settings_bare_path

    shutil.rmtree(settings_bare_path)
