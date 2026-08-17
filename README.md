# bubble-sandbox

A Python-specific driver for configuring
[bubblewrap](https://github.com/containers/bubblewrap) sandboxes using a
specified Python virtual environment, controlling which packages are available.

Each execution runs in a disposable sandbox with the following constraints:
- no network access (unless explicitly enabled; see [Configuration](#configuration))
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
uv run bubble-sandbox list-environments

──────────────────────────── Available environments ────────────────────────────

- bare
- pandas-only

```

### `bubble-sandbox exec-script`

Execute a Python script in a sandboxed environment.

Inline script:

```bash
uv run bubble-sandbox exec-script \
  --environment="bare" \
  --script="import sys; print(sys.version_info)"

──────────── Running script: 'import sys; print(sys.version_info)' ─────────────

sys.version_info(major=3, minor=13, micro=12, releaselevel='final', serial=0)

```

Script stored in a file (same script as above):

```bash
uv run bubble-sandbox exec-script \
  --environment="bare" \
  --script-file=/tmp/foo.py

───────────────────────── Running script: @/tmp/foo.py ─────────────────────────

sys.version_info(major=3, minor=13, micro=12, releaselevel='final', serial=0)
```

### `bubble-sandbox exec-command`

Execute a shell command in a sandboxed environment.

```bash
uv run bubble-sandbox exec-command \
  --environment="bare" \
  --workdir "/tmp/test" \
  "pwd && ls -l"

───────────────────── Running shell command: pwd && ls -l ──────────────────────

/sandbox/work
total 8
-rw-rw-r-- 1 1000 1000  4 Apr  7 16:38 baz.txt
-rw-rw-r-- 1 1000 1000 58 Apr  7 16:38 script.py

```

### `bubble-sandbox exec-command`

Execute a command line (no shell wrapper) in a sandboxed environment.

```bash
$ uv run bubble-sandbox execute -w /tmp/bar/ -e bare -- ls -laF

─────────────────────────── Running command: ls -laF ───────────────────────────

total 12
drwxrwxr-x 2 1000 1000 4096 Apr  7 16:38 ./
drwx------ 4 1000 1000   80 Apr  7 18:11 ../
-rw-rw-r-- 1 1000 1000    4 Apr  7 16:38 baz.txt
-rw-rw-r-- 1 1000 1000   58 Apr  7 16:38 script.py

```

**Note:** the `--` above prevents the CLI from interpreting the `-laf` as
one of its own arguments.


## Configuration

Settings are read from environment variables with the `BUBBLE_SANDBOX_`
prefix:

| Variable                                   | Default        | Description                                            |
|--------------------------------------------|----------------|--------------------------------------------------------|
| `BUBBLE_SANDBOX_ENVIRONMENTS_PATHNAME`     | `environments` | Path to the environments directory                     |
| `BUBBLE_SANDBOX_EXECUTION_TIMEOUT_SECONDS` | `30`           | Max wall-clock time for one execution                  |
| `BUBBLE_SANDBOX_MAX_OUTPUT_CHARS`          | `100000`       | Combined stdout+stderr is truncated past this          |
| `BUBBLE_SANDBOX_ENABLE_NETWORK`            | `false`        | Allow network access from the sandbox (see below)      |
| `BUBBLE_SANDBOX_CONFIG_FILE_PATH`          | *(unset)*      | Anchors `environments_pathname` to this file's dir     |

The same keys can be given in a YAML file passed with `-c/--config`. Note
that `-c` *replaces* environment-variable loading rather than layering over
it, so a config file must spell out every non-default setting it wants.

### Network access

Network access is **off by default**: the sandbox is created with
`--unshare-net` and has no network at all. To turn it on globally:

```bash
export BUBBLE_SANDBOX_ENABLE_NETWORK=true
```

or in a config file:

```yaml
enable_network: true
```

Every exec command also takes `--network` / `--no-network`, which overrides
the configured default for that one run:

```bash
uv run bubble-sandbox execute-python -e my-env --network \
  -s 'import requests; print(requests.get("https://example.com").status_code)'
```

Enabling the network additionally bind-mounts a small read-only set of host
`/etc` paths into the sandbox — `resolv.conf`, `hosts`, `nsswitch.conf`,
`host.conf`, `gai.conf`, and the CA trust stores. Nothing under `/etc` is
mounted otherwise, and without those files a networked sandbox could only
reach IP literals: name resolution and TLS verification would both fail.

Two caveats worth knowing before enabling it:

- The sandbox shares the **host's** network namespace, so it can reach
  everything the host can, including loopback services and anything on the
  local network. There is no egress filtering here; if you need one, put
  the sandbox behind a network namespace or firewall you control.
- Sandboxed code is generally untrusted, and network access is what turns
  a data-exfiltration bug into data exfiltration. Prefer leaving it off and
  enabling it per-run with `--network`.

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

Note: an environment provides the *libraries*, not network access — the two
are configured separately. Network access is disabled by default, so the
script above fails unless the sandbox is also run with `--network` or with
`enable_network` set. See [Network access](#network-access).

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
- **Network isolation** (`--unshare-net`): no network access (loopback only). This is the default and can be lifted per run or globally — see [Network access](#network-access)
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
