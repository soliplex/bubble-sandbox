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


VolumeMap = dict[str, str]  # host -> sandbox


class SessionInfo(pydantic.BaseModel):
    session_id: str
    environment: str
    created_at: str
    last_activity: str
    volumes: VolumeMap = {}
