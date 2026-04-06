import asyncio
import contextlib
import pathlib
from unittest import mock

import pytest

from bubble_sandbox import models as bs_models
from bubble_sandbox import sandbox as bs_sandbox
from bubble_sandbox import settings as bs_settings

ENVIRONMENT_NAME = "test_environment"
OTHER_ENVIRONMENT_NAME = "other_test_environment"
WORKDIR_NAME = "test_workdir"
HOST_VOLUME_PATH = pathlib.Path("/path/to/host/volume")
SANDBOX_VOLUME_PATH = pathlib.Path("/sandbox/mounted/volume")
VOLUME_RO = bs_models.VolumeMount(
    host_path=HOST_VOLUME_PATH,
    sandbox_path=SANDBOX_VOLUME_PATH,
    writable=False,
)
VOLUME_RW = bs_models.VolumeMount(
    host_path=HOST_VOLUME_PATH,
    sandbox_path=SANDBOX_VOLUME_PATH,
    writable=True,
)

OTHER_HOST_VOLUME_PATH = pathlib.Path("/path/to/host/other_volume")
OTHER_SANDBOX_VOLUME_PATH = pathlib.Path("/sandbox/mounted/other_volume")
OTHER_VOLUME_RO = bs_models.VolumeMount(
    host_path=OTHER_HOST_VOLUME_PATH,
    sandbox_path=OTHER_SANDBOX_VOLUME_PATH,
    writable=False,
)


@pytest.mark.parametrize(
    "name",
    ["../etc", "foo/bar", "foo\\bar", ".."],
)
def test_resolve_venv_path_w_path_traversal_rejected(sandbox_settings, name):
    with pytest.raises(bs_sandbox.InvalidEnvironmenName):
        bs_sandbox.resolve_venv_path(name, sandbox_settings)


def test_resolve_venv_path_w_missing_env_dir(sandbox_settings):
    with pytest.raises(bs_sandbox.EnvironmentNotFound):
        bs_sandbox.resolve_venv_path("nonexistent", sandbox_settings)


def test_resolve_venv_path_w_missing_venv(sandbox_settings):
    environment_path = sandbox_settings.environments_path / "no-venv"
    environment_path.mkdir()

    with pytest.raises(bs_sandbox.EnvironmentNotInitialized):
        bs_sandbox.resolve_venv_path("no-venv", sandbox_settings)


def test_resolve_venv_path_w_valid_env(sandbox_settings, bare_environment):
    expected = bare_environment / ".venv"

    found = bs_sandbox.resolve_venv_path("bare", sandbox_settings)

    assert found == expected


def test_validate_uploads_w_invalid_extension(sandbox_settings):
    files = {"script.py": b"import os"}

    with pytest.raises(bs_sandbox.ExtensionNotAllowed):
        bs_sandbox.validate_uploads(files, sandbox_settings)


def test_validate_uploads_w_oversized_upload(sandbox_settings):
    sandbox_settings.max_upload_size_bytes = 10
    files = {"big.csv": b"x" * 20}

    with pytest.raises(bs_sandbox.MaxUploadSizeExceded):
        bs_sandbox.validate_uploads(files, sandbox_settings)


def test_validate_uploads_w_valid_uploads(sandbox_settings):
    files = {
        "data.csv": b"a,b,c",
        "notes.txt": b"hello",
    }
    bs_sandbox.validate_uploads(files, sandbox_settings)  # no raise


def test_validate_uploads_w_empty_files(sandbox_settings):
    bs_sandbox.validate_uploads({}, sandbox_settings)  # no raise


def test_validate_uploads_w_extension_case_insensitive(sandbox_settings):
    files = {"DATA.CSV": b"a,b"}
    bs_sandbox.validate_uploads(files, sandbox_settings)  # no raise


def _extract_multis(cmd):
    binds = {}
    for i_token, token in enumerate(cmd):
        if token in ("--bind", "--ro-bind", "--symlink", "--setenv"):
            source, target = cmd[i_token + 1], cmd[i_token + 2]
            binds.setdefault(token, []).append((source, target))

        elif token in ["--proc", "--dev", "--tmpfs"]:
            target = cmd[i_token + 1]
            binds.setdefault(token, []).append(target)

    return binds


