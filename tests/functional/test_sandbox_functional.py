from bubble_sandbox import models as bs_models
from bubble_sandbox import sandbox as bs_sandbox


async def test_bwrapsandboxcommand_execute_script_wo_workdir(
    sandbox_settings,
    bare_environment,
):
    script = r"import sys; print('\n'.join(sys.path))"

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute_script(script=script)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output.startswith("/sandbox/work")
    assert not found.truncated


async def test_bwrapsandboxcommand_execute_script_w_workdir(
    tmp_path,
    sandbox_settings,
    bare_environment,
):
    workdir = tmp_path / "work"
    workdir.mkdir()

    script = r"import sys; print('\n'.join(sys.path))"

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute_script(script=script, workdir=workdir)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output.startswith("/sandbox/work")
    assert not found.truncated


async def test_bwrapsandboxcommand_execute_script_w_truncation(
    sandbox_settings,
    bare_environment,
):
    sandbox_settings.max_output_chars = 10
    script = "print('X' * 50)"

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute_script(script=script)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output == "X" * 10
    assert found.truncated


async def test_bwrapsandboxcommand_execute_command_wo_workdir(
    sandbox_settings,
    bare_environment,
):
    command = ["ls", "-a", "/sandbox"]

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute(command=command)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output.splitlines() == [
        ".",
        "..",
        "venv",
    ]
    assert not found.truncated


async def test_bwrapsandboxcommand_execute_command_w_workdir(
    tmp_path,
    sandbox_settings,
    bare_environment,
):
    workdir = tmp_path / "work"
    workdir.mkdir()

    command = ["ls", "-a", "/sandbox"]

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name="bare",
        settings=sandbox_settings,
    )

    found = await sandbox.execute(command=command, workdir=workdir)

    assert isinstance(found, bs_models.ExecuteResult)
    assert found.output.splitlines() == [
        ".",
        "..",
        "venv",
        "work",
    ]
    assert not found.truncated
