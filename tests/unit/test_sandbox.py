import asyncio
import contextlib
import os
import pathlib
import signal
import stat
import subprocess
import sys
import time
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
EMPTY_RO = bs_models.VolumeInfo(
    host_path=None,
    writable=False,
)
EMPTY_RW = bs_models.VolumeInfo(
    host_path=None,
    writable=True,
)

OTHER_HOST_VOLUME_PATH = pathlib.Path("/path/to/host/other_volume")
OTHER_VOLUME_RO = bs_models.VolumeInfo(
    host_path=OTHER_HOST_VOLUME_PATH,
    writable=False,
)


_CORE_SIMPLE_PATHS = (
    "/lib64",
    "/etc/alternatives",
    "/etc/fonts",
    "/etc/papersize",
    "/etc/paperspecs",
)

ONE_ARG_MULTIS = {
    "--proc",
    "--dev",
    "--tmpfs",
    "--chdir",
    "--perms",
    "--dir",
}
TWO_ARG_MULTIS = {"--bind", "--ro-bind", "--symlink", "--setenv"}


def _extract_multis(cmd):
    binds = {}
    for i_token, token in enumerate(cmd):
        if token in TWO_ARG_MULTIS:
            source, target = cmd[i_token + 1], cmd[i_token + 2]
            binds.setdefault(token, []).append((source, target))

        elif token in ONE_ARG_MULTIS:
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
@pytest.mark.parametrize(
    "extant_dirs",
    [
        (),
        ("/lib64",),
        ("/etc/alternatives",),
        ("/etc/fonts",),
        ("/etc/papersize",),
        ("/etc/paperspecs",),
        _CORE_SIMPLE_PATHS,
    ],
)
def test_core_sandbox_args(
    monkeypatch,
    extant_dirs,
    network_kwargs,
    has_unshare_net,
    w_sys_base_prefix,
    exp_ro_bind,
):
    unbound = pathlib.Path.exists

    def _fake_exists(self):
        for known_path in _CORE_SIMPLE_PATHS:
            if self == pathlib.Path(known_path):
                return known_path in extant_dirs

        return unbound(self)  # pragma: NO COVER

    monkeypatch.setattr(pathlib.Path, "exists", _fake_exists)
    monkeypatch.setattr(bs_sandbox, "openjdk_binds", lambda: [])
    monkeypatch.setattr(bs_sandbox, "_SYS_BASE_PREFIX", w_sys_base_prefix)

    found = bs_sandbox.core_sandbox_args(**network_kwargs)

    executable, *rest = found

    assert executable == "bwrap"

    multis = _extract_multis(rest)

    # Check special filesystem binds:
    assert multis["--proc"] == ["/proc"]
    assert multis["--dev"] == ["/dev"]
    assert multis["--tmpfs"] == ["/tmp"]

    # Check read-only binds:
    ro_binds = multis["--ro-bind"]
    assert ("/usr", "/usr") in ro_binds
    assert ("/lib", "/lib") in ro_binds

    # Check binds of elements w/ permissions:
    w_perms = {}
    check_perms = rest

    while "--perms" in check_perms:
        i_perm = check_perms.index("--perms")
        mask = check_perms[i_perm + 1]
        next_command = check_perms[i_perm + 2]

        if next_command == "--dir":
            target = check_perms[i_perm + 3]
            w_perms.setdefault("dirs", []).append((target, mask))
            check_perms = check_perms[i_perm + 4 :]
        else:  # pragma: NO COVER
            pass

    assert ("/var/empty", "0644") in w_perms["dirs"]

    # Only if host platform has it:
    for known_path in _CORE_SIMPLE_PATHS:
        if known_path in extant_dirs:
            assert (known_path, known_path) in ro_binds
        else:
            assert (known_path, known_path) not in ro_binds

    if exp_ro_bind is not None:
        assert exp_ro_bind in ro_binds

    # Check symlinks:
    symlinks = multis["--symlink"]
    assert ("usr/bin", "/bin") in symlinks
    assert ("usr/sbin", "/sbin") in symlinks

    # Check flags:
    assert "--unshare-user" in rest
    assert "--unshare-pid" in rest
    assert "--new-session" in rest
    assert "--die-with-parent" in rest

    if has_unshare_net:
        assert "--unshare-net" in rest
    else:
        assert "--unshare-net" not in rest


