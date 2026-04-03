import re

import pydantic

_SAFE_NAME_RE = re.compile(r"[a-zA-Z0-9_-]+")


class ScriptResult(pydantic.BaseModel):
    stdout: str
    stderr: str
    return_code: int


class ExecuteResult(pydantic.BaseModel):
    output: str
    exit_code: int | None = None
    truncated: bool = False
