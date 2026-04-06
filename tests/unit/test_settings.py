import pathlib
from unittest import mock

import pytest

from bubble_sandbox import settings  # Settings get_settings


@pytest.fixture
def clean_os_env():
    import os

    with mock.patch.dict(os.environ, clear=True) as cleaned:
        yield cleaned


def test_settings_defaults(clean_os_env):

    s = settings.Settings()

    assert s.environments_path == settings.DEFAULT_ENVIRONMENTS_PATH
    assert s.workspace_path == settings.DEFAULT_WORKSPACE_PATH
    assert s.max_upload_size_bytes == settings.DEFAULT_MAX_UPLOAD_SIZE_BYTES
    assert s.allowed_extensions == list(settings.DEFAULT_ALLOWED_EXTENSIONS)
    assert (
        s.execution_timeout_seconds == settings.DEFAULT_EXECUTION_TIMEOUT_SECS
    )
    assert s.execution_timeout_seconds == (
        settings.DEFAULT_EXECUTION_TIMEOUT_SECS
    )
    assert s.session_idle_timeout_seconds == (
        settings.DEFAULT_SESSION_IDLE_TIMEOUT_SECS
    )
    assert s.max_output_chars == settings.DEFAULT_MAX_OUTPUT_CHARS
    assert s.max_session_count == settings.DEFAULT_MAX_SESSION_COUNT
    assert s.log_level == settings.DEFAULT_LOG_LEVEL


def test_settings_from_env_vars(clean_os_env):
    clean_os_env["BUBBLE_SANDBOX_ENVIRONMENTS_PATH"] = "/some/path"
    clean_os_env["BUBBLE_SANDBOX_WORKSPACE_PATH"] = "/other/path"
    clean_os_env["BUBBLE_SANDBOX_MAX_UPLOAD_SIZE_BYTES"] = "5000"
    clean_os_env["BUBBLE_SANDBOX_ALLOWED_EXTENSIONS"] = '[".py",".txt"]'
    clean_os_env["BUBBLE_SANDBOX_EXECUTION_TIMEOUT_SECONDS"] = "60"
    clean_os_env["BUBBLE_SANDBOX_SESSION_IDLE_TIMEOUT_SECONDS"] = "7200"
    clean_os_env["BUBBLE_SANDBOX_MAX_OUTPUT_CHARS"] = "500"
    clean_os_env["BUBBLE_SANDBOX_MAX_SESSION_COUNT"] = "100"
    clean_os_env["BUBBLE_SANDBOX_LOG_LEVEL"] = "WARNING"

    s = settings.Settings()

    assert s.environments_path == pathlib.Path("/some/path")
    assert s.workspace_path == pathlib.Path("/other/path")
    assert s.max_upload_size_bytes == 5000
    assert s.allowed_extensions == [".py", ".txt"]
    assert s.execution_timeout_seconds == 60
    assert s.session_idle_timeout_seconds == 7200
    assert s.max_output_chars == 500
    assert s.max_session_count == 100
    assert s.log_level == "WARNING"


def test_get_settings_caching(clean_os_env):
    settings.get_settings.cache_clear()

    s1 = settings.get_settings()
    s2 = settings.get_settings()

    assert s1 is s2

    settings.get_settings.cache_clear()