def test_core_sandbox_args_w_openjdk(monkeypatch):
    monkeypatch.setattr(
        bs_sandbox,
        "openjdk_binds",
        lambda: ["--ro-bind", "/etc/java-21-openjdk", "/etc/java-21-openjdk"],
    )

    found = bs_sandbox.core_sandbox_args()

    multis = _extract_multis(found)
    ro_binds = multis["--ro-bind"]
    assert ("/etc/java-21-openjdk", "/etc/java-21-openjdk") in ro_binds


_OPENJDK_SIMPLE_DIRS = (
    "/usr/lib/jvm",
    "/usr/share/java",
    "/etc/java",
)


@pytest.mark.parametrize(
    "glob_results, exp_glob_binds",
    [
        ([], []),
        (
            [("/etc/java-21-openjdk", True)],
            [("/etc/java-21-openjdk", "/etc/java-21-openjdk")],
        ),
        (
            [
                ("/etc/java-17-openjdk", True),
                ("/etc/java-21-openjdk", True),
                ("/etc/java-not-a-dir-openjdk", False),
            ],
            [
                ("/etc/java-17-openjdk", "/etc/java-17-openjdk"),
                ("/etc/java-21-openjdk", "/etc/java-21-openjdk"),
            ],
        ),
    ],
)
@pytest.mark.parametrize(
    "extant_dirs",
    [
        (),
        ("/usr/lib/jvm",),
        ("/usr/share/java",),
        ("/etc/java",),
        _OPENJDK_SIMPLE_DIRS,
    ],
)
def test_openjdk_binds(monkeypatch, extant_dirs, glob_results, exp_glob_binds):
    class _FakeJavaPath:
        def __init__(self, path_str, is_dir_value):
            self._path_str = path_str
            self._is_dir_value = is_dir_value

        def __str__(self):
            return self._path_str

        def __lt__(self, other):
            return str(self) < str(other)

        def is_dir(self):
            return self._is_dir_value

    unbound_exists = pathlib.Path.exists

    def _fake_glob(self, pattern):
        if self == pathlib.Path("/etc") and pattern == "java-*-openjdk":
            return iter(
                _FakeJavaPath(path, is_dir) for path, is_dir in glob_results
            )
        else:  # pragma: NO COVER
            raise AssertionError(self, pattern)

    def _fake_exists(self):
        for known_dir in _OPENJDK_SIMPLE_DIRS:
            if self == pathlib.Path(known_dir):
                return known_dir in extant_dirs

        return unbound_exists(self)  # pragma: NO COVER

    monkeypatch.setattr(pathlib.Path, "glob", _fake_glob)
    monkeypatch.setattr(pathlib.Path, "exists", _fake_exists)

    found = bs_sandbox.openjdk_binds()

    multis = _extract_multis(found)
    ro_binds = multis.get("--ro-bind", [])

    exp_binds = [
        (known_dir, known_dir)
        for known_dir in _OPENJDK_SIMPLE_DIRS
        if known_dir in extant_dirs
    ]
    exp_binds.extend(exp_glob_binds)

    assert ro_binds == exp_binds


@pytest.fixture
def fresh_probe(monkeypatch):
    """Run a test with an empty probe cache, as on a Linux host."""
    monkeypatch.setattr(bs_sandbox, "_SYS_PLATFORM", "linux")
    bs_sandbox._probe.cache_clear()

    yield

    bs_sandbox._probe.cache_clear()


def _completed(returncode, stderr=""):
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout="",
        stderr=stderr,
    )


@pytest.mark.parametrize("w_network", [False, True])
@mock.patch("shutil.which", return_value="/usr/bin/bwrap")
@mock.patch("subprocess.run")
def test_check_available_w_success(run, which, fresh_probe, w_network):
    run.return_value = _completed(0)

    found = bs_sandbox.check_available(network=w_network)

    assert found is None
    which.assert_called_once_with("bwrap")
    ((args, kwargs),) = run.call_args_list
    assert args == (
        bs_sandbox.core_sandbox_args(network=w_network) + ["/usr/bin/true"],
    )
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["timeout"] == bs_sandbox._PROBE_TIMEOUT_SECONDS


