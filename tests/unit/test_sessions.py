import datetime
import pathlib
import shutil
from unittest import mock

import pytest

from bubble_sandbox import sessions as bs_sessions
from bubble_sandbox import settings as bs_settings


@pytest.fixture
def store_settings(tmp_path: pathlib.Path) -> bs_settings.Settings:
    environments_path = tmp_path / "environments"
    environments_path.mkdir()
    return bs_settings.Settings(
        environments_path=environments_path,
        max_session_count=3,
        session_idle_timeout_seconds=1,
        workspace_path=tmp_path / "workspace_data",
    )


@pytest.fixture
def mock_mkdir():
    with mock.patch.object(
        pathlib.Path,
        "mkdir",
    ) as m:
        yield m


@pytest.fixture
def mock_rmtree():
    with mock.patch.object(
        shutil,
        "rmtree",
    ) as m:
        yield m


@pytest.fixture
def mock_path_exists():
    with mock.patch.object(
        pathlib.Path,
        "exists",
    ) as m:
        m.return_value = False
        yield m


@pytest.fixture
def store(
    store_settings: bs_settings.Settings,
    mock_mkdir,
    mock_rmtree,
    mock_path_exists,
) -> bs_sessions.SessionStore:
    return bs_sessions.SessionStore(store_settings)


def test_sessionstate_to_info(store):
    session, created = store.create("bare")
    assert created is True

    info = session.to_info()

    assert info.session_id == session.session_id
    assert info.environment == "bare"
    assert info.created_at == session.created_at.isoformat()
    assert info.last_activity == session.last_activity.isoformat()
    assert info.volumes == {}


def test_sessionstate_to_info_with_volumes(store):
    session, _ = store.create(
        "bare",
        volumes={"data": "data"},
    )

    info = session.to_info()

    assert info.volumes == {"data": "data"}


def test_sessionstate_touch_updates_activity(store):
    session, _ = store.create("bare")
    old_activity = session.last_activity

    session.touch()

    assert session.last_activity >= old_activity


def test_sessionstate_idle_seconds(store):
    session, _ = store.create("bare")
    session.last_activity = datetime.datetime.now(
        datetime.UTC,
    ) - datetime.timedelta(seconds=5)

    assert session.idle_seconds() >= 5


def test_sessionstore_create(store, mock_mkdir):
    session, created = store.create("bare")

    assert created is True
    assert isinstance(session, bs_sessions.SessionState)
    assert session.environment == "bare"
    mock_mkdir.assert_called()


def test_sessionstore_create_makes_session_dir(
    store,
    store_settings,
    mock_mkdir,
):
    session, _ = store.create("bare", session_id="abc")

    expected = store_settings.workspace_path / "sessions" / "abc"
    assert session.workdir == expected
    mock_mkdir.assert_any_call(
        parents=True,
        exist_ok=True,
    )


def test_sessionstore_create_with_session_id(store):
    session, created = store.create("bare", session_id="my-session")

    assert created is True
    assert session.session_id == "my-session"
    assert session.workdir.name == "my-session"


def test_sessionstore_create_idempotent(store):
    s1, c1 = store.create("bare", session_id="sess-1", volumes={"vol": "mnt"})
    s2, c2 = store.create("bare", session_id="sess-1", volumes={"vol": "mnt"})

    assert c1 is True
    assert c2 is False

    assert s1 is s2


def test_sessionstore_create_conflict(store):
    store.create("bare", session_id="sess-1")

    with pytest.raises(bs_sessions.SessionIdConflict):
        store.create("other", session_id="sess-1")


def test_sessionstore_create_volume_dirs(
    store_settings,
    store,
    mock_mkdir,
):
    store.create(
        "bare",
        volumes={"shared": "data"},
    )

    # mkdir is called for session dir + volume dir
    mock_mkdir.assert_called_with(
        parents=True,
        exist_ok=True,
    )
    assert mock_mkdir.call_count >= 2


def test_sessionstore_get_existing(store):
    session, _ = store.create("bare")

    found = store.get(session.session_id)

    assert found is session


def test_sessionstore_get_missing(store):
    assert store.get("nonexistent") is None


def test_sessionstore_list_sessions(store):
    store.create("env1")
    store.create("env2")

    sessions = store.list_sessions()

    assert len(sessions) == 2


