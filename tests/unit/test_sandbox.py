import asyncio
import contextlib
import pathlib
from unittest import mock

import pytest

from bubble_sandbox import models as bs_models
from bubble_sandbox import sandbox as bs_sandbox

ENVIRONMENT_NAME = "test_environment"
OTHER_ENVIRONMENT_NAME = "other_test_environment"
WORKDIR_NAME = "test_workdir"
HOST_VOLUME_PATH = pathlib.Path("/path/to/host/volume")
VOLUME_RO = bs_models.VolumeInfo(
    host_path=HOST_VOLUME_PATH,
    writable=False,
)
VOLUME_RW = bs_models.VolumeInfo(
    host_path=HOST_VOLUME_PATH,
    writable=True,
)

OTHER_HOST_VOLUME_PATH = pathlib.Path("/path/to/host/other_volume")
OTHER_VOLUME_RO = bs_models.VolumeInfo(
    host_path=OTHER_HOST_VOLUME_PATH,
    writable=False,
)


@pytest.mark.parametrize(
    "name",
    ["../etc", "foo/bar", "foo\\bar", ".."],
)
def test_resolve_venv_path_w_path_traversal_rejected(sandbox_config, name):
    with pytest.raises(bs_sandbox.InvalidEnvironmenName):
        bs_sandbox.resolve_venv_path(name, sandbox_config)


def test_resolve_venv_path_w_missing_env_dir(sandbox_config):
    with pytest.raises(bs_sandbox.EnvironmentNotFound):
        bs_sandbox.resolve_venv_path("nonexistent", sandbox_config)


def test_resolve_venv_path_w_missing_venv(sandbox_config):
    environment_path = sandbox_config.environments_path / "no-venv"
    environment_path.mkdir()

    with pytest.raises(bs_sandbox.EnvironmentNotInitialized):
        bs_sandbox.resolve_venv_path("no-venv", sandbox_config)


def test_resolve_venv_path_w_valid_env(sandbox_config, bare_environment):
    expected = bare_environment / ".venv"

    found = bs_sandbox.resolve_venv_path("bare", sandbox_config)

    assert found == expected


def _extract_multis(cmd):
    binds = {}
    for i_token, token in enumerate(cmd):
        if token in ("--bind", "--ro-bind", "--symlink", "--setenv"):
            source, target = cmd[i_token + 1], cmd[i_token + 2]
            binds.setdefault(token, []).append((source, target))

        elif token in ["--proc", "--dev", "--tmpfs", "--chdir"]:
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
def test_venv_sandbox_args(rvp, sandbox_config):
    venv_path = sandbox_config.environments_path / ENVIRONMENT_NAME
    rvp.return_value = venv_path

    found = bs_sandbox.venv_sandbox_args(ENVIRONMENT_NAME, sandbox_config)

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

    # Check read-write binds
    rw_binds = multis["--bind"]
    assert (str(workdir_path), "/sandbox/work") in rw_binds

    chdir = multis["--chdir"]
    assert chdir == ["/sandbox/work"]


@pytest.mark.parametrize(
    "volume_map, expected",
    [
        ({}, []),
        (
            {"readonly": VOLUME_RO},
            [
                "--ro-bind",
                str(HOST_VOLUME_PATH),
                "/sandbox/volumes/readonly",
            ],
        ),
        (
            {"readwrite": VOLUME_RW},
            [
                "--bind",
                str(HOST_VOLUME_PATH),
                "/sandbox/volumes/readwrite",
            ],
        ),
    ],
)
def test_volumes_sandbox_args(volume_map, expected):
    found = bs_sandbox.volumes_sandbox_args(volume_map)

    assert found == expected


@pytest.mark.parametrize(
    "xtra_vols_kwargs",
    [
        {},
        {"extra_volumes": {"other": OTHER_VOLUME_RO}},
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
    sandbox_config,
    env_kwargs,
    exp_env_name,
    xtra_vols_kwargs,
):
    csa.return_value = ["CORE"]
    venvsa.return_value = ["VENV"]
    wdsa.return_value = ["WORKDIR"]
    volsa.return_value = ["VOLUMES"]

    volumes = {"readonly": VOLUME_RO}
    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name=ENVIRONMENT_NAME,
        config=sandbox_config,
        volumes=volumes,
    )

    workdir_path = tmp_path / "workdir"
    command = ["ls", "-laF"]
    expected = ["CORE", "VENV", "WORKDIR", "VOLUMES"] + command
    exp_xtra_vols = xtra_vols_kwargs.get("extra_volumes", {})

    found = sandbox.build_bwrap_command(
        workdir_path=workdir_path,
        command=command,
        **env_kwargs,
        **xtra_vols_kwargs,
    )

    assert found == expected

    csa.assert_called_once_with()
    venvsa.assert_called_once_with(exp_env_name, sandbox_config)
    wdsa.assert_called_once_with(workdir_path)
    volsa.assert_called_once_with(volumes | exp_xtra_vols)


