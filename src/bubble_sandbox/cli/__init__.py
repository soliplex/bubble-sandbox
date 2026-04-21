import asyncio
import importlib.metadata
import pathlib
import typing

import rich.console
import typer
import yaml

from bubble_sandbox import config as bs_config
from bubble_sandbox import models as bs_models
from bubble_sandbox import sandbox as bs_sandbox

the_cli = typer.Typer(
    context_settings={
        "help_option_names": ["-h", "--help"],
    },
    no_args_is_help=True,
    add_completion=False,
    # pretty_exceptions_show_locals=False,
)

the_console = rich.console.Console()

config_file_option: pathlib.Path = typer.Option(
    None,
    "-c",
    "--config",
    help="Config file",
)
script_option: str = typer.Option(
    None,
    "-s",
    "--script",
    help="Script as string",
)
script_file_option: pathlib.Path = typer.Option(
    None,
    "-f",
    "--script-file",
    help="Script as filename",
)
environment_name_option: str = typer.Option(
    None,
    "-e",
    "--environment",
    help="Environment name",
)
workdir_option: pathlib.Path = typer.Option(
    None,
    "-w",
    "--workdir",
    help="Directory in which to run the script (mounted read-write)",
)
exec_command_args = typing.Annotated[
    list[str],
    typer.Argument(
        help="Arguments to 'exec-command'",
    ),
]
volume_option: list[str] = typer.Option(
    (),
    "-v",
    "--volume",
    help=(
        "Volume info, formatted as a comma-separated string: "
        "'volume_name,host_path,writable' (repeatable)"
    ),
)


def extract_volume_map(volumes: list[str]) -> bs_models.VolumeMap:
    result = {}

    for volume in volumes:
        name, host_path, *flags = volume.split(",")
        writable = "rw" in flags
        result[name] = bs_models.VolumeInfo(
            host_path=host_path,
            writable=writable,
        )

    return result


def version_callback(value: bool):
    if value:
        v = importlib.metadata.version("bubble_sandbox")
        the_console.print(f"Installed bubble_sandbox version: {v}")
        raise typer.Exit()


@the_cli.callback()
def app(
    _version: bool = typer.Option(
        False,
        "-v",
        "--version",
        callback=version_callback,
        help="Show version and exit",
    ),
):
    """bubble-sandbox CLI"""


def get_the_config(config_file: pathlib.Path | None) -> bs_config.Config:
    if config_file is not None:
        with open(config_file) as f:
            config_dict = yaml.safe_load(f)

        return bs_config.Config.model_validate(config_dict)
    else:
        return bs_config.get_config()


@the_cli.command(
    "list-environments",
)
def list_environments(
    ctx: typer.Context,
    config_file: pathlib.Path = config_file_option,
):
    """List environments defined in the given path"""
    the_console.line()
    the_console.rule("Available environments")
    the_console.line()

    the_config = get_the_config(config_file)
    for env_info in the_config.list_environments():
        the_console.rule(env_info.name)

        if env_info.description:
            the_console.print(env_info.description)

        the_console.line()
        if env_info.dependencies:
            the_console.print("Dependencies:")
            for dep in env_info.dependencies:
                the_console.print(f"- {dep}")
        else:
            the_console.print("No dependencies")

        the_console.line()


def make_sandbox(
    config_file: pathlib.Path | None,
    environment_name: str | None,
    volumes: list[str],
):
    the_config = get_the_config(config_file)

    return bs_sandbox.BwrapSandbox(
        default_environment_name=environment_name or "bare",
        config=the_config,
        volumes=extract_volume_map(volumes),
    )


@the_cli.command(
    "exec-script",
)
def exec_script(
    ctx: typer.Context,
    config_file: pathlib.Path = config_file_option,
    script: str | None = script_option,
    script_file: pathlib.Path | None = script_file_option,
    environment_name: str = environment_name_option,
    workdir: pathlib.Path | None = workdir_option,
    volumes: list[str] = volume_option,
):
    """Run a script / script file in a given environment"""
    the_sandbox = make_sandbox(
        config_file=config_file,
        environment_name=environment_name,
        volumes=volumes,
    )

    if script is not None:
        str_or_file = f"'{script}'"
    elif script_file is not None:
        str_or_file = f"@{script_file}"
        script = script_file.read_text()

    the_console.line()
    the_console.rule(f"Running script: {str_or_file}")
    the_console.line()

    if workdir is not None:
        response = asyncio.run(
            the_sandbox.execute_script(
                script=script,
                workdir=workdir,
            )
        )
    else:
        response = asyncio.run(
            the_sandbox.execute_script(
                script=script,
            )
        )

    if response.exit_code:
        print(f"Exited with code: {response.exit_code}")

    print(response.output)

    if response.truncated:
        print("<truncated>")


@the_cli.command(
    "execute",
)
def execute(
    ctx: typer.Context,
    command: list[str],
    config_file: pathlib.Path = config_file_option,
    environment_name: str = environment_name_option,
    workdir: pathlib.Path | None = workdir_option,
    volumes: list[str] = volume_option,
):
    """Run a command line in a given environment"""
    the_sandbox = make_sandbox(
        config_file=config_file,
        environment_name=environment_name,
        volumes=volumes,
    )

    the_console.line()
    the_console.rule(f"Running command: {' '.join(command)}")
    the_console.line()

    if workdir is not None:
        response = asyncio.run(
            the_sandbox.execute(
                command=command,
                workdir=workdir,
            )
        )
    else:
        response = asyncio.run(
            the_sandbox.execute(
                command=command,
            )
        )

    if response.exit_code:
        print(f"Exited with code: {response.exit_code}")

    print(response.output)

    if response.truncated:
        print("<truncated>")


@the_cli.command(
    "exec-command",
)
def exec_command(
    ctx: typer.Context,
    command: str,
    config_file: pathlib.Path = config_file_option,
    environment_name: str = environment_name_option,
    workdir: pathlib.Path | None = workdir_option,
    volumes: list[str] = volume_option,
):
    """Run a shell command in a given environment"""
    the_sandbox = make_sandbox(
        config_file=config_file,
        environment_name=environment_name,
        volumes=volumes,
    )

    the_console.line()
    the_console.rule(f"Running shell command: {command}")
    the_console.line()

    command = ["sh", "-c", command]

    if workdir is not None:
        response = asyncio.run(
            the_sandbox.execute(
                command=command,
                workdir=workdir,
            )
        )
    else:
        response = asyncio.run(
            the_sandbox.execute(
                command=command,
            )
        )

    if response.exit_code:
        print(f"Exited with code: {response.exit_code}")

    print(response.output)

    if response.truncated:
        print("<truncated>")
