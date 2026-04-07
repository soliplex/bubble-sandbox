# bubble-sandbox

...

This package also provides a `bubble-session` driver command:

- `bubble-session` manages sessions which represent "persistent" state
  across multiple sandbox invocations.  A session can map one or more
  host system directories as read-only or read-write mounts in the
  sandbox filesytem.

...

## CLI commands

...

### `bubble-sandbox exec-script`

...


Script with a file copied into sandbox (the `--copy-file` argument
can be repeated):

```bash
uv run bubble-sandbox exec-script \
  --environment="pandas-exec" \
  --copy-file="/path/to/data.csv" \
  --script="import pandas as pd; df = pd.read_csv('data.csv'); print(df.head())"\
  | jq
```
```json
{
  "stdout": "   col_1 col_2...\n0     1  descr...\n...",
  "stderr": "",
  "return_code": 0
}
```

### Session Management

Sessions provide stateful sandboxes with persistent working directories, file operations, and optional volume mounts.

#### List active sessions

```bash
uv run bubble-session list-sessions | jq
```
```json
{
  "sessions": [
    {
      "session_id": "abc123",
      "environment": "bare",
      "created_at": "2026-03-31T12:00:00+00:00",
      "last_activity": "2026-03-31T12:00:00+00:00",
      "volumes": {}
    },
    ...
  ]
}
```

#### Get an existing session:

```bash
uv run bubble-session get-sesssion abc123 | jq
```

```json
{
  "session_id": "abc123",
  "environment": "bare",
  "created_at": "2026-03-31T12:00:00+00:00",
  "last_activity": "2026-03-31T12:00:00+00:00",
  "volumes": {}
}
```

#### Create a new session

Create a session with generated ID:

```bash
uv run bubble-session new-session \
    --environment "bare" \
    --volume "foo,foo" | jq
```
```json
{
  "session_id": "<UUID4>",
  "environment": "bare",
  "created_at": "2026-03-31T12:00:00+00:00",
  "last_activity": "2026-03-31T12:00:00+00:00",
  "volumes": {"foo": "foo"}
}
```

Create a session with a specified ID:

```bash
uv run bubble-session new-session \
    --environment "bare" \
    --volume "foo,foo" \
    --session-id def445 | jq
```
```json
{
  "session_id": "def456",
  "environment": "bare",
  "created_at": "2026-03-31T12:00:00+00:00",
  "last_activity": "2026-03-31T12:00:00+00:00",
  "volumes": {"foo": "foo"}
}
```

If a session with the same `session_id`, `environment`, and `volumes` already
exists, it is returned (idempotent).

If the config differs, returns an error, reporting the conflict.

#### Delete a session

Delete a session, but retain its workspace directory in the host's workspaces
directory:

```bash
uv run bubble-session --session-id def445 \
    delete-session | jq
```
```json
null
```

Delete a session, removing its workspace directory:

```bash
uv run bubble-session --session-id def445 \
    delete-session --clear-data | jq
```
```json
null
```

#### Remove idle sessions

Remove sessions idle for longer than the default:
```bash
uv run bubble-session remove-idle-sessions | jq
```
```json
{
  "removed_sessions": [
    "abc123",
    "def456",
  ]
}
```

Remove sessions idle for longer than a specified interval in seconds:

```bash
uv run bubble-session remove-idle-sessions \
  --max-idle 7200 \
  --clear-data | jq
```
```json
{
  "removed_sessions": [
    "abc123",
    "def456",
  ]
}
```

Remove all sessions clearing their workspace directories:

```bash
uv run bubble-session remove-idle-sessions \
  --max-idle 0 \
  --clear-data | jq
```
```json
{
  "removed_sessions": [
    "abc123",
    "def456",
  ]
}
```

#### Operations within a session

All file paths are validated to prevent directory traversal (`../` is rejected).

Run a shell command in the session's sandbox:

```bash
uv run bubble-session --session-id <session_id> \
    execute 'echo "test"' | jq
```
```json
{
  "stdout": "test\n",
  "stderr": "",
  "return_code": 0
}
```

Read a file from the session's sandbox

```bash
uv run bubble-session --session-id <session_id> \
    read-file test.txt
{
  "stdout": "Whatever content is in the sandbox file 'test.txt'",
  "stderr": "",
  "return_code": 0
}
```

Write a file to the session's sandbox

```bash
uv run bubble-session --session-id <session_id> \
    write-file test.txt host-file.txt | jq
```
```json
{
  "stdout": "Wrote file :'test.txt'",
  "stderr": "",
  "return_code": 0
}
```

Find and replace a string in a sandbox file:

```bash
uv run bubble-session --session-id <session_id> \
    edit-file test.xt "find str" "replace str" | jq
```
```json
{
  "stdout": "Edited file: 'test.txt'",
  "stderr": "",
  "return_code": 0
}
```

List the contents of the workspace directory:

```bash
uv run bubble-session --session-id <session_id> \
    list-files | jq
```
```json
{
  "stdout": "abc.csv\ntest.txt",
  "stderr": "",
  "return_code": 0
}
```

List workspace files by glob pattern:

```bash
uv run bubble-session --session-id <session_id> \
    list-files "abc*" | jq
```
```json
{
  "stdout": "abc.csv",
  "stderr": "",
  "return_code": 0
}
```

Grep workspace files

```bash
uv run bubble-session --session-id <session_id> \
    grep-files "content" | jq
```
```json
{
  "stdout": "test.txt",
  "stderr": "",
  "return_code": 0
}
```

### Volumes

Volumes allow mounting shared data directories (read-only) into a session's workspace.

**Disk layout** (relative to `BUBBLE_SANDBOX_WORKSPACE_DIR`):

```
workspace_data/
├── sessions/
│   └── my-session/          # session workdir (rw)
└── volumes/
    └── shared-data/         # shared volume (ro in sandbox)
```

**Example:** `volumes: {"shared-data": "data"}` mounts `workspace_data/volumes/shared-data/` as `/workspace/data` (read-only) inside the sandbox.
