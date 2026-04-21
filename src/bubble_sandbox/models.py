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

      'output'
        Concatenated stdout / stderr from the execution

      'exit_code'
        Code returned from the execution ('None' indicates that
        the requested command / script was not executed).

      'trunctated'
        True if 'output' was longer than the configured maximum
        length, else False.
    """

    output: str
    exit_code: int | None = None
    truncated: bool = False
