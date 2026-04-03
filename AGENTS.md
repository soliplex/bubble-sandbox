# AGENTS.md

Instructions for AI coding agents working on bubble-sandbox.

## Setup

```bash
uv sync

# Sync environment venvs for local testing
cd environments/bare && uv sync && cd ../..
cd environments/pandas-exec && uv sync && cd ../..
```

## Build and Test

```bash
# Unit tests with 100% branch coverage (must pass before committing)
uv run pytest

# Lint
uv run ruff check

# Format check
uv run ruff format --check
```

## Code Style

- Python 3.13+, line length 79 characters
- Ruff for linting and formatting (rules: F, E, B, U, I, PT)
- Force single-line imports
- All code must pass `ruff check` and `ruff format --check`

## Testing Guidelines

- All tests in `tests/` directory, 100% branch coverage enforced
- Async tests use pytest-asyncio with `auto` mode
- API endpoint tests use httpx `AsyncClient` with `ASGITransport`
- Fixtures in `tests/conftest.py`: `test_settings`, `app`, `auth_headers`,
  `client`
- Test classes follow the naming pattern `TestMethodName`

## Project Structure

- `src/bubble_sandbox/main.py` - CLI entry point (`cli_main`)
- `src/bubble_sandbox/sandbox.py` - Bubblewrap command construction, script and
  command execution in sandboxes, file upload validation
- `src/bubble_sandbox/sessions.py` - SessionStore with creation (ID,
  volumes, idempotency), destruction (`clear_data` flag), idle cleanup, shutdown,
  and max session enforcement
- `src/bubble_sandbox/settings.py` - Pydantic BaseSettings with `EXEC_SERVER_`
  prefix, cached singleton via `get_settings()`

## Key Design Decisions

- Bubblewrap sandboxing with filesystem, network, PID, and user namespace
  isolation
- Fully async (asyncio) for scalability
- Environment venvs are read-only bind mounts in the sandbox
- Sessions use persistent workspace directories under `BUBBLE_SANDBOX_WORKSPACE_DIR`
  (`workspace_data/sessions/{session_id}/`), cleaned up on destroy or idle
  timeout when `clear_data=true`
- Session IDs (alphanumeric, hyphens, underscores) with idempotent
  creation — if a session already exists with the same config, return it
- Volume mounts: `dict[str, str]` mapping disk volume names to mount points,
  stored under `workspace_data/volumes/{disk_name}/`, mounted read-only
  relative to `/workspace` in the sandbox
- Directory traversal prevention on all file operation paths (`../` rejected)
- JSON structured logging to stdout with a dedicated AUDIT logger
  (`exec_server.AUDIT`) that logs every session operation with `session_id`,
  operation, and relevant parameters
- Base64 encoding for file writes to avoid shell escaping issues
- Output truncated at 100,000 characters

## Environment Variables

All use `BUBBLE_SANDBOX_` prefix (Pydantic BaseSettings):

- `BUBBLE_SANDBOX_ENVIRONMENTS_DIR` (default: `environments`) - Path to
  environments
- `BUBBLE_SANDBOX_MAX_UPLOAD_SIZE_BYTES` (default: 10MB) - Max upload size
- `BUBBLE_SANDBOX_ALLOWED_EXTENSIONS` (default: common text formats) - Whitelist
- `BUBBLE_SANDBOX_EXECUTION_TIMEOUT_SECONDS` (default: 30) - Script timeout
- `BUBBLE_SANDBOX_SESSION_IDLE_TIMEOUT_SECONDS` (default: 3600) - Idle cleanup
- `BUBBLE_SANDBOX_MAX_SESSIONS` (default: 50) - Concurrent session limit
- `BUBBLE_SANDBOX_WORKSPACE_DIR` (default: `workspace_data`) - Root directory for
  session workspaces and volume directories
- `BUBBLE_SANDBOX_ALLOW_PERSISTENT_SESSIONS` (default: `true`) - When false,
  `clear_data=false` on delete/cleanup/shutdown is rejected
- `BUBBLE_SANDBOX_LOG_LEVEL` (default: `INFO`) - Root and AUDIT logger level

## Common Tasks

### Adding a New Environment

1. Create directory under `environments/<name>/`
2. Add `pyproject.toml` with dependencies
3. Run `cd environments/<name> && uv sync`
4. Rebuild Docker image

### Modifying Sandbox Isolation

- Bubblewrap flags are constructed in `sandbox.py:_build_bwrap_command()`
- Test changes thoroughly -- sandbox escapes are security-critical
- Session commands use `execute_command_in_sandbox()`
- One-shot scripts use `execute_in_sandbox()`