@pytest.mark.parametrize(
    "w_sys_base_prefix, exp_ro_bind",
    [
        ("/usr", None),
        ("/opt/Python-x.y.z", ("/opt/Python-x.y.z", "/opt/Python-x.y.z")),
        ("/usr/local", ("/usr/local", "/usr/local")),
    ],
)
@pytest.mark.parametrize(
    "network_kwargs, has_unshare_net",
    [
        ({}, True),
        ({"network": False}, True),
        ({"network": True}, False),
    ],
)
@pytest.mark.parametrize("w_lib64", [False, True])
def test_core_sandbox_args(
    monkeypatch,
    w_lib64,
    network_kwargs,
    has_unshare_net,
    w_sys_base_prefix,
    exp_ro_bind,
):
    unbound = pathlib.Path.exists

    def _lib64_exists(self):
        if str(self) == "/lib64":
            return w_lib64
        else:  # pragma: NO COVER
            return unbound(self)

    monkeypatch.setattr(pathlib.Path, "exists", _lib64_exists)
    monkeypatch.setattr(bs_sandbox, "_SYS_BASE_PREFIX", w_sys_base_prefix)

    found = bs_sandbox.core_sandbox_args(**network_kwargs)

    executable, *rest = found

    assert executable == "bwrap"

    multis = _extract_multis(rest)

    # Check special filesystem binds
    assert multis["--proc"] == ["/proc"]
    assert multis["--dev"] == ["/dev"]
    assert multis["--tmpfs"] == ["/tmp"]

    # Check read-only binds
    ro_binds = multis["--ro-bind"]
    assert ("/usr", "/usr") in ro_binds
    assert ("/lib", "/lib") in ro_binds

    if w_lib64:
        assert ("/lib64", "/lib64") in ro_binds
    else:
        assert ("/lib64", "/lib64") not in ro_binds

    if exp_ro_bind is not None:
        assert exp_ro_bind in ro_binds

    # Check symlinks
    symlinks = multis["--symlink"]
    assert ("usr/bin", "/bin") in symlinks
    assert ("usr/sbin", "/sbin") in symlinks

    # Check flags
    assert "--unshare-user" in rest
    assert "--unshare-pid" in rest
    assert "--new-session" in rest
    assert "--die-with-parent" in rest

    if has_unshare_net:
        assert "--unshare-net" in rest
    else:
        assert "--unshare-net" not in rest


@mock.patch("bubble_sandbox.sandbox.resolve_venv_path")
def test_venv_sandbox_args(rvp, sandbox_settings):
    venv_path = sandbox_settings.environments_path / ENVIRONMENT_NAME
    rvp.return_value = venv_path

    found = bs_sandbox.venv_sandbox_args(ENVIRONMENT_NAME, sandbox_settings)

    multis = _extract_multis(found)

    # Check read-only binds
    ro_binds = multis["--ro-bind"]
    assert (str(venv_path), "/sandbox/venv") in ro_binds

    # Check that venv bindir is at head of PATH
    set_envs = multis["--setenv"]
    ((name, value),) = set_envs  # only one
    assert name == "PATH"
    assert value.startswith("/sandbox/venv/bin")


def test_workdir_sandbox_args_w_None():
    found = bs_sandbox.workdir_sandbox_args(None)

    assert found == []


def test_workdir_sandbox_args_w_path(tmp_path: pathlib.Path):
    workdir_path = tmp_path / WORKDIR_NAME

    found = bs_sandbox.workdir_sandbox_args(workdir_path)

    multis = _extract_multis(found)

    # Check read-only binds
    ro_binds = multis["--bind"]
    assert (str(workdir_path), "/sandbox/work") in ro_binds


@pytest.mark.parametrize(
    "volumes, expected",
    [
        ([], []),
        (
            [VOLUME_RO],
            [
                "--ro-bind",
                str(HOST_VOLUME_PATH),
                str(SANDBOX_VOLUME_PATH),
            ],
        ),
        (
            [VOLUME_RW],
            [
                "--bind",
                str(HOST_VOLUME_PATH),
                str(SANDBOX_VOLUME_PATH),
            ],
        ),
    ],
)
def test_volumes_sandbox_args(volumes, expected):
    found = bs_sandbox.volumes_sandbox_args(volumes)

    assert found == expected


