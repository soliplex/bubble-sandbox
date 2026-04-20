import asyncio
import contextlib
import dataclasses
import pathlib
import sys
import tempfile

from bubble_sandbox import config as bs_config
from bubble_sandbox import models as bs_models

_SYS_BASE_PREFIX = sys.base_prefix

_MAX_OUTPUT_CHARS = 100_000


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
        host_path = str(volume_info.host_path)

        if volume_info.writable:
            result.extend(["--bind", host_path, sandbox_path])
        else:
            result.extend(["--ro-bind", host_path, sandbox_path])

    return result


@dataclasses.dataclass(kw_only=True)
class BwrapSandbox:
    default_environment_name: str
    config: bs_config.Config
    volumes: bs_models.VolumeMap = dataclasses.field(default_factory=dict)

    def build_bwrap_command(
        self,
        *,
        workdir_path: pathlib.Path | None,
        command: list[str],
        environment_name: str = None,
        extra_volumes: bs_models.VolumeMap = None,
    ) -> list[str]:
        if environment_name is None:
            environment_name = self.default_environment_name

        if extra_volumes is None:
            extra_volumes = {}

        return (
            core_sandbox_args()
            + venv_sandbox_args(environment_name, self.config)
            + workdir_sandbox_args(workdir_path)
            + volumes_sandbox_args(self.volumes | extra_volumes)
            + command
        )

    async def execute_script(
        self,
        *,
        script: str,
        environment_name: str = None,
        workdir: pathlib.Path | str = None,
        timeout: float = None,  # seconds
        extra_volumes: bs_models.VolumeMap = None,
    ) -> bs_models.ExecuteResult:

        if workdir is None:
            workdir_context = tempfile.TemporaryDirectory(
                ignore_cleanup_errors=True,
            )
        else:
            workdir_context = contextlib.nullcontext(workdir)

        with workdir_context as workdir_str:
            workdir_path = pathlib.Path(workdir_str)

            script_path = workdir_path / "script.py"
            script_path.write_text(script, encoding="utf-8")

            return await self.execute(
                command=[
                    "/sandbox/venv/bin/python",
                    "/sandbox/work/script.py",
                ],
                environment_name=environment_name,
                workdir=workdir_path,
                timeout=timeout,
                extra_volumes=extra_volumes,
            )

    async def execute(
        self,
        *,
        command: list[str],
        environment_name: str = None,
        workdir: pathlib.Path | None = None,
        timeout: float = None,  # seconds
        extra_volumes: bs_models.VolumeMap = None,
    ) -> bs_models.ExecuteResult:

        if timeout is None:
            timeout = self.config.execution_timeout_seconds

        bwrap_command = self.build_bwrap_command(
            command=command,
            workdir_path=workdir,
            environment_name=environment_name,
            extra_volumes=extra_volumes,
        )

        proc = await asyncio.create_subprocess_exec(
            *bwrap_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return bs_models.ExecuteResult(
                output="Execution timed out",
                exit_code=-1,
            )

        stdout = stdout.decode("utf-8", errors="replace")
        stderr = stderr.decode("utf-8", errors="replace")
        output = stdout + stderr
        truncated = len(output) > self.config.max_output_chars

        if truncated:
            output = output[: self.config.max_output_chars]

        return bs_models.ExecuteResult(
            output=output,
            exit_code=proc.returncode or 0,
            truncated=truncated,
        )
