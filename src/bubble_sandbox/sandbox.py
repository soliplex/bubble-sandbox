import asyncio
import pathlib
import sys
import tempfile

from bubble_sandbox import models as bs_models
from bubble_sandbox import settings as bs_settings

_VENV_PYTHON = (
    pathlib.PurePosixPath("bin", "python")
    if sys.platform != "win32"
    else pathlib.PureWindowsPath("Scripts", "python.exe")
)

_MAX_OUTPUT = 100_000


class InvalidEnvironmenName(ValueError):
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


class ExtensionNotAllowed(ValueError):
    def __init__(self, extension, allowed_extensions):
        self.extension = extension
        self.allowed_extensions = allowed_extensions
        super().__init__(
            f"File extension {extension!r} not allowed. "
            f"Allowed: {allowed_extensions}"
        )


class MaxUploadSizeExceded(ValueError):
    def __init__(self, total_size, max_upload_size_bytes):
        self.total_size = total_size
        self.max_upload_size_bytes = max_upload_size_bytes
        super().__init__(
            f"Total upload size {total_size} bytes exceeds"
            f" limit of {max_upload_size_bytes} bytes"
        )


def resolve_venv_path(
    environment_name: str,
    settings: bs_settings.Settings,
) -> pathlib.Path:
    """Return the path to an environment's virtualenv"""

    if (
        "/" in environment_name
        or "\\" in environment_name
        or ".." in environment_name
    ):
        raise InvalidEnvironmenName(environment_name)

    environment_path = settings.environments_path / environment_name

    if not environment_path.is_dir():
        raise EnvironmentNotFound(environment_path)

    venv_python = environment_path / ".venv" / _VENV_PYTHON

    if not venv_python.exists():
        raise EnvironmentNotInitialized(environment_name, venv_python)

    return environment_path / ".venv"


def validate_uploads(
    files: dict[str, bytes],
    settings: bs_settings.Settings,
) -> None:
    total_size = 0
    for name, content in files.items():
        extension = pathlib.PurePosixPath(name).suffix.lower()

        if extension not in settings.allowed_extensions:
            raise ExtensionNotAllowed(extension, settings.allowed_extensions)

        total_size += len(content)

    if total_size > settings.max_upload_size_bytes:
        raise MaxUploadSizeExceded(total_size, settings.max_upload_size_bytes)


def core_sandbox_args(network: bool = False) -> list[str]:
    """Return 'bwrap' and arguments which are always present

    Include a mount for '/lib64' only if that directory is present
    on the host system.

    Args:
      'network' (boolean): if True, omit the '--unshare-net' flag
    """
    result = [
        "bwrap",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/lib",
        "/lib",
    ]

    if pathlib.Path("/lib64").exists():
        result.extend(["--ro-bind", "/lib64", "/lib64"])

    result.extend(
        [
            "--symlink",
            "usr/bin",
            "/bin",
            "--symlink",
            "usr/sbin",
            "/sbin",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--unshare-user",
            "--unshare-pid",
            "--new-session",
            "--die-with-parent",
        ]
    )

    if not network:
        result.append("--unshare-net")

    return result


def venv_sandbox_args(
    env_name: str,
    settings: bs_settings.Settings,
) -> list[str]:
    """Return added 'bwrap' args based on the given sandbox environment"""
    venv_path = resolve_venv_path(env_name, settings)

    return [
        "--ro-bind",
        str(venv_path),
        "/sandbox/venv",
        "--setenv",
        "PATH",
        "/sandbox/venv/bin:/usr/bin:/bin",
    ]


def workdir_sandbox_args(
    workdir: pathlib.Path,
) -> list[str]:
    """Return added 'bwrap' args based on the given work directory

    Note that the work directory is mounte with read-write permissions.
    """
    return [
        "--bind",
        str(workdir),
        "/sandbox/work",
    ]


def volumes_sandbox_args(volumes: list[bs_models.VolumeMount]) -> list[str]:
    """Return added 'bwrap' args based on the given volumes"""
    result = []

    for volume in volumes:
        if volume.writable:
            result.extend(
                ["--bind", str(volume.host_path), str(volume.sandbox_path)]
            )
        else:
            result.extend(
                ["--ro-bind", str(volume.host_path), str(volume.sandbox_path)]
            )

    return result


def _build_bwrap_command(
    venv_path: pathlib.Path,
    workdir: pathlib.Path,
    command: list[str],
    network: bool = False,
) -> list[str]:
    cmd = [
        "bwrap",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/lib",
        "/lib",
    ]
    if pathlib.Path("/lib64").exists():
        cmd.extend(["--ro-bind", "/lib64", "/lib64"])
    cmd.extend(
        [
            "--symlink",
            "usr/bin",
            "/bin",
            "--symlink",
            "usr/sbin",
            "/sbin",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--ro-bind",
            str(venv_path),
            "/sandbox/venv",
            "--bind",
            str(workdir),
            "/sandbox/work",
            "--chdir",
            "/sandbox/work",
            "--unshare-user",
            "--unshare-pid",
            "--new-session",
            "--die-with-parent",
        ]
    )

    if not network:
        cmd.append("--unshare-net")

    cmd.extend(
        [
            "--setenv",
            "PATH",
            "/sandbox/venv/bin:/usr/bin:/bin",
        ]
    )
    cmd.extend(command)
    return cmd


async def execute_in_sandbox(
    script: str,
    env_name: str,
    files: dict[str, bytes],
    settings: bs_settings.Settings,
) -> bs_models.ScriptResult:
    venv_path = resolve_venv_path(env_name, settings)
    with tempfile.TemporaryDirectory(
        prefix="exec-",
        ignore_cleanup_errors=True,
    ) as workdir_str:
        workdir = pathlib.Path(workdir_str)

        script_path = workdir / "script.py"
        script_path.write_text(script, encoding="utf-8")

        for name, content in files.items():
            safe_name = pathlib.PurePosixPath(name).name
            file_path = workdir / safe_name
            file_path.write_bytes(content)

        cmd = _build_bwrap_command(
            venv_path,
            workdir,
            ["/sandbox/venv/bin/python", "/sandbox/work/script.py"],
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=settings.execution_timeout_seconds,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return bs_models.ScriptResult(
                stdout="",
                stderr="Execution timed out",
                return_code=-1,
            )

        return bs_models.ScriptResult(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            return_code=proc.returncode or 0,
        )


async def execute_command_in_sandbox(
    command: str,
    venv_path: pathlib.Path,
    workdir: pathlib.Path,
    timeout: int | None = None,
) -> bs_models.ExecuteResult:
    cmd = _build_bwrap_command(
        venv_path,
        workdir,
        ["sh", "-c", command],
    )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout or 30,
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return bs_models.ExecuteResult(
            output="Execution timed out",
            exit_code=-1,
        )

    raw = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    output = raw + err if err else raw

    truncated = len(output) > _MAX_OUTPUT
    if truncated:
        output = output[:_MAX_OUTPUT]

    return bs_models.ExecuteResult(
        output=output,
        exit_code=proc.returncode or 0,
        truncated=truncated,
    )