@pytest.mark.parametrize(
    "xtra_vols_kwargs, exp_xtra_vols",
    [
        ({}, []),
        (
            {"extra_volumes": [OTHER_VOLUME_RO]},
            [OTHER_VOLUME_RO],
        ),
    ],
)
@pytest.mark.parametrize(
    "env_kwargs, exp_env_name",
    [
        ({}, ENVIRONMENT_NAME),
        (
            {"environment_name": OTHER_ENVIRONMENT_NAME},
            OTHER_ENVIRONMENT_NAME,
        ),
    ],
)
@mock.patch("bubble_sandbox.sandbox.volumes_sandbox_args")
@mock.patch("bubble_sandbox.sandbox.workdir_sandbox_args")
@mock.patch("bubble_sandbox.sandbox.venv_sandbox_args")
@mock.patch("bubble_sandbox.sandbox.core_sandbox_args")
def test_bwrapsandboxcommand_build_bwrap_command(
    csa,
    venvsa,
    wdsa,
    volsa,
    tmp_path,
    sandbox_settings,
    env_kwargs,
    exp_env_name,
    xtra_vols_kwargs,
    exp_xtra_vols,
):
    csa.return_value = ["CORE"]
    venvsa.return_value = ["VENV"]
    wdsa.return_value = ["WORKDIR"]
    volsa.return_value = ["VOLUMES"]

    volumes = [VOLUME_RO]
    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name=ENVIRONMENT_NAME,
        settings=sandbox_settings,
        volumes=volumes,
    )

    workdir_path = tmp_path / "workdir"
    command = ["ls", "-laF"]
    expected = ["CORE", "VENV", "WORKDIR", "VOLUMES"] + command

    found = sandbox.build_bwrap_command(
        workdir_path=workdir_path,
        command=command,
        **env_kwargs,
        **xtra_vols_kwargs,
    )

    assert found == expected

    csa.assert_called_once_with()
    venvsa.assert_called_once_with(exp_env_name, sandbox_settings)
    wdsa.assert_called_once_with(workdir_path)
    volsa.assert_called_once_with(volumes + exp_xtra_vols)