@mock.patch("shutil.which", return_value="/usr/bin/bwrap")
@mock.patch("subprocess.run")
def test_check_available_w_unsupported_platform(
    run,
    which,
    fresh_probe,
    monkeypatch,
):
    monkeypatch.setattr(bs_sandbox, "_SYS_PLATFORM", "darwin")

    with pytest.raises(bs_sandbox.UnsupportedPlatform) as exc_info:
        bs_sandbox.check_available()

    assert exc_info.value.detail == "darwin"
    which.assert_not_called()
    run.assert_not_called()


@mock.patch("shutil.which", return_value=None)
@mock.patch("subprocess.run")
def test_check_available_wo_bwrap(run, which, fresh_probe):
    with pytest.raises(bs_sandbox.BwrapNotFound) as exc_info:
        bs_sandbox.check_available()

    assert str(exc_info.value) == (
        "Sandbox unavailable: 'bwrap' not found on PATH"
    )
    run.assert_not_called()


@mock.patch("shutil.which", return_value="/usr/bin/bwrap")
@mock.patch("subprocess.run")
def test_check_available_w_probe_not_started(run, which, fresh_probe):
    run.side_effect = PermissionError(13, "Permission denied")

    with pytest.raises(bs_sandbox.ProbeNotStarted) as exc_info:
        bs_sandbox.check_available()

    assert exc_info.value.detail == "[Errno 13] Permission denied"


@mock.patch("shutil.which", return_value="/usr/bin/bwrap")
@mock.patch("subprocess.run")
def test_check_available_w_probe_timed_out(run, which, fresh_probe):
    run.side_effect = subprocess.TimeoutExpired(cmd="bwrap", timeout=5.0)

    with pytest.raises(bs_sandbox.ProbeTimedOut) as exc_info:
        bs_sandbox.check_available()

    assert exc_info.value.timeout_seconds == (
        bs_sandbox._PROBE_TIMEOUT_SECONDS
    )


@mock.patch("shutil.which", return_value="/usr/bin/bwrap")
@mock.patch("subprocess.run")
def test_check_available_w_probe_failed(run, which, fresh_probe):
    stderr = "bwrap: setting up uid map: Permission denied\n"
    run.return_value = _completed(1, stderr)

    with pytest.raises(bs_sandbox.ProbeFailed) as exc_info:
        bs_sandbox.check_available()

    assert exc_info.value.exit_code == 1
    assert exc_info.value.stderr == stderr
    assert str(exc_info.value) == (
        "Sandbox unavailable: probe failed: exit code 1: "
        "bwrap: setting up uid map: Permission denied"
    )


@pytest.mark.parametrize(
    "w_returncode, expectation",
    [
        (0, contextlib.nullcontext()),
        (1, pytest.raises(bs_sandbox.ProbeFailed)),
    ],
)
@mock.patch("shutil.which", return_value="/usr/bin/bwrap")
@mock.patch("subprocess.run")
def test_check_available_caches_probe(
    run,
    which,
    fresh_probe,
    w_returncode,
    expectation,
):
    run.return_value = _completed(w_returncode)
    with contextlib.suppress(bs_sandbox.SandboxUnavailable):
        bs_sandbox.check_available()

    with expectation:
        bs_sandbox.check_available()

    run.assert_called_once()


@mock.patch("shutil.which", return_value="/usr/bin/bwrap")
@mock.patch("subprocess.run")
def test_check_available_probes_each_network_setting(run, which, fresh_probe):
    run.return_value = _completed(0)
    bs_sandbox.check_available(network=False)

    bs_sandbox.check_available(network=True)

    assert run.call_count == 2


@mock.patch("shutil.which", return_value="/usr/bin/bwrap")
@mock.patch("subprocess.run")
def test_check_available_raises_fresh_exception(run, which, fresh_probe):
    run.return_value = _completed(1)
    with pytest.raises(bs_sandbox.ProbeFailed) as first:
        bs_sandbox.check_available()

    with pytest.raises(bs_sandbox.ProbeFailed) as second:
        bs_sandbox.check_available()

    assert second.value is not first.value


