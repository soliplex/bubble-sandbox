# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development commands

```bash
# Sync the main project's dependencies.
uv sync

# Per-environment venvs must be built separately — they are excluded from
# the uv workspace (see `[tool.uv.workspace]` in pyproject.toml). Without
# them the sandbox has no Python to mount at /sandbox/venv.
#
# Use a *system* Python (not one from a venv), since the venv in each
# environment ends up bind-mounted read-only into the sandbox.
cd environments/bare       && uv sync --python=/usr/bin/python3.13 && cd ../..
cd environments/pandas-only && uv sync --python=/usr/bin/python3.13 && cd ../..

# Tests. Only `tests/unit` runs by default (see pyproject `testpaths`);
# `tests/functional` exercises a real `bwrap` subprocess and must be
# requested explicitly.
uv run pytest
uv run pytest tests/functional          # functional tests; needs bubblewrap
uv run pytest tests/unit/test_sandbox.py::test_name  # single test

# Lint / format (ruff is the only linter; config in pyproject).
uv run ruff check
uv run ruff format --check
```

100% branch coverage is enforced (`--cov-fail-under=100`) on `bubble_sandbox` and `tests` themselves; `src/bubble_sandbox/cli/*.py` is omitted from coverage per `[tool.coverage.run]`, so CLI code is not required to be covered but everything else is. A failing coverage check fails the test run.

The `bubble-sandbox` CLI entry point is installed by `uv sync` as `bubble-sandbox` (see `[project.scripts]`); invoke it via `uv run bubble-sandbox ...`.

## Architecture

This package is a thin Python driver around [`bubblewrap`](https://github.com/containers/bubblewrap) (`bwrap`). It does **not** implement sandboxing itself — it builds a `bwrap` argv and runs it as an async subprocess. `bwrap` must be installed on the host and available on PATH.

### Sandbox argv is composed in layers

`src/bubble_sandbox/sandbox.py` builds the `bwrap` command by concatenating four independent helpers, in order:

1. `core_sandbox_args()` — always-on flags: read-only binds of `/usr`, `/lib`, `/lib64` (if present), and `sys.base_prefix` (when not `/usr`); `/bin` and `/sbin` symlinks; fresh `/proc`, `/dev`, tmpfs `/tmp`; `--unshare-user`, `--unshare-pid`, `--unshare-net` (unless `network=True`), `--new-session`, `--die-with-parent`.
2. `venv_sandbox_args(env_name, config)` — resolves `environments/<env_name>/.venv` and bind-mounts it read-only at `/sandbox/venv`; sets `PATH=/sandbox/venv/bin:/usr/bin:/bin`.
3. `workdir_sandbox_args(workdir)` — if a host workdir is given, bind-mounts it **read-write** at `/sandbox/work` and `--chdir`s into it. `execute_script` allocates a `TemporaryDirectory` workdir when none is provided and writes `script.py` into it.
4. `volumes_sandbox_args(volume_map)` — for each `VolumeInfo`: bind-mount at `/sandbox/volumes/<name>` (rw or ro based on `writable`), or create an empty dir when `host_path` is `None`.

`BwrapSandbox.execute` runs the resulting argv via `asyncio.create_subprocess_exec`, enforces `config.execution_timeout_seconds` with `asyncio.wait_for` (returns `exit_code=-1` on timeout), decodes stdout+stderr, and truncates to `config.max_output_chars`. `execute_script` is just a wrapper that writes the script to the workdir and invokes `/sandbox/venv/bin/python /sandbox/work/script.py`.

### Environments are separate uv projects

Each directory under `environments/` is its own `pyproject.toml` project with its own `.venv`. `bare` has no deps (stdlib only); `pandas-only` adds pandas. At runtime the selected env's `.venv` is the *only* Python visible inside the sandbox — so the set of importable third-party packages is exactly that env's dependency closure. Adding a new environment means creating `environments/<name>/pyproject.toml` and running `uv sync` inside that directory (with a non-venv Python); the name must not contain `/`, `\`, or `..` (validated by `Config.resolve_venv_path`).

`Config.list_environments()` discovers environments by globbing `environments/*` for dirs that contain both `.venv/` and `pyproject.toml`, reading the project name/description/deps from the toml.

### Config

`Config` is a `pydantic_settings.BaseSettings` with prefix `BUBBLE_SANDBOX_` (e.g. `BUBBLE_SANDBOX_EXECUTION_TIMEOUT_SECONDS`). `get_config()` is `@functools.lru_cache`d — tests that need a fresh `Config` should construct one directly rather than calling `get_config()`. The CLI's `-c/--config` flag loads a YAML file and constructs `Config` from it, bypassing env-var loading; when set, `environments_path` is resolved relative to the config file's directory rather than CWD.

### CLI

`src/bubble_sandbox/cli/__init__.py` is a Typer app with four commands: `list-environments`, `exec-script` (script string or file), `execute` (argv, no shell), `exec-command` (wraps argv in `sh -c`). `-a/--agent-mode` switches from Rich-decorated output to machine-parseable form (JSON for `list-environments`, raw stdout for the exec commands) — when adding new CLI output, honor this flag so agent callers get clean output.

### Tests

- `tests/conftest.py` provides `sandbox_config` (a `Config` with a tmp `config_file_path`) and `bare_environment` (copies the real `environments/bare` into the tmp path). The `bare_environment` fixture depends on `environments/bare/.venv` already existing on disk.
- `tests/unit/` — default; must preserve 100% branch coverage.
- `tests/functional/` — skipped by `testpaths`. These actually shell out to `bwrap` and need bubblewrap + the prebuilt `bare` venv.
