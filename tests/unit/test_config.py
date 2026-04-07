from unittest import mock

import pytest

from bubble_sandbox import config as bs_config


@pytest.fixture
def clean_os_env():
    import os

    with mock.patch.dict(os.environ, clear=True) as cleaned:
        yield cleaned


def test_config_defaults(clean_os_env):

    s = bs_config.Config()

    assert s.environments_pathname == bs_config.DEFAULT_ENVIRONMENTS_PATHNAME
    assert (
        s.execution_timeout_seconds == bs_config.DEFAULT_EXECUTION_TIMEOUT_SECS
    )
    assert s.execution_timeout_seconds == (
        bs_config.DEFAULT_EXECUTION_TIMEOUT_SECS
    )
    assert s.max_output_chars == bs_config.DEFAULT_MAX_OUTPUT_CHARS


def test_config_from_env_vars(clean_os_env):
    clean_os_env["BUBBLE_SANDBOX_ENVIRONMENTS_PATHNAME"] = "/some/path"
    clean_os_env["BUBBLE_SANDBOX_EXECUTION_TIMEOUT_SECONDS"] = "60"
    clean_os_env["BUBBLE_SANDBOX_MAX_OUTPUT_CHARS"] = "500"

    s = bs_config.Config()

    assert s.environments_pathname == "/some/path"
    assert s.execution_timeout_seconds == 60
    assert s.max_output_chars == 500


def test_config_environments_path_wo_config_file_path(tmp_path):
    s = bs_config.Config()

    with mock.patch("pathlib.Path.cwd") as cwd:
        cwd.return_value = tmp_path

        found = s.environments_path

    assert found == tmp_path / "environments"


def test_config_environments_path_w_config_file_path(tmp_path):
    s = bs_config.Config(
        environments_pathname="testing/path",
        config_file_path=tmp_path / "config.yaml",
    )

    found = s.environments_path

    assert found == tmp_path / "testing" / "path"


def test_get_config_caching(clean_os_env):
    bs_config.get_config.cache_clear()

    s1 = bs_config.get_config()
    s2 = bs_config.get_config()

    assert s1 is s2

    bs_config.get_config.cache_clear()