@pytest.mark.parametrize("w_returncode, expected", [(0, True), (1, False)])
@mock.patch("shutil.which", return_value="/usr/bin/bwrap")
@mock.patch("subprocess.run")
def test_is_available(run, which, fresh_probe, w_returncode, expected):
    run.return_value = _completed(w_returncode)

    found = bs_sandbox.is_available()

    assert found is expected


def test_venv_sandbox_args(sandbox_config, environments_path):
    venv_path = environments_path / ENVIRONMENT_NAME / ".venv"

    if sys.platform != "win32":  # pragma: NO COVER
        bin_path = venv_path / "bin"
        python_interpreter = bin_path / "python"
    else:  # pragma: NO COVER
        bin_path = venv_path / "Scripts"
        python_interpreter = bin_path / "python.exe"

    bin_path.mkdir(parents=True)
    python_interpreter.touch()

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
        (
            {"empty-readonly": EMPTY_RO},
            [
                "--perms",
                "0644",
                "--dir",
                "/sandbox/volumes/empty-readonly",
            ],
        ),
        (
            {"empty-readwrite": EMPTY_RW},
            [
                "--perms",
                "0755",
                "--dir",
                "/sandbox/volumes/empty-readwrite",
            ],
        ),
    ],
)
def test_volumes_sandbox_args(volume_map, expected):
    found = bs_sandbox.volumes_sandbox_args(volume_map)

    assert found == expected


@pytest.mark.parametrize(
    "w_script_name",
    ["script.py", "run-1.py", ".hidden.py"],
)
def test__validate_script_name_accepts(w_script_name):
    found = bs_sandbox._validate_script_name(w_script_name)

    assert found == w_script_name


@pytest.mark.parametrize(
    "w_script_name, expectation",
    [
        (" script.py", pytest.raises(bs_sandbox.LeadingTrailingWhitespace)),
        ("script.py\n", pytest.raises(bs_sandbox.LeadingTrailingWhitespace)),
        ("C:\\escape.py", pytest.raises(bs_sandbox.WindowsStylePath)),
        ("\\\\srv\\share\\x.py", pytest.raises(bs_sandbox.WindowsStylePath)),
        ("a\\..\\b.py", pytest.raises(bs_sandbox.WindowsStylePath)),
        ("dir/", pytest.raises(bs_sandbox.NotInWorkdirRoot)),
        ("./script.py", pytest.raises(bs_sandbox.NotInWorkdirRoot)),
        ("snapshots/script.py", pytest.raises(bs_sandbox.NotInWorkdirRoot)),
        ("/etc/passwd", pytest.raises(bs_sandbox.NotInWorkdirRoot)),
        ("../escape.py", pytest.raises(bs_sandbox.NotInWorkdirRoot)),
        ("", pytest.raises(bs_sandbox.NamesNoFile)),
        (".", pytest.raises(bs_sandbox.NamesNoFile)),
        ("..", pytest.raises(bs_sandbox.NamesNoFile)),
    ],
)
def test__validate_script_name_rejects(w_script_name, expectation):
    with expectation as exc_info:
        bs_sandbox._validate_script_name(w_script_name)

    assert exc_info.value.script_name == w_script_name


