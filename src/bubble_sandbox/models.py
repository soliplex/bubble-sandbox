import pathlib

import pydantic


class VolumeInfo(pydantic.BaseModel):
    host_path: pathlib.Path
    writable: bool


VolumeMap = dict[str, VolumeInfo]  # sandbox volume name: vol info


class ExecuteResult(pydantic.BaseModel):
    output: str
    exit_code: int | None = None
    truncated: bool = False
