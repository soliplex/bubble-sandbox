import asyncio
import contextlib
import dataclasses
import os
import pathlib
import sys
import tempfile
import uuid

from bubble_sandbox import config as bs_config
from bubble_sandbox import models as bs_models

_SYS_BASE_PREFIX = sys.base_prefix

_MAX_OUTPUT_CHARS = 100_000

# Bubblewrap execution is Linux-only; Windows lacks these flags.
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    """Return 'text' capped at 'limit', and whether it was cut.

    The middle is replaced by a marker counting what was dropped, so both
    the start of a stream and its end (where a traceback is) survive.
    """
    if len(text) <= limit:
        return text, False

    omitted = len(text) - limit

    while True:
        marker = f"\n[... {omitted} characters omitted ...]\n"
        kept = limit - len(marker)

        if kept <= 0:
            return text[:limit], True

        if len(text) - kept == omitted:
            break

        # The marker's own length grew the count; recount with it.
        omitted = len(text) - kept

    head = kept // 2
    return text[:head] + marker + text[len(text) - (kept - head) :], True


def _extant_ro_binds(*paths: str) -> list[str]:
    """Return '--ro-bind' args for each given path that exists (as a
    file or a directory) on the host.
    """
    result = []

    for path in paths:
        if pathlib.Path(path).exists():
            result.extend(["--ro-bind", path, path])

    return result


def openjdk_binds() -> list[str]:
    """Return '--ro-bind' args for OpenJDK install and config
    directories found on the host (e.g. '/usr/lib/jvm',
    '/usr/share/java', '/etc/java', '/etc/java-21-openjdk').

    JDKs are typically installed under '/usr/lib/jvm', with shared
    jars under '/usr/share/java'; RPM-based distros (Fedora, RHEL,
    etc.) additionally keep a symlink farm for each installed OpenJDK
    version at '/etc/java-<N>-openjdk', while Debian-based distros
    keep shared alternatives config at '/etc/java'. None of these are
    necessarily covered by the '/usr' bind mount above, so any that
    are present must be added explicitly.

    Commands such as '/usr/bin/java' are themselves usually symlinks
    through '/etc/alternatives' to the real binary; that directory is
    bound generally in 'core_sandbox_args' since it's shared by many
    update-alternatives-managed commands, not just Java's.
    """
    result = _extant_ro_binds(
        "/usr/lib/jvm",
        "/usr/share/java",
        "/etc/java",
    )

    for etc_openjdk_path in sorted(
        pathlib.Path("/etc").glob("java-*-openjdk")
    ):
        if etc_openjdk_path.is_dir():
            etc_openjdk = str(etc_openjdk_path)
            result.extend(["--ro-bind", etc_openjdk, etc_openjdk])

    return result


