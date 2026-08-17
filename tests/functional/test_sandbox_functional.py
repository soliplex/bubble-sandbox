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
    assert found.output.startswith("/sandbox/work")
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
    assert found.output.startswith("/sandbox/work")
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
    assert found.output == "X" * 10
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
    assert found.output.splitlines() == [
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
    assert found.output.splitlines() == [
        ".",
        "..",
        "venv",
        "work",
    ]
    assert not found.truncated


async def test_bwrapsandboxcommand_execute_wo_network(
    sandbox_config,
    bare_environment,
):
    """Without the network there is no route to anything, even a literal"""
    script = "\n".join(
        [
            "import socket",
            "try:",
            "    socket.create_connection(('1.1.1.1', 53), timeout=5)",
            "except OSError as exc:",
            "    print(f'FAILED: {type(exc).__name__}')",
            "else:",
            "    print('CONNECTED')",
        ]
    )

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_python(script=script)

    assert found.exit_code == 0
    assert found.output.startswith("FAILED:")


async def test_bwrapsandboxcommand_execute_w_network_mounts_resolver(
    sandbox_config,
    bare_environment,
):
    """With the network enabled, the resolver config is visible

    Asserts on the mounts rather than on reaching a remote host, so the
    test does not depend on egress from wherever it runs.
    """
    script = "\n".join(
        [
            "import pathlib",
            "for name in ('/etc/resolv.conf', '/etc/hosts'):",
            "    print(name, pathlib.Path(name).is_file())",
        ]
    )

    sandbox = bs_sandbox.BwrapSandbox(
        default_environment="bare",
        config=sandbox_config,
    )

    found = await sandbox.execute_python(script=script, network=True)

    assert found.exit_code == 0
    assert found.output.splitlines() == [
        "/etc/resolv.conf True",
        "/etc/hosts True",
    ]
