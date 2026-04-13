import pathlib

import pydantic


class EnvironmentInfo(pydantic.BaseModel):
    name: str
    description: str
    dependencies: list[str] = []


class VolumeInfo(pydantic.BaseModel):
    host_path: pathlib.Path
    writable: bool


VolumeMap = dict[str, VolumeInfo]  # sandbox volume name: vol info


class ExecuteResult(pydantic.BaseModel):
    output: str
    exit_code: int | None = None
    truncated: bool = False
