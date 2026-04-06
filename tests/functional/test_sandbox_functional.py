from bubble_sandbox import models as bs_models
from bubble_sandbox import sandbox as bs_sandbox


async def test_bwrapsandboxcommand_execute_script_wo_workdir(
    tmp_path,
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
