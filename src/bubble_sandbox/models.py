import pathlib

import pydantic


class EnvironmentInfo(pydantic.BaseModel):
    """Describe an available sandbox envronment

    Args:

      'name'
        name used to select the environment, e.g., 'bare', 'with-pandas', etc.

      'description'
        skill-agent oriented description of the environment's purpose

      'dependencies'
        list of Python projects specified in the environment (not the
        full transitive set).
    """

    name: str
    description: str
    dependencies: list[str] = []


class VolumeInfo(pydantic.BaseModel):
    """Describe a volume to be mounted into the sandbox

    Args:

      'host_path'
        path to be mounted from the host system.  If 'None', the sandbox
        will contain and empty directory at the target location.

      'writable'
        If true, the volume will be mounted read-write, else read-only.
        For 'host_path' of 'None', controls the permission mask for the
        created directory: '0755' if true, else '0644'.
    """

    host_path: pathlib.Path | None
    writable: bool


VolumeMap = dict[str, VolumeInfo]  # sandbox volume name: vol info


class ExecuteResult(pydantic.BaseModel):
    """Result of executing a command or script

    Args:

      'stdout'
        What the execution wrote to stdout, truncated to
        'max_output_chars' by replacing its middle with a marker.

      'stderr'
        What it wrote to stderr, truncated the same way.  The limit
        applies to each stream separately.

      'output'
        'stdout' and 'stderr' concatenated.

      'exit_code'
        Code returned from the execution.  'None' when it did not run to
        completion: it was never executed, or it timed out.

      'truncated'
        True if either stream was longer than 'max_output_chars'.

      'max_output_chars'
        The per-stream limit truncation was applied at.

      'timed_out'
        True if the execution was killed for exceeding
        'timeout_seconds'.

      'timeout_seconds'
        The limit that was applied, whether or not it was hit.
    """

    # An unknown field is an error, not something to drop silently.
    model_config = pydantic.ConfigDict(extra="forbid")

    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    truncated: bool = False
    max_output_chars: int | None = None
    timed_out: bool = False
    timeout_seconds: float | None = None