@pytest.mark.asyncio
@pytest.mark.parametrize("w_workdir", [False, True])
@mock.patch("tempfile.TemporaryDirectory")
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_script_w_success(
    cs_exec,
    tftd,
    tmp_path,
    sandbox_settings,
    bare_environment,
    w_workdir,
):
    proc = cs_exec.return_value
    proc.communicate.return_value = (b"hello\n", b"")
    proc.returncode = 0

    script = "print('hello')"

    kwargs = {}

    if w_workdir:
        workdir = kwargs["workdir"] = tmp_path / "work"
        workdir.mkdir()
    else:
        temp_dir = tmp_path / "temp_dir"
        temp_dir.mkdir()
        tftd.return_value = contextlib.nullcontext(temp_dir)

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute_script(script=script, **kwargs)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output == "hello\n"
    assert found.exit_code == 0
    assert not found.truncated


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_script_w_truncation(
    cs_exec,
    tmp_path,
    sandbox_settings,
    bare_environment,
):
    MUST_TRUNCATE = b"X" * 100

    sandbox_settings.max_output_chars = 50
    proc = cs_exec.return_value
    proc.communicate.return_value = (MUST_TRUNCATE, b"")
    proc.returncode = 0

    script = f"print('{MUST_TRUNCATE}')"

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute_script(script=script, workdir=workdir)
    exp_output = MUST_TRUNCATE[:50].decode("ascii")

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output == exp_output
    assert found.exit_code == 0
    assert found.truncated

    ((args, kwargs),) = cs_exec.call_args_list
    assert args[-2:] == (
        "/sandbox/venv/bin/python",
        "/sandbox/work/script.py",
    )
    assert kwargs == {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_script_w_error(
    cs_exec,
    tmp_path,
    sandbox_settings,
    bare_environment,
):
    proc = cs_exec.return_value
    proc.communicate.return_value = (b"", b"error")
    proc.returncode = 1

    script = "bad"

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute_script(script=script, workdir=workdir)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output == "error"
    assert found.exit_code == 1


@pytest.mark.asyncio
@mock.patch("asyncio.wait_for")
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_script_w_timeout(
    cs_exec,
    wait_for,
    tmp_path,
    sandbox_settings,
    bare_environment,
):
    proc = cs_exec.return_value
    # work around mock quirk: 'asyncio.subprocess.Process.kill' is not async
    proc.kill = mock.Mock(spec_set=())
    proc.communicate.return_value = (b"times out", b"")
    proc.returncode = -99

    wait_for.side_effect = TimeoutError

    sandbox_settings.execution_timeout_seconds = 0.01

    script = "import time; time.sleep(100)"

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute_script(script=script, workdir=workdir)

    assert isinstance(found, bs_models.ExecuteResult)
    assert "timed out" in found.output
    assert found.exit_code == -1

    proc.kill.assert_called_once_with()
    proc.wait.assert_awaited_once_with()

    ((args, kwargs),) = wait_for.call_args_list
    assert kwargs == {"timeout": 0.01}

    # 'wait_for' raises without awaiting calling the 'proc.communicate' coro
    cs_exec.return_value.communicate.assert_not_awaited()
    await args[0]  # avoid tracemalloc warning


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_command_w_success(
    cs_exec,
    tmp_path,
    sandbox_settings,
    bare_environment,
):
    proc = cs_exec.return_value
    proc.communicate.return_value = (b".  ..\n", b"")
    proc.returncode = 0

    workdir = tmp_path / "work"
    workdir.mkdir()

    command = ["ls", "-a", "/sandbox/work"]

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute_command(command=command, workdir=workdir)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output == ".  ..\n"
    assert found.exit_code == 0
    assert not found.truncated

    ((args, kwargs),) = cs_exec.call_args_list
    assert args[-3:] == (
        "ls",
        "-a",
        "/sandbox/work",
    )
    assert kwargs == {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_command_wo_workdir(
    cs_exec,
    tmp_path,
    sandbox_settings,
    bare_environment,
):
    proc = cs_exec.return_value
    proc.communicate.return_value = (b"hello\n", b"")
    proc.returncode = 0

    workdir = tmp_path / "work"
    workdir.mkdir()

    command = ["python", "-c", "print('hello')"]

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute_command(command=command)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output == "hello\n"
    assert found.exit_code == 0
    assert not found.truncated


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_command_w_truncation(
    cs_exec,
    tmp_path,
    sandbox_settings,
    bare_environment,
):
    MUST_TRUNCATE = b"X" * 100

    sandbox_settings.max_output_chars = 50
    proc = cs_exec.return_value
    proc.communicate.return_value = (MUST_TRUNCATE, b"")
    proc.returncode = 0

    script = f"print('{MUST_TRUNCATE}')"
    command = ["python", "-c", script]

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute_command(command=command, workdir=workdir)
    exp_output = MUST_TRUNCATE[:50].decode("ascii")

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output == exp_output
    assert found.exit_code == 0
    assert found.truncated


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_command_w_error(
    cs_exec,
    tmp_path,
    sandbox_settings,
    bare_environment,
):
    proc = cs_exec.return_value
    proc.communicate.return_value = (b"", b"error")
    proc.returncode = 1

    script = "import sys; sys.exit(1)"
    command = ["python", "-c", script]

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute_command(command=command, workdir=workdir)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output == "error"
    assert found.exit_code == 1


@pytest.mark.asyncio
@mock.patch("asyncio.wait_for")
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_command_w_timeout(
    cs_exec,
    wait_for,
    tmp_path,
    sandbox_settings,
    bare_environment,
):
    proc = cs_exec.return_value
    # work around mock quirk: 'asyncio.subprocess.Process.kill' is not async
    proc.kill = mock.Mock(spec_set=())
    proc.communicate.return_value = (b"times out", b"")
    proc.returncode = -99

    wait_for.side_effect = TimeoutError

    sandbox_settings.execution_timeout_seconds = 0.01

    script = "import time; time.sleep(100)"
    command = ["python", "-c", script]

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute_command(command=command, workdir=workdir)

    assert isinstance(found, bs_models.ExecuteResult)
    assert "timed out" in found.output
    assert found.exit_code == -1

    proc.kill.assert_called_once_with()
    proc.wait.assert_awaited_once_with()

    ((args, kwargs),) = wait_for.call_args_list
    assert kwargs == {"timeout": 0.01}

    # 'wait_for' raises without awaiting calling the 'proc.communicate' coro
    cs_exec.return_value.communicate.assert_not_awaited()
    await args[0]  # avoid tracemalloc warning


@pytest.mark.parametrize(
    "command",
    [
        ["true"],
        ["sh", "-c", "echo hello"],
    ],
)
def test__build_bwrap_command_w_command_structure(command):
    venv = pathlib.Path("/env/.venv")
    workdir = pathlib.Path("/tmp/exec-abc")
    cmd = bs_sandbox._build_bwrap_command(venv, workdir, command)

    assert cmd[0] == "bwrap"

    multis = _extract_multis(cmd)

    # Check special filesystem binds
    assert multis["--proc"] == ["/proc"]
    assert multis["--dev"] == ["/dev"]
    assert multis["--tmpfs"] == ["/tmp"]

    # Check read-only binds
    ro_binds = multis["--ro-bind"]
    assert ("/usr", "/usr") in ro_binds
    assert ("/lib", "/lib") in ro_binds
    assert (str(venv), "/sandbox/venv") in ro_binds

    # Check read-only binds
    rw_binds = multis["--bind"]
    assert (str(workdir), "/sandbox/work") in rw_binds

    # Check symlinks
    symlinks = multis["--symlink"]
    assert ("usr/bin", "/bin") in symlinks
    assert ("usr/sbin", "/sbin") in symlinks

    assert "--unshare-user" in cmd
    assert "--unshare-pid" in cmd
    assert "--new-session" in cmd
    assert "--die-with-parent" in cmd

    assert "--unshare-net" in cmd  # net disabled by default

    set_envs = multis["--setenv"]
    ((name, value),) = set_envs  # only one
    assert name == "PATH"
    assert value.startswith("/sandbox/venv/bin")

    assert cmd[-len(command) :] == command


def test__build_bwrap_command_w_network_enabled():
    venv = pathlib.Path("/env/.venv")
    workdir = pathlib.Path("/tmp/exec-abc")
    cmd = bs_sandbox._build_bwrap_command(
        venv,
        workdir,
        ["true"],
        network=True,
    )
    assert "--unshare-net" not in cmd


def test__build_bwrap_command_w_lib64_exists(monkeypatch):
    venv = pathlib.Path("/env/.venv")
    workdir = pathlib.Path("/tmp/exec-abc")
    unbound = pathlib.Path.exists

    def _lib64_exists(self):
        if str(self) == "/lib64":
            return True
        else:  # pragma: NO COVER
            return unbound(self)

    monkeypatch.setattr(pathlib.Path, "exists", _lib64_exists)

    cmd = bs_sandbox._build_bwrap_command(venv, workdir, ["true"])

    multis = _extract_multis(cmd)
    ro_binds = multis["--ro-bind"]
    assert ("/lib64", "/lib64") in ro_binds


def test__build_bwrap_command_w_lib64_excluded_when_missing(monkeypatch):
    venv = pathlib.Path("/env/.venv")
    workdir = pathlib.Path("/tmp/exec-abc")
    unbound = pathlib.Path.exists

    def _lib64_does_not_exist(self):
        if str(self) == "/lib64":
            return False
        else:  # pragma: NO COVER
            return unbound(self)

    monkeypatch.setattr(pathlib.Path, "exists", _lib64_does_not_exist)

    cmd = bs_sandbox._build_bwrap_command(venv, workdir, ["true"])

    multis = _extract_multis(cmd)
    ro_binds = multis["--ro-bind"]
    assert ("/lib64", "/lib64") not in ro_binds


def _create_env(envs_dir: pathlib.Path, name: str):
    env_dir = envs_dir / name
    env_dir.mkdir()
    venv_python = env_dir / ".venv" / bs_sandbox._VENV_PYTHON
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("fake")
    return env_dir


def _mock_process(stdout=b"", stderr=b"", returncode=0):
    proc = mock.create_autospec(asyncio.subprocess.Process)
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode

    return proc


async def test_execute_in_sandbox_w_env_not_found(sandbox_settings):
    with pytest.raises(bs_sandbox.EnvironmentNotFound):
        await bs_sandbox.execute_in_sandbox(
            script="ok",
            env_name="nope",
            files={},
            settings=sandbox_settings,
        )


async def test_execute_in_sandbox_w_success(sandbox_settings):
    _create_env(sandbox_settings.environments_path, "bare")
    proc = _mock_process(stdout=b"hello\n", returncode=0)

    with mock.patch(
        "bubble_sandbox.sandbox.asyncio.create_subprocess_exec",
        return_value=proc,
    ):
        result = await bs_sandbox.execute_in_sandbox(
            script='print("hello")',
            env_name="bare",
            files={},
            settings=sandbox_settings,
        )

    assert isinstance(result, bs_models.ScriptResult)
    assert result.stdout == "hello\n"
    assert result.stderr == ""
    assert result.return_code == 0


async def test_execute_in_sandbox_w_with_files(sandbox_settings):
    _create_env(sandbox_settings.environments_path, "bare")
    proc = _mock_process(stdout=b"ok")

    with mock.patch(
        "bubble_sandbox.sandbox.asyncio.create_subprocess_exec",
        return_value=proc,
    ):
        result = await bs_sandbox.execute_in_sandbox(
            script="print('ok')",
            env_name="bare",
            files={"data.csv": b"a,b,c"},
            settings=sandbox_settings,
        )

    assert result.stdout == "ok"


async def test_execute_in_sandbox_w_nonzero_exit(sandbox_settings):
    _create_env(sandbox_settings.environments_path, "bare")
    proc = _mock_process(stderr=b"error", returncode=1)

    with mock.patch(
        "bubble_sandbox.sandbox.asyncio.create_subprocess_exec",
        return_value=proc,
    ):
        result = await bs_sandbox.execute_in_sandbox(
            script="bad",
            env_name="bare",
            files={},
            settings=sandbox_settings,
        )

    assert result.return_code == 1
    assert result.stderr == "error"


async def test_execute_in_sandbox_w_timeout(sandbox_settings):
    sandbox_settings.execution_timeout_seconds = 0.01
    _create_env(sandbox_settings.environments_path, "bare")

    proc = _mock_process(stdout=b"times out")

    with (
        mock.patch(
            "bubble_sandbox.sandbox.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
        mock.patch(
            "bubble_sandbox.sandbox.asyncio.wait_for",
            side_effect=TimeoutError,
        ) as mock_wait_for,
    ):
        result = await bs_sandbox.execute_in_sandbox(
            script="import time; time.sleep(100)",
            env_name="bare",
            files={},
            settings=sandbox_settings,
        )

    assert result.return_code == -1
    assert "timed out" in result.stderr
    assert result.stdout == ""

    proc.kill.assert_called_once_with()
    proc.wait.assert_awaited_once_with()

    ((args, kwargs),) = mock_wait_for.call_args_list
    assert kwargs == {"timeout": 0.01}

    # 'wait_for' raises without awaiting calling the 'proc.communicate' coro
    proc.communicate.assert_not_awaited()
    await args[0]  # avoid tracemalloc warning


async def test_execute_in_sandbox_w_file_path_sanitized(sandbox_settings):
    _create_env(sandbox_settings.environments_path, "bare")
    proc = _mock_process(stdout=b"ok")

    created_files: list[str] = []
    original_write = pathlib.Path.write_bytes

    def tracking_write(self, data):
        created_files.append(self.name)
        return original_write(self, data)

    with (
        mock.patch(
            "bubble_sandbox.sandbox.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
        mock.patch.object(
            pathlib.Path,
            "write_bytes",
            tracking_write,
        ),
    ):
        await bs_sandbox.execute_in_sandbox(
            script="ok",
            env_name="bare",
            files={"../../etc/passwd.csv": b"sneaky"},
            settings=sandbox_settings,
        )

    assert "passwd.csv" in created_files
    assert "../../etc/passwd.csv" not in created_files


async def test_execute_command_in_sandbox_w_success(sandbox_settings):
    _create_env(sandbox_settings.environments_path, "bare")
    venv = bs_sandbox.resolve_venv_path("bare", sandbox_settings)
    workdir = sandbox_settings.environments_path / "bare"

    proc = _mock_process(stdout=b"hello\n", returncode=0)

    with mock.patch(
        "bubble_sandbox.sandbox.asyncio.create_subprocess_exec",
        return_value=proc,
    ):
        result = await bs_sandbox.execute_command_in_sandbox(
            command="echo hello",
            venv_path=venv,
            workdir=workdir,
        )

    assert isinstance(result, bs_models.ExecuteResult)
    assert result.output == "hello\n"
    assert result.exit_code == 0
    assert result.truncated is False


async def test_execute_command_in_sandbox_w_stderr_appended(sandbox_settings):
    _create_env(sandbox_settings.environments_path, "bare")
    venv = bs_sandbox.resolve_venv_path("bare", sandbox_settings)
    workdir = sandbox_settings.environments_path / "bare"

    proc = _mock_process(stdout=b"out", stderr=b"err", returncode=0)

    with mock.patch(
        "bubble_sandbox.sandbox.asyncio.create_subprocess_exec",
        return_value=proc,
    ):
        result = await bs_sandbox.execute_command_in_sandbox(
            command="cmd",
            venv_path=venv,
            workdir=workdir,
        )

    assert result.output == "outerr"


async def test_execute_command_in_sandbox_w_timeout(sandbox_settings):
    _create_env(sandbox_settings.environments_path, "bare")
    venv = bs_sandbox.resolve_venv_path("bare", sandbox_settings)
    workdir = sandbox_settings.environments_path / "bare"

    proc = _mock_process(stdout=b"times out")

    with (
        mock.patch(
            "bubble_sandbox.sandbox.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
        mock.patch(
            "bubble_sandbox.sandbox.asyncio.wait_for",
            side_effect=TimeoutError,
        ) as mock_wait_for,
    ):
        result = await bs_sandbox.execute_command_in_sandbox(
            command="sleep 100",
            venv_path=venv,
            workdir=workdir,
            timeout=1,
        )

    assert result.exit_code == -1
    assert "timed out" in result.output

    proc.kill.assert_called_once_with()
    proc.wait.assert_awaited_once_with()

    ((args, kwargs),) = mock_wait_for.call_args_list
    assert kwargs == {"timeout": 1}

    # 'wait_for' raises without awaiting calling the 'proc.communicate' coro
    proc.communicate.assert_not_awaited()
    await args[0]  # avoid tracemalloc warning


async def test_execute_command_in_sandbox_w_truncation(sandbox_settings):
    _create_env(sandbox_settings.environments_path, "bare")
    venv = bs_sandbox.resolve_venv_path("bare", sandbox_settings)
    workdir = sandbox_settings.environments_path / "bare"

    big_output = b"x" * 200_000
    proc = _mock_process(stdout=big_output, returncode=0)
    with mock.patch(
        "bubble_sandbox.sandbox.asyncio.create_subprocess_exec",
        return_value=proc,
    ):
        result = await bs_sandbox.execute_command_in_sandbox(
            command="cat bigfile",
            venv_path=venv,
            workdir=workdir,
        )

    assert result.truncated is True
    assert len(result.output) == 100_000


async def test_execute_command_in_sandbox_w_default_timeout(sandbox_settings):
    _create_env(sandbox_settings.environments_path, "bare")
    venv = bs_sandbox.resolve_venv_path("bare", sandbox_settings)
    workdir = sandbox_settings.environments_path / "bare"

    proc = _mock_process(stdout=b"times out", returncode=0)

    with (
        mock.patch(
            "bubble_sandbox.sandbox.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
        mock.patch(
            "bubble_sandbox.sandbox.asyncio.wait_for",
            return_value=(b"ok", b""),
        ) as mock_wait_for,
    ):
        result = await bs_sandbox.execute_command_in_sandbox(
            command="echo ok",
            venv_path=venv,
            workdir=workdir,
        )

    assert result.exit_code == 0
    assert "ok" in result.output

    proc.kill.assert_not_called()
    proc.wait.assert_not_awaited()

    ((args, kwargs),) = mock_wait_for.call_args_list
    assert kwargs == {
        "timeout": bs_settings.DEFAULT_EXECUTION_TIMEOUT_SECS,
    }

    proc.communicate.assert_not_awaited()
    await args[0]  # avoid tracemalloc warning
