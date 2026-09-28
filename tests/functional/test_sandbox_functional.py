from bubble_sandbox import models as bs_models
from bubble_sandbox import sandbox as bs_sandbox


async def test_bwrapsandboxcommand_execute_python_wo_workdir(
    sandbox_config,
    bare_environment,
):
    script = r"import sys; print('\n'.join(sys.path))"

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_python(script=script)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.stdout.startswith("/sandbox/work")
    assert not found.truncated


async def test_bwrapsandboxcommand_execute_python_w_workdir(
    tmp_path,
    sandbox_config,
    bare_environment,
):
    workdir = tmp_path / "work"
    workdir.mkdir()

    script = r"import sys; print('\n'.join(sys.path))"

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_python(script=script, workdir=workdir)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.stdout.startswith("/sandbox/work")
    assert not found.truncated


async def test_bwrapsandboxcommand_execute_python_w_truncation(
    sandbox_config,
    bare_environment,
):
    sandbox_config.max_output_chars = 10
    script = "print('X' * 50)"

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_python(script=script)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.stdout == "X" * 10
    assert found.truncated


async def test_bwrapsandboxcommand_execute_command_wo_workdir(
    sandbox_config,
    bare_environment,
):
    command = ["ls", "-a", "/sandbox"]

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(command=command)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.stdout.splitlines() == [
        ".",
        "..",
        "venv",
    ]
    assert not found.truncated


async def test_bwrapsandboxcommand_execute_command_w_workdir(
    tmp_path,
    sandbox_config,
    bare_environment,
):
    workdir = tmp_path / "work"
    workdir.mkdir()

    command = ["ls", "-a", "/sandbox"]

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute(command=command, workdir=workdir)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.stdout.splitlines() == [
        ".",
        "..",
        "venv",
        "work",
    ]
    assert not found.truncated


async def test_bwrapsandboxcommand_execute_separates_streams(
    sandbox_config,
    bare_environment,
):
    script = (
        "import sys\n"
        "print('the answer')\n"
        "print('a warning', file=sys.stderr)\n"
    )

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_python(script=script)

    assert found.stdout == "the answer\n"
    assert found.stderr == "a warning\n"
    assert found.exit_code == 0
    assert not found.timed_out


async def test_bwrapsandboxcommand_execute_python_w_nested_script_path(
    tmp_path,
    sandbox_config,
    bare_environment,
):
    workdir = tmp_path / "work"
    workdir.mkdir()

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_python(
        script="import sys; print(sys.argv[0])",
        workdir=workdir,
        script_path=".snapshots/run-1/script.py",
    )

    assert found.exit_code == 0
    assert found.stdout == "/sandbox/work/.snapshots/run-1/script.py\n"
    written = workdir / ".snapshots" / "run-1" / "script.py"
    assert written.read_text(encoding="utf-8") == (
        "import sys; print(sys.argv[0])"
    )


async def test_bwrapsandboxcommand_execute_python_w_real_timeout(
    sandbox_config,
    bare_environment,
):
    sandbox_config.execution_timeout_seconds = 0.5

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_python(
        script="import time; time.sleep(30)",
    )

    assert found.timed_out
    assert found.timeout_seconds == 0.5
    assert found.exit_code is None
