from unittest import mock

import pytest

from bubble_sandbox import config as bs_config
from bubble_sandbox import models as bs_models


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


@pytest.mark.parametrize(
    "w_env_names, w_exists, w_has_toml, w_has_venv, expected",
    [
        ([], [], [], [], []),
        (["nonesuch"], [False], [False], [False], []),
        (["empty"], [True], [False], [False], []),
        (["no_venv"], [True], [True], [False], []),
        (["no_toml"], [True], [False], [True], []),
        (
            ["valid"],
            [True],
            [True],
            [True],
            [
                {
                    "name": "valid",
                    "description": "Describe valid",
                    "dependencies": ["some-dep"],
                },
            ],
        ),
    ],
)
async def test_config_list_environments(
    environments_path,
    w_env_names,
    w_exists,
    w_has_toml,
    w_has_venv,
    expected,
):
    s = bs_config.Config()

    for env_name, exists, has_toml, has_venv in zip(
        w_env_names,
        w_exists,
        w_has_toml,
        w_has_venv,
        strict=True,
    ):
        env_subdir = environments_path / env_name
        if exists:
            env_subdir.mkdir(parents=True)

            if has_toml:
                toml = "\n".join(
                    [
                        "[project]",
                        f'name = "{env_name}"',
                        f'description = "Describe {env_name}"',
                        'dependencies = ["some-dep"]',
                    ]
                )
                toml_file = env_subdir / "pyproject.toml"
                toml_file.write_text(toml)

            if has_venv:
                venv_dir = env_subdir / ".venv"
                venv_dir.mkdir()

    with mock.patch("pathlib.Path.cwd") as cwd:
        cwd.return_value = environments_path.parent

        found = s.list_environments()

    assert found == [
        bs_models.EnvironmentInfo.model_validate(entry) for entry in expected
    ]


@pytest.mark.parametrize(
    "name",
    ["../etc", "foo/bar", "foo\\bar", ".."],
)
def test_config_resolve_venv_path_w_path_traversal_rejected(name):
    s = bs_config.Config()

    with pytest.raises(bs_config.InvalidEnvironmentName):
        s.resolve_venv_path(name)


def test_config_resolve_venv_path_w_missing_env_dir(environments_path):
    s = bs_config.Config(environments_pathname=str(environments_path))

    with pytest.raises(bs_config.EnvironmentNotFound):
        s.resolve_venv_path("nonexistent")


def test_config_resolve_venv_path_w_missing_venv(environments_path):
    s = bs_config.Config(environments_pathname=str(environments_path))

    environment_path = environments_path / "no-venv"
    environment_path.mkdir()

    with pytest.raises(bs_config.EnvironmentNotInitialized):
        s.resolve_venv_path("no-venv")


def test_config_resolve_venv_path_w_valid_env(
    environments_path, bare_environment
):
    s = bs_config.Config(environments_pathname=str(environments_path))

    expected = bare_environment / ".venv"

    found = s.resolve_venv_path("bare")

    assert found == expected


def test_get_config_caching(clean_os_env):
    bs_config.get_config.cache_clear()

    s1 = bs_config.get_config()
    s2 = bs_config.get_config()

    assert s1 is s2

    bs_config.get_config.cache_clear()