@pytest.mark.parametrize(
    "xtra_args_kwargs",
    [
        {},
        {"extra_args": ["--foo"]},
    ],
)
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
    xtra_args_kwargs,
):
    csa.return_value = ["CORE"]
    venvsa.return_value = ["VENV"]
    wdsa.return_value = ["WORKDIR"]
    volsa.return_value = ["VOLUMES"]

    volumes = {"readonly": VOLUME_RO}
    sandbox = bs_sandbox.BwrapSandbox(
        default_environment=ENVIRONMENT_NAME,
        config=sandbox_config,
        volumes=volumes,
    )

    workdir_path = tmp_path / "workdir"
    command = ["ls", "-laF"]
    expected = (
        ["CORE", "VENV", "WORKDIR", "VOLUMES"]
        + xtra_args_kwargs.get("extra_args", [])
        + command
    )
    exp_xtra_vols = xtra_vols_kwargs.get("extra_volumes", {})

    found = sandbox.build_bwrap_command(
        workdir_path=workdir_path,
        command=command,
        **env_kwargs,
        **xtra_vols_kwargs,
        **xtra_args_kwargs,
    )

    assert found == expected

    if xtra_args_kwargs:
        assert "--foo" in found

    csa.assert_called_once_with()
    venvsa.assert_called_once_with(exp_env_name, sandbox_config)
    wdsa.assert_called_once_with(workdir_path)
    volsa.assert_called_once_with(volumes | exp_xtra_vols)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "xtra_args_kwargs",
    [
        {},
        {"extra_args": ["--foo"]},
    ],
)
@pytest.mark.parametrize(
    "xtra_vols_kwargs",
    [
        {},
        {"extra_volumes": {"other": OTHER_VOLUME_RO}},
    ],
)
@pytest.mark.parametrize("w_workdir", [False, True])
@mock.patch("tempfile.TemporaryDirectory")
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_python_w_success(
    cs_exec,
    tftd,
    tmp_path,
    sandbox_config,
    bare_environment,
    w_workdir,
    xtra_vols_kwargs,
    xtra_args_kwargs,
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
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_python(
        script=script,
        **kwargs,
        **xtra_vols_kwargs,
        **xtra_args_kwargs,
    )

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.stdout == "hello\n"
    assert found.stderr == ""
    assert found.exit_code == 0
    assert not found.truncated

    ((args, kwargs),) = cs_exec.call_args_list
    assert args[-2:] == (
        "/sandbox/venv/bin/python",
        "/sandbox/work/script.py",
    )
    assert kwargs == {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }

    multis = _extract_multis(args)
    if xtra_vols_kwargs:
        exp_bind = (str(OTHER_HOST_VOLUME_PATH), "/sandbox/volumes/other")
        ro_binds = multis["--ro-bind"]
        assert exp_bind in ro_binds

    if xtra_args_kwargs:
        assert "--foo" in args


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_python_w_truncation(
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
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_python(script=script, workdir=workdir)
    exp_output = "X" * 8 + "\n[... 83 characters omitted ...]\n" + "X" * 9

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.stdout == exp_output
    assert found.stderr == ""
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
async def test_bwrapsandboxcommand_execute_python_w_error(
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
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_python(script=script, workdir=workdir)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.stdout == ""
    assert found.stderr == "error"
    assert found.exit_code == 1


@pytest.mark.asyncio
@mock.patch("asyncio.wait_for")
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_python_w_timeout(
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
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_python(
        script=script,
        workdir=workdir,
        timeout=timeout_seconds,
    )

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.timed_out
    assert found.exit_code is None

    proc.kill.assert_called_once_with()
    proc.wait.assert_awaited_once_with()

    ((args, kwargs),) = wait_for.call_args_list
    assert kwargs == {"timeout": 0.02}

    # 'wait_for' raises without awaiting calling the 'proc.communicate' coro
    cs_exec.return_value.communicate.assert_not_awaited()
    await args[0]  # avoid tracemalloc warning


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "xtra_args_kwargs",
    [
        {},
        {"extra_args": ["--foo"]},
    ],
)
@pytest.mark.parametrize(
    "xtra_vols_kwargs",
    [
        {},
        {"extra_volumes": {"other": OTHER_VOLUME_RO}},
    ],
)
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_w_success(
    cs_exec,
    tmp_path,
    sandbox_config,
    bare_environment,
    xtra_vols_kwargs,
    xtra_args_kwargs,
):
    proc = cs_exec.return_value
    proc.communicate.return_value = (b".  ..\n", b"")
    proc.returncode = 0

    workdir = tmp_path / "work"
    workdir.mkdir()

    command = ["ls", "-a", "/sandbox/work"]

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(
        command=command,
        workdir=workdir,
        **xtra_vols_kwargs,
        **xtra_args_kwargs,
    )

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.stdout == ".  ..\n"
    assert found.stderr == ""
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

    multis = _extract_multis(args)
    if xtra_vols_kwargs:
        exp_bind = (str(OTHER_HOST_VOLUME_PATH), "/sandbox/volumes/other")
        ro_binds = multis["--ro-bind"]
        assert exp_bind in ro_binds

    if xtra_args_kwargs:
        assert "--foo" in args


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
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(command=command)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.stdout == "hello\n"
    assert found.stderr == ""
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
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(command=command, workdir=workdir)
    exp_output = "X" * 8 + "\n[... 83 characters omitted ...]\n" + "X" * 9

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.stdout == exp_output
    assert found.stderr == ""
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
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(command=command, workdir=workdir)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.stdout == ""
    assert found.stderr == "error"
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
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(
        command=command,
        workdir=workdir,
        timeout=timeout_seconds,
    )

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.timed_out
    assert found.exit_code is None

    proc.kill.assert_called_once_with()
    proc.wait.assert_awaited_once_with()

    ((args, kwargs),) = wait_for.call_args_list
    assert kwargs == {"timeout": 0.01}

    # 'wait_for' raises without awaiting calling the 'proc.communicate' coro
    cs_exec.return_value.communicate.assert_not_awaited()
    await args[0]  # avoid tracemalloc warning


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_separates_streams(
    cs_exec,
    tmp_path,
    sandbox_config,
    bare_environment,
):
    proc = cs_exec.return_value
    proc.communicate.return_value = (b"the answer\n", b"a warning\n")
    proc.returncode = 0

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(command=["/bin/true"], workdir=workdir)

    assert found.stdout == "the answer\n"
    assert found.stderr == "a warning\n"
    assert not found.timed_out


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_truncates_each_stream(
    cs_exec,
    tmp_path,
    sandbox_config,
    bare_environment,
):
    sandbox_config.max_output_chars = 5
    proc = cs_exec.return_value
    proc.communicate.return_value = (b"X" * 20, b"Y" * 20)
    proc.returncode = 0

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(command=["/bin/true"], workdir=workdir)

    assert found.stdout == "X" * 5
    assert found.stderr == "Y" * 5
    assert found.truncated
    assert found.max_output_chars == 5


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_reports_untruncated_limit(
    cs_exec,
    tmp_path,
    sandbox_config,
    bare_environment,
):
    proc = cs_exec.return_value
    proc.communicate.return_value = (b"short", b"")
    proc.returncode = 0

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(command=["/bin/true"], workdir=workdir)

    assert not found.truncated
    assert found.max_output_chars == sandbox_config.max_output_chars


@pytest.mark.asyncio
@mock.patch("asyncio.wait_for")
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_reports_timeout_distinctly(
    cs_exec,
    wait_for,
    tmp_path,
    sandbox_config,
    bare_environment,
):
    proc = cs_exec.return_value
    proc.kill = mock.Mock(spec_set=())
    proc.returncode = -99
    wait_for.side_effect = TimeoutError

    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(
        command=["/bin/true"],
        workdir=workdir,
        timeout=0.02,
    )

    assert found.timed_out
    assert found.timeout_seconds == 0.02
    assert found.exit_code is None

    ((args, kwargs),) = wait_for.call_args_list
    await args[0]  # avoid tracemalloc warning


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_python_w_script_name(
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

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    await sandbox.execute_python(
        script="print('hello')",
        workdir=workdir,
        script_name="run-1.py",
    )

    written = workdir / "run-1.py"
    assert written.read_text(encoding="utf-8") == "print('hello')"

    ((args, _),) = cs_exec.call_args_list
    assert args[-2:] == (
        "/sandbox/venv/bin/python",
        "/sandbox/work/run-1.py",
    )


@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_python_rejects_script_name(
    cs_exec,
    tmp_path,
    sandbox_config,
    bare_environment,
):
    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    with pytest.raises(bs_sandbox.NotInWorkdirRoot):
        await sandbox.execute_python(
            script="print('hello')",
            workdir=workdir,
            script_name="../escape.py",
        )

    cs_exec.assert_not_called()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
@pytest.mark.asyncio
@mock.patch("asyncio.create_subprocess_exec")
async def test_bwrapsandboxcommand_execute_python_wo_following_symlink(
    cs_exec,
    tmp_path,
    sandbox_config,
    bare_environment,
):
    proc = cs_exec.return_value
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0

    workdir = tmp_path / "work"
    workdir.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("ORIGINAL", encoding="utf-8")
    (workdir / "script.py").symlink_to(victim)

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    await sandbox.execute_python(script="print(1)", workdir=workdir)

    assert victim.read_text(encoding="utf-8") == "ORIGINAL"
    written = workdir / "script.py"
    assert not written.is_symlink()
    assert written.read_text(encoding="utf-8") == "print(1)"


class _Alarm(BaseException):
    """Alarm exception outside the 'OSError' hierarchy."""


@contextlib.contextmanager
def _deadline(seconds):
    def _fire(signum, frame):
        raise _Alarm

    previous = signal.signal(signal.SIGALRM, _fire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX FIFOs")
def test_write_script_wo_blocking_on_fifo(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    os.mkfifo(workdir / "script.py")

    with _deadline(2.0):
        bs_sandbox.write_script(workdir, "script.py", "print(1)")

    written = workdir / "script.py"
    assert stat.S_ISREG(written.lstat().st_mode)
    assert written.read_text(encoding="utf-8") == "print(1)"


def test_write_script_rejects_directory_target(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "script.py").mkdir()

    with pytest.raises(bs_sandbox.CannotBeReplacedInWorkdir):
        bs_sandbox.write_script(workdir, "script.py", "print(1)")

    assert [p.name for p in workdir.iterdir()] == ["script.py"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX hard links")
def test_write_script_replaces_rather_than_writing_through(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("ORIGINAL", encoding="utf-8")
    (workdir / "script.py").hardlink_to(victim)

    bs_sandbox.write_script(workdir, "script.py", "print(1)")

    assert victim.read_text(encoding="utf-8") == "ORIGINAL"
    written = workdir / "script.py"
    assert written.read_text(encoding="utf-8") == "print(1)"
    assert not written.samefile(victim)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_write_script_w_owner_only_file(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()

    bs_sandbox.write_script(workdir, "script.py", "print(1)")

    assert [p.name for p in workdir.iterdir()] == ["script.py"]
    assert (workdir / "script.py").stat().st_mode & 0o777 == 0o600


def test_deadline_guard_fires():
    with pytest.raises(_Alarm):
        with _deadline(0.01):
            time.sleep(2.0)


def test_write_script_w_uncreatable_file(tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    workdir.mkdir()

    real_open = os.open

    def _refuse(path, flags, *args, **kwargs):
        if flags & os.O_CREAT:
            raise PermissionError(13, "Permission denied")

        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", _refuse)

    with pytest.raises(bs_sandbox.CannotBeCreatedInWorkdir):
        bs_sandbox.write_script(workdir, "script.py", "print(1)")


def test_write_script_w_unencodable_script(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    previous = workdir / "script.py"
    previous.write_text("print(0)", encoding="utf-8")

    with pytest.raises(UnicodeEncodeError):
        bs_sandbox.write_script(workdir, "script.py", "bad: \udc80")

    assert [p.name for p in workdir.iterdir()] == ["script.py"]
    assert previous.read_text(encoding="utf-8") == "print(0)"


@pytest.mark.parametrize(
    "w_text, w_limit, exp_text, exp_cut",
    [
        ("X" * 50, 50, "X" * 50, False),
        (
            "A" * 50 + "Z" * 50,
            50,
            "A" * 8 + "\n[... 83 characters omitted ...]\n" + "Z" * 9,
            True,
        ),
        # No room for the marker: keep the beginning.
        ("X" * 20, 5, "X" * 5, True),
    ],
)
def test_truncate(w_text, w_limit, exp_text, exp_cut):
    found, cut = bs_sandbox._truncate(w_text, w_limit)

    assert found == exp_text
    assert cut is exp_cut
    assert len(found) <= w_limit


def test_truncate_counts_omission_after_marker_grows():
    # 1000 over the limit before the marker, so the count needs 4 digits.
    text = "X" * 1_100

    found, _ = bs_sandbox._truncate(text, 100)

    assert len(found) == 100
    assert "[... 1035 characters omitted ...]" in found
