# bubble-sandbox

A Python-specific driver for configuring
[bubblewrap](https://github.com/containers/bubblewrap) sandboxes using a
specified Python virtual environment, controlling which packages are available.

Each execution runs in a disposable sandbox with the following constraints:
- no network access
- PID isolation
- read-only filesystem (unless host directories are mounted `read-write`)

This package provides driver commands:

- `bubble-sandbox` runs `bwrap` command with arguments which populate
  the sandbox filesystem using a specified Python virtual environment
  before running a Python script in the sandbox.  The command can optionally
  copy host-sytem files into the `/workspace` directory (the working
  directory in which the script runs).

- `bubble-session` manages sessions which represent "persistent" state
  across multiple sandbox invocations.  A session can map one or more
  host system directories as read-only or read-write mounts in the
  sandbox filesytem.


## Quick Start

Build and run:

```bash
uv sync
```

```bash
uv run bubble-sandbox exec-script \
  --environment=bare' \
  --script='script=print("hello world")' | jq
```
```json
{
  "stdout": "hello world\n",
  "stderr": "",
  "return_code": 0
}
```

## CLI commands

### `bubble-sandbox list-environments`

List available execution environments and their dependencies.

```bash
uv run bubble-sandbox list-environments | jq
```
```json
{
  "environments": [
    {"name": "bare", "dependencies": []},
    {"name": "pandas-exec", "dependencies": ["pandas>=3.0.1"]}
  ]
}
```

### `bubble-sandbox exec-script`

Execute a Python script in a sandboxed environment.

Script with no files:

```bash
uv run bubble-sandbox exec-script \
  --environment="bare" \
  --script="import sys; print(sys.version)" | jq
```
```json
{
  "stdout": "3.13.12",
  "stderr": "",
  "return_code": 0
}
```

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

## Configuration

All settings are configured via environment variables with the `BUBBLE_SANDBOX_` prefix:

| Variable                              | Default          | Description                          |
|---------------------------------------|------------------|--------------------------------------|
| `BUBBLE_SANDBOX_ENVIRONMENTS_DIR`        | `environments`   | Path to environments directory       |
| `BUBBLE_SANDBOX_WORKSPACE_DIR`           | `workspace_data` | Root directory for session workspaces and volumes |
| `BUBBLE_SANDBOX_MAX_UPLOAD_SIZE_BYTES`   | `10485760`       | Max total upload size (10 MB)        |
| `BUBBLE_SANDBOX_ALLOWED_EXTENSIONS`      | `[".txt",".csv",".md",".json",".yaml",".yml",".tsv",".xml"]` | Allowed file extensions (JSON list) |
| `BUBBLE_SANDBOX_EXECUTION_TIMEOUT_SECONDS`| `30`            | Max script execution time            |
| `BUBBLE_SANDBOX_SESSION_IDLE_TIMEOUT_SECONDS`| `3600`       | Session idle timeout (seconds)       |
| `BUBBLE_SANDBOX_MAX_SESSIONS`            | `50`             | Maximum concurrent sessions          |
| `BUBBLE_SANDBOX_ALLOW_PERSISTENT_SESSIONS`| `true`          | Allow `clear_data=false` on delete   |
| `BUBBLE_SANDBOX_LOG_LEVEL`               | `INFO`           | Log level (JSON to stdout)           |

## Adding Environments

Each subdirectory in `environments/` is a self-contained Python environment with its own virtual environment and dependencies.

### 1. Create the environment directory

```bash
mkdir environments/my-env
```

### 2. Add a `pyproject.toml`

```toml
[project]
name = "my-env"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "requests>=2.32",
    "beautifulsoup4>=4.12",
]
```

### 3. Sync the environment

```bash
cd environments/my-env
uv sync
```

This creates a `.venv/` directory with the declared dependencies installed.

### 4. Use it

```bash
uv run bubble-sandbox exec-script \
  --environment="my-dnv" \
  --script='import requests; print(requests.get("http://example.com").status_code)'
```

Note: network access is disabled in the sandbox by default, so scripts that make HTTP requests will fail. The environment provides the *libraries*, not network access.

### Bundled environments

| Name          | Dependencies   | Use case                    |
|---------------|----------------|-----------------------------|
| `bare`        | *(none)*       | Standard library only       |
| `pandas-exec` | pandas 3.0.1+ | Data analysis with pandas   |

## Sandbox Isolation

Each script execution is wrapped in a bubblewrap sandbox that provides:

- **Filesystem isolation**: read-only bind mounts for system libraries and the selected venv; a writable tmpfs for `/tmp`; uploaded files available in the working directory
- **User namespace** (`--unshare-user`): runs as an unprivileged user
- **PID namespace** (`--unshare-pid`): cannot see or signal other processes
- **Network isolation** (`--unshare-net`): no network access (loopback only)
- **Session isolation** (`--new-session`): no TTY control
- **Auto-cleanup** (`--die-with-parent`): sandbox is killed if the server process dies

The sandbox working directory and all uploaded files are deleted after execution completes.

## Development

```bash
# Install dependencies
uv sync

# Sync environment venvs (for local testing)
cd environments/bare && uv sync && cd ../..
cd environments/pandas-exec && uv sync && cd ../..

# Run tests (100% coverage required)
uv run pytest

# Lint and format
uv run ruff check
uv run ruff format --check
```