def test_sessionstore_destroy(store, mock_rmtree):
    session, _ = store.create("bare")

    destroyed = store.destroy(session.session_id)

    assert destroyed
    assert store.get(session.session_id) is None
    mock_rmtree.assert_not_called()


def test_sessionstore_destroy_clear_data_calls_rmtree(
    tmp_path,
    store,
    mock_rmtree,
    mock_path_exists,
):
    mock_path_exists.return_value = True
    session, _ = store.create("bare")

    destroyed = store.destroy(session.session_id, clear_data=True)

    assert destroyed
    mock_rmtree.assert_called_once_with(
        tmp_path / "workspace_data" / "sessions" / session.session_id,
        ignore_errors=True,
    )


def test_sessionstore_destroy_clear_data_false_keeps_dir(
    store,
    mock_rmtree,
):
    session, _ = store.create("bare")

    destroyed = store.destroy(session.session_id, clear_data=False)

    assert destroyed
    mock_rmtree.assert_not_called()


def test_sessionstore_destroy_orphaned_data(
    tmp_path,
    store,
    mock_rmtree,
    mock_path_exists,
):
    mock_path_exists.return_value = True
    destroyed = store.destroy("orphan", clear_data=True)

    assert destroyed
    mock_rmtree.assert_called_once_with(
        tmp_path / "workspace_data" / "sessions" / "orphan",
        ignore_errors=True,
    )


def test_sessionstore_destroy_missing(store):
    destroyed = store.destroy("nonexistent")

    assert not destroyed


def test_sessionstore_destroy_persistence_policy(
    store_settings,
    mock_mkdir,
    mock_rmtree,
    mock_path_exists,
):
    store_settings.allow_persistent_sessions = False
    s = bs_sessions.SessionStore(store_settings)
    s.create("bare", session_id="sess")

    with pytest.raises(bs_sessions.PersistentSessionsDisabled):
        s.destroy("sess", clear_data=False)


def test_sessionstore_max_session_count(store):
    store.create("env1")
    store.create("env2")
    store.create("env3")

    with pytest.raises(bs_sessions.MaxSessionCount):
        store.create("env4")


def test_sessionstore_cleanup_idle(store):
    session, _ = store.create("bare")
    session.last_activity = datetime.datetime.now(
        datetime.UTC,
    ) - datetime.timedelta(seconds=10)

    removed = store.cleanup_idle()

    assert len(removed) == 1
    assert removed[0] == session.session_id
    assert store.get(session.session_id) is None


def test_sessionstore_cleanup_idle_with_max_idle(store):
    session, _ = store.create("bare")
    session.last_activity = datetime.datetime.now(
        datetime.UTC,
    ) - datetime.timedelta(seconds=5)

    removed = store.cleanup_idle(max_idle=100)
    assert len(removed) == 0

    removed = store.cleanup_idle(max_idle=1)
    assert len(removed) == 1


def test_sessionstore_cleanup_idle_keeps_active(store):
    session, _ = store.create("bare")
    session.touch()

    removed = store.cleanup_idle()
    assert len(removed) == 0

    assert store.get(session.session_id) is not None


def test_sessionstore_shutdown(store):
    store.create("env1")
    store.create("env2")

    removed = store.shutdown()

    assert len(removed) == 2
    assert store.list_sessions() == []


def test_sessionstore_shutdown_persistence_policy(
    store_settings,
    mock_mkdir,
    mock_rmtree,
    mock_path_exists,
):
    store_settings.allow_persistent_sessions = False
    s = bs_sessions.SessionStore(store_settings)
    s.create("bare")

    with pytest.raises(bs_sessions.PersistentSessionsDisabled):
        s.shutdown(clear_data=False)


def test_sessionstore_destroy_all(store):
    store.create("env1")
    store.create("env2")

    count = store.destroy_all()

    assert count == 2


async def test_sessionstore_start_and_stop_cleanup_loop(store):
    import asyncio

    await store.start_cleanup_loop(interval=0.01)

    assert store._cleanup_task is not None
    await asyncio.sleep(0.05)

    store.stop_cleanup_loop()

    assert store._cleanup_task is None


def test_sessionstore_stop_cleanup_loop_no_task(store):
    store.stop_cleanup_loop()

    assert store._cleanup_task is None
