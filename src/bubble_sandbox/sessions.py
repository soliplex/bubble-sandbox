import asyncio
import datetime
import logging
import pathlib
import shutil
import uuid

from bubble_sandbox import config as bs_config
from bubble_sandbox import models as bs_models

logger = logging.getLogger(__name__)


class SessionIdConflict(ValueError):
    def __init__(self, session_id):
        self.session_id = session_id
        super().__init__(
            f"Session {session_id!r} already exists with"
            f" different configuration"
        )


class PersistentSessionsDisabled(ValueError):
    def __init__(self):
        super().__init__(
            "Persistent sessions are disabled; "
            "'clear_data=False' is not allowed"
        )


class MaxSessionCount(RuntimeError):
    def __init__(self, max_session_count):
        self.max_session_count = max_session_count
        super().__init__(
            f"Maximum number of sessions ({max_session_count}) reached"
        )


class SessionState:
    def __init__(
        self,
        session_id: str,
        environment: str,
        workdir: pathlib.Path,
        created_at: datetime.datetime,
        volumes: bs_models.VolumeMap | None = None,
    ) -> None:
        self.session_id = session_id
        self.environment = environment
        self.workdir = workdir
        self.created_at = created_at
        self.last_activity = created_at
        self.volumes: bs_models.VolumeMap = volumes or {}

    def touch(self) -> None:
        self.last_activity = datetime.datetime.now(datetime.UTC)

    def idle_seconds(self) -> float:
        now = datetime.datetime.now(datetime.UTC)
        return (now - self.last_activity).total_seconds()

    def to_info(self) -> bs_models.SessionInfo:
        return bs_models.SessionInfo(
            session_id=self.session_id,
            environment=self.environment,
            created_at=self.created_at.isoformat(),
            last_activity=self.last_activity.isoformat(),
            volumes=self.volumes,
        )


class SessionStore:
    def __init__(self, config: bs_config.Config) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._settings = config
        self._cleanup_task: asyncio.Task[None] | None = None

    def create(
        self,
        environment: str,
        session_id: str | None = None,
        volumes: dict[str, str] | None = None,
    ) -> tuple[SessionState, bool]:
        effective_volumes = volumes or {}

        if session_id is not None and session_id in self._sessions:
            existing = self._sessions[session_id]
            if (
                existing.environment == environment
                and existing.volumes == effective_volumes
            ):
                logger.info(
                    "Session already exists, returning existing",
                    extra={"session_id": session_id},
                )
                return existing, False
            raise SessionIdConflict(session_id)

        if len(self._sessions) >= self._settings.max_session_count:
            raise MaxSessionCount(self._settings.max_session_count)

        if session_id is None:
            session_id = uuid.uuid4().hex[:16]

        workdir = self._settings.workspace_path / "sessions" / session_id
        workdir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Session directory created",
            extra={
                "session_id": session_id,
                "path": str(workdir),
            },
        )

        for disk_name in effective_volumes:
            vol_dir = self._settings.workspace_path / "volumes" / disk_name
            vol_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Volume directory created",
                extra={
                    "session_id": session_id,
                    "volume": disk_name,
                    "path": str(vol_dir),
                },
            )

        now = datetime.datetime.now(datetime.UTC)
        session = SessionState(
            session_id=session_id,
            environment=environment,
            workdir=workdir,
            created_at=now,
            volumes=effective_volumes,
        )
        self._sessions[session_id] = session
        logger.info(
            "Session created",
            extra={
                "session_id": session_id,
                "environment": environment,
            },
        )
        return session, True

    def get(self, session_id: str) -> SessionState | None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.touch()
        return session

    def list_sessions(self) -> list[SessionState]:
        return list(self._sessions.values())

    def _check_persistence_policy(
        self,
        clear_data: bool,
    ) -> None:
        if not self._settings.allow_persistent_sessions and not clear_data:
            raise PersistentSessionsDisabled()

    def destroy(
        self,
        session_id: str,
        clear_data: bool = True,
    ) -> bool:
        self._check_persistence_policy(clear_data)

        session = self._sessions.pop(session_id, None)
        found = session is not None

        if clear_data:
            session_dir = (
                self._settings.workspace_path / "sessions" / session_id
            )
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
                logger.info(
                    "Session directory deleted",
                    extra={
                        "session_id": session_id,
                        "path": str(session_dir),
                    },
                )
                found = True

        if found:
            logger.info(
                "Session destroyed",
                extra={
                    "session_id": session_id,
                    "clear_data": clear_data,
                },
            )
        return found

    def cleanup_idle(
        self,
        max_idle: int | None = None,
        clear_data: bool = True,
    ) -> list[str]:
        self._check_persistence_policy(clear_data)

        effective_max = (
            max_idle
            if max_idle is not None
            else self._settings.session_idle_timeout_seconds
        )
        to_remove: list[str] = []
        for sid, session in self._sessions.items():
            if session.idle_seconds() > effective_max:
                to_remove.append(sid)

        for sid in to_remove:
            self.destroy(sid, clear_data=clear_data)

        logger.info(
            "Idle cleanup completed",
            extra={
                "removed_count": len(to_remove),
                "session_ids": to_remove,
            },
        )
        return to_remove

    def shutdown(
        self,
        clear_data: bool = True,
    ) -> list[str]:
        self._check_persistence_policy(clear_data)

        session_ids = list(self._sessions.keys())
        self.stop_cleanup_loop()
        for sid in session_ids:
            self.destroy(sid, clear_data=clear_data)

        logger.info(
            "All sessions shut down",
            extra={"removed_count": len(session_ids)},
        )
        return session_ids

    def destroy_all(self) -> int:
        count = len(self._sessions)
        for sid in list(self._sessions):
            self.destroy(sid)
        return count

    async def start_cleanup_loop(
        self,
        interval: int = 300,
    ) -> None:
        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval)
                self.cleanup_idle()

        self._cleanup_task = asyncio.create_task(_loop())

    def stop_cleanup_loop(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            self._cleanup_task = None