def core_sandbox_args(network: bool = False) -> list[str]:
    """Return 'bwrap' and arguments which are always present

    Include mounts for '/lib64', '/etc/alternatives', '/etc/fonts',
    '/etc/papersize', and '/etc/paperspecs' only if present on the host.

    '/etc/papersize' names the configured default paper size (e.g.
    "letter"), and '/etc/paperspecs' is libpaper's own lookup table
    mapping every recognized paper name to its dimensions (confirmed via
    strace: dvipdfmx/libpaper opens both). Without '/etc/paperspecs' in
    particular, libpaper has no table to validate *any* name against, so
    every paper format -- not just the configured default -- comes back
    "Unrecognized paper format" regardless of '-p'/$PAPERSIZE.

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
        "--ro-bind",
        "/var/lib",
        "/var/lib",
        "--ro-bind",
        "/usr/share",
        "/usr/share",
    ]

    result.extend(
        _extant_ro_binds(
            "/lib64",
            "/etc/alternatives",
            "/etc/fonts",
            "/etc/papersize",
            "/etc/paperspecs",
        )
    )
    result.extend(openjdk_binds())

    if _SYS_BASE_PREFIX != "/usr":
        result.extend(
            [
                "--ro-bind",
                _SYS_BASE_PREFIX,
                _SYS_BASE_PREFIX,
            ]
        )

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
            "--perms",
            "0644",
            "--dir",
            "/var/empty",
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
    config: bs_config.Config,
) -> list[str]:
    """Return added 'bwrap' args based on the given sandbox environment"""
    venv_path = config.resolve_venv_path(env_name)

    return [
        "--ro-bind",
        str(venv_path.resolve()),
        "/sandbox/venv",
        "--setenv",
        "PATH",
        "/sandbox/venv/bin:/usr/bin:/bin",
    ]


def workdir_sandbox_args(
    workdir: pathlib.Path | None,
) -> list[str]:
    """Return added 'bwrap' args based on the given work directory

    Note that the work directory is mounte with read-write permissions.
    """
    if workdir is not None:
        return [
            "--bind",
            str(workdir),
            "/sandbox/work",
            "--chdir",
            "/sandbox/work",
        ]
    else:
        return []


def volumes_sandbox_args(volume_map: bs_models.VolumeMap) -> list[str]:
    """Return added 'bwrap' args based on the given volumes"""
    result = []

    for volume_name, volume_info in volume_map.items():
        sandbox_path = f"/sandbox/volumes/{volume_name}"

        if volume_info.host_path is None:  # create empty dir
            if volume_info.writable:
                result.extend(["--perms", "0755", "--dir", sandbox_path])
            else:
                result.extend(["--perms", "0644", "--dir", sandbox_path])

        else:  # create a bind mount
            host_path = str(volume_info.host_path)

            if volume_info.writable:
                result.extend(["--bind", host_path, sandbox_path])
            else:
                result.extend(["--ro-bind", host_path, sandbox_path])

    return result


DEFAULT_SCRIPT_PATH = "script.py"


class InvalidScriptPath(ValueError):
    def __init__(self, script_path, reason):
        self.script_path = script_path
        self.reason = reason
        super().__init__(f"Invalid script path {script_path!r}: {reason}")


def _script_path_parts(script_path: str) -> tuple[str, ...]:
    """Return validated components of a relative script path."""
    if script_path.strip() != script_path:
        raise InvalidScriptPath(
            script_path,
            "Paths with leading / trailing whitespace not allowed",
        )

    if "\\" in script_path:
        raise InvalidScriptPath(
            script_path,
            "Windows-style paths are not allowed",
        )

    if script_path.endswith("/"):
        raise InvalidScriptPath(
            script_path,
            "Cannot write a directory",
        )

    path = pathlib.PurePosixPath(script_path)

    if path.is_absolute():
        raise InvalidScriptPath(script_path, "must be relative to the workdir")

    parts = tuple(part for part in path.parts if part != ".")

    if not parts:
        raise InvalidScriptPath(script_path, "names no file")

    if ".." in parts:
        raise InvalidScriptPath(script_path, "must not contain '..'")

    return parts


def _write_and_replace(
    dir_fd: int,
    name: str,
    script: str,
    script_path: str,
) -> None:
    """Atomically replace 'name' with a newly created file in 'dir_fd'."""
    temporary = f".{uuid.uuid4().hex}.tmp"

    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
            0o600,
            dir_fd=dir_fd,
        )
    except OSError as exc:
        raise InvalidScriptPath(
            script_path,
            "could not be written inside the workdir",
        ) from exc

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as script_file:
            script_file.write(script)

        os.replace(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except OSError as exc:  # EISDIR when a directory holds the name
        raise InvalidScriptPath(
            script_path,
            f"{name!r} cannot be replaced inside the workdir",
        ) from exc
    finally:
        # A successful replacement has already removed the temporary name.
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=dir_fd)


def write_script(
    workdir: pathlib.Path,
    script_path: str,
    script: str,
) -> pathlib.PurePosixPath:
    """Atomically write 'script_path' below 'workdir', following no links.

    Returns the path written, relative to 'workdir'.
    """
    parts = _script_path_parts(script_path)
    dir_fd = os.open(workdir, os.O_RDONLY | _O_DIRECTORY | os.O_CLOEXEC)
    opened = [dir_fd]

    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, dir_fd=dir_fd)
            except FileExistsError:
                pass

            try:
                dir_fd = os.open(
                    part,
                    os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=dir_fd,
                )
            except OSError as exc:  # ELOOP / ENOTDIR for a symlinked parent
                raise InvalidScriptPath(
                    script_path,
                    f"{part!r} is not a directory inside the workdir",
                ) from exc

            opened.append(dir_fd)

        _write_and_replace(dir_fd, parts[-1], script, script_path)
    finally:
        for fd in opened:
            os.close(fd)

    return pathlib.PurePosixPath(*parts)


@dataclasses.dataclass(kw_only=True)
class BwrapSandbox:
    default_environment: str
    config: bs_config.Config
    volumes: bs_models.VolumeMap = dataclasses.field(default_factory=dict)

    def build_bwrap_command(
        self,
        *,
        workdir_path: pathlib.Path | None,
        command: list[str],
        environment_name: str = None,
        extra_volumes: bs_models.VolumeMap = None,
        extra_args: list[str] = None,
    ) -> list[str]:
        if environment_name is None:
            environment_name = self.default_environment

        if extra_volumes is None:
            extra_volumes = {}

        if extra_args is None:
            extra_args = []

        return (
            core_sandbox_args()
            + venv_sandbox_args(environment_name, self.config)
            + workdir_sandbox_args(workdir_path)
            + volumes_sandbox_args(self.volumes | extra_volumes)
            + extra_args
            + command
        )

    async def execute_python(
        self,
        *,
        script: str,
        environment_name: str = None,
        workdir: pathlib.Path | str = None,
        script_path: str = DEFAULT_SCRIPT_PATH,
        timeout: float = None,  # seconds
        extra_volumes: bs_models.VolumeMap = None,
        extra_args: list[str] = None,
    ) -> bs_models.ExecuteResult:
        """Execute 'script', stored at 'script_path' relative to the
        workdir."""
        if workdir is None:
            workdir_context = tempfile.TemporaryDirectory(
                ignore_cleanup_errors=True,
            )
        else:
            workdir_context = contextlib.nullcontext(workdir)

        with workdir_context as workdir_str:
            workdir_path = pathlib.Path(workdir_str)

            written = write_script(workdir_path, script_path, script)

            return await self.execute(
                command=[
                    "/sandbox/venv/bin/python",
                    str(pathlib.PurePosixPath("/sandbox/work") / written),
                ],
                environment_name=environment_name,
                workdir=workdir_path,
                timeout=timeout,
                extra_volumes=extra_volumes,
                extra_args=extra_args,
            )

    execute_script = execute_python  # backward-compat

    async def execute(
        self,
        *,
        command: list[str],
        environment_name: str = None,
        workdir: pathlib.Path | None = None,
        timeout: float = None,  # seconds
        extra_volumes: bs_models.VolumeMap = None,
        extra_args: list[str] = None,
    ) -> bs_models.ExecuteResult:

        if timeout is None:
            timeout = self.config.execution_timeout_seconds

        bwrap_command = self.build_bwrap_command(
            command=command,
            workdir_path=workdir,
            environment_name=environment_name,
            extra_volumes=extra_volumes,
            extra_args=extra_args,
        )

        proc = await asyncio.create_subprocess_exec(
            *bwrap_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        max_output_chars = self.config.max_output_chars

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return bs_models.ExecuteResult(
                timed_out=True,
                timeout_seconds=timeout,
                max_output_chars=max_output_chars,
            )

        stdout, out_cut = _truncate(
            stdout.decode("utf-8", errors="replace"),
            max_output_chars,
        )
        stderr, err_cut = _truncate(
            stderr.decode("utf-8", errors="replace"),
            max_output_chars,
        )

        return bs_models.ExecuteResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=proc.returncode or 0,
            truncated=out_cut or err_cut,
            max_output_chars=max_output_chars,
            timeout_seconds=timeout,
        )
