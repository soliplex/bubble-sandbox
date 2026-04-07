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
  copy host-sytem files into the `/sandbox/workspace` directory (the working
  directory in which the script runs).


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

Inline script with no files:

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

Script stored in a file (no extra files):

```bash
uv run bubble-sandbox exec-script \
  --environment="bare" \
  --script-file=/path/to/my_script.py | jq
```
```json
{
  ...
}
```

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

**Note**:  Avoid using a Python here which derives from another virtual environment:  instead, use the "base" environment.  E.g.:

```
uv sync --python="/opt/Python-3.13.12"
```

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
| `pandas-exec` | pandas 3.0.1+  | Data analysis with pandas   |

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

# Sync environment venvs (for local testing) (see note above).
cd environments/bare && uv sync && cd ../..
cd environments/pandas-exec && uv sync && cd ../..

# Run tests (100% coverage required)
uv run pytest

# Lint and format
uv run ruff check
uv run ruff format --check
```