@pytest.mark.asyncio
@pytest.mark.parametrize("w_workdir", [False, True])
@mock.patch("tempfile.TemporaryDirectory")
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_script_w_success(
    cs_exec,
    tftd,
    tmp_path,
    sandbox_config,
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
        config=sandbox_config,
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
    sandbox_config,
    bare_environment,
):
    MUST_TRUNCATE = b"X" * 100

    sandbox_config.max_output_chars = 50
    proc = cs_exec.return_value
    proc.communicate.return_value = (MUST_TRUNCATE, b"")
    proc.returncode = 0

    script = f"print('{MUST_TRUNCATE}')"

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        config=sandbox_config,
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
    sandbox_config,
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
        config=sandbox_config,
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
    sandbox_config,
    bare_environment,
):
    proc = cs_exec.return_value
    # work around mock quirk: 'asyncio.subprocess.Process.kill' is not async
    proc.kill = mock.Mock(spec_set=())
    proc.communicate.return_value = (b"times out", b"")
    proc.returncode = -99

    wait_for.side_effect = TimeoutError

    timeout_seconds = 0.02

    script = "import time; time.sleep(100)"

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_script(
        script=script,
        workdir=workdir,
        timeout=timeout_seconds,
    )

    assert isinstance(found, bs_models.ExecuteResult)
    assert "timed out" in found.output
    assert found.exit_code == -1

    proc.kill.assert_called_once_with()
    proc.wait.assert_awaited_once_with()

    ((args, kwargs),) = wait_for.call_args_list
    assert kwargs == {"timeout": 0.02}

    # 'wait_for' raises without awaiting calling the 'proc.communicate' coro
    cs_exec.return_value.communicate.assert_not_awaited()
    await args[0]  # avoid tracemalloc warning


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_w_success(
    cs_exec,
    tmp_path,
    sandbox_config,
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
        config=sandbox_config,
    )

    found = await sandbox.execute(command=command, workdir=workdir)

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
async def test_bwrapsandboxcommand_execute_wo_workdir(
    cs_exec,
    tmp_path,
    sandbox_config,
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
        config=sandbox_config,
    )

    found = await sandbox.execute(command=command)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output == "hello\n"
    assert found.exit_code == 0
    assert not found.truncated


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_w_truncation(
    cs_exec,
    tmp_path,
    sandbox_config,
    bare_environment,
):
    MUST_TRUNCATE = b"X" * 100

    sandbox_config.max_output_chars = 50
    proc = cs_exec.return_value
    proc.communicate.return_value = (MUST_TRUNCATE, b"")
    proc.returncode = 0

    script = f"print('{MUST_TRUNCATE}')"
    command = ["python", "-c", script]

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(command=command, workdir=workdir)
    exp_output = MUST_TRUNCATE[:50].decode("ascii")

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output == exp_output
    assert found.exit_code == 0
    assert found.truncated


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_w_error(
    cs_exec,
    tmp_path,
    sandbox_config,
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
        config=sandbox_config,
    )

    found = await sandbox.execute(command=command, workdir=workdir)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output == "error"
    assert found.exit_code == 1


@pytest.mark.asyncio
@mock.patch("asyncio.wait_for")
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_w_timeout(
    cs_exec,
    wait_for,
    tmp_path,
    sandbox_config,
    bare_environment,
):
    proc = cs_exec.return_value
    # work around mock quirk: 'asyncio.subprocess.Process.kill' is not async
    proc.kill = mock.Mock(spec_set=())
    proc.communicate.return_value = (b"times out", b"")
    proc.returncode = -99

    wait_for.side_effect = TimeoutError

    timeout_seconds = 0.01

    script = "import time; time.sleep(100)"
    command = ["python", "-c", script]

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(
        command=command,
        workdir=workdir,
        timeout=timeout_seconds,
    )

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
