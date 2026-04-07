import asyncio
import importlib.metadata
import pathlib

import rich.console
import typer
import yaml

from bubble_sandbox import config as bs_config
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
    root = the_config.environments_path

    for subpath in sorted(root.glob("*")):
        if (subpath / ".venv").is_dir():
            the_console.print(f"- {subpath.name}")

    the_console.print()


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
):
    """Run a script / script file in a given environment"""
    the_config = get_the_config(config_file)

    the_sandbox = bs_sandbox.BwrapSandbox(
        default_environment_name=environment_name,
        config=the_config,
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
