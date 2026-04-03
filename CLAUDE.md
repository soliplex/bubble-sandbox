# CLAUDE.md

## Project Overview

exec-server is a FastAPI service that executes Python scripts in isolated
bubblewrap sandboxes. It provides one-shot script execution, stateful sessions
with file management, and multiple configurable Python environments.

## Build and Test Commands

```bash
# Install dependencies
uv sync

# Sync environment venvs (needed for local testing)
cd environments/bare && uv sync && cd ../..
cd environments/pandas-exec && uv sync && cd ../..

# Run unit tests with coverage (100% required)
uv run pytest

# Lint
uv run ruff check

# Format check
uv run ruff format --check

# Run server locally
EXEC_SERVER_API_KEY=dev-key uv run exec-server

# Docker build and run
podman build -t exec-server .
podman run --security-opt seccomp=unconfined -p 8000:8000 \
  -e EXEC_SERVER_API_KEY='my-secret' exec-server
```

## Code Style

- Line length: 79 characters
- Target Python: 3.13
- Ruff rules: F, E, B, U, I, PT
- Force single-line imports (isort)
- Use `uv` for package management, not pip

## Testing

- All tests in `tests/` with 100% branch coverage required
- pytest-asyncio with `auto` mode
- httpx for async API testing
- No functional/integration test split -- all tests are unit tests

## Key Files

- [src/exec_server/main.py](src/exec_server/main.py) - FastAPI app factory, lifespan (logging init, session store), CLI entry point
- [src/exec_server/sandbox.py](src/exec_server/sandbox.py) - Bubblewrap sandbox execution
- [src/exec_server/sessions.py](src/exec_server/sessions.py) - SessionStore: create (optional ID, volumes, idempotent), destroy (clear_data), cleanup_idle, shutdown, list
- [src/exec_server/settings.py](src/exec_server/settings.py) - Pydantic settings (EXEC_SERVER_ prefix)
- [src/exec_server/logging.py](src/exec_server/logging.py) - JsonFormatter, AUDIT logger, configure_logging()
- [src/exec_server/models.py](src/exec_server/models.py) - Request/response models (CreateSessionRequest, CleanupResult, ShutdownResult)
- [src/exec_server/views/](src/exec_server/views/) - API route handlers

## Environment Variables

All use `EXEC_SERVER_` prefix. See [README.md](README.md) for full list.

- `EXEC_SERVER_API_KEY` (required) - Bearer token for authentication
- `EXEC_SERVER_ENVIRONMENTS_DIR` - Path to environments directory
- `EXEC_SERVER_EXECUTION_TIMEOUT_SECONDS` - Max script execution time
- `EXEC_SERVER_SESSION_IDLE_TIMEOUT_SECONDS` - Session idle timeout
- `EXEC_SERVER_MAX_SESSIONS` - Maximum concurrent sessions
- `EXEC_SERVER_WORKSPACE_DIR` - Root for session workspaces and volumes
- `EXEC_SERVER_ALLOW_PERSISTENT_SESSIONS` - Allow clear_data=false on delete
- `EXEC_SERVER_LOG_LEVEL` - Root and AUDIT logger level

## Design Patterns

- Bubblewrap sandboxing with filesystem, network, PID, and user isolation
- Fully async implementation (asyncio)
- Pydantic settings with `@lru_cache` singleton via `get_settings()`
- FastAPI dependency injection for auth, settings, session store
- Environment venvs are read-only bind mounts in the sandbox
- Base64 encoding for file writes to avoid shell escaping issues
- Session workspaces under `workspace_dir/sessions/{id}/`, volumes under
  `workspace_dir/volumes/{name}/` (read-only mount at `/workspace/{mount_point}`)
- Idempotent session creation: same ID + same config = return existing session
- Directory traversal prevention on all file operation paths
- JSON structured logging (JsonFormatter) with AUDIT logger for session ops
- `allow_persistent_sessions` policy controls whether `clear_data=false` is
  permitted on delete, cleanup, and shutdown
