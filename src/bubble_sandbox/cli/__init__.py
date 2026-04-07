import asyncio
import contextlib
import pathlib
import shutil
import tempfile
import typing

import typer
import yaml
from rich import console

from bubble_sandbox import sandbox
from bubble_sandbox import settings


the_cli = typer.Typer(
    context_settings={
        "help_option_names": ["-h", "--help"],
    },
    no_args_is_help=True,
    add_completion=False,
    #pretty_exceptions_show_locals=False,
)

the_console = console.Console()


settings_path_option: pathlib.Path = typer.Option(
    None,
    "--settings",
    help="Settings file",
)


script_option: str = typer.Option(
    None,
    "--script",
    help="Script as string",
)


script_file_option: pathlib.Path = typer.Option(
    None,
    "--script-file",
    help="Script as filename",
)


environment_name_option: str = typer.Option(
    None,
    "--environment",
    help="Environment name",
)


def version_callback(value: bool):
    if value:
        gitmeta = util.GitMetadata(pathlib.Path.cwd())
        v = importlib_metadata.version("bubble_sandbox")
        the_console.print(f"Installed bubble_sandbox version: {v}")


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


def get_the_settings(settings_path: pathlib.Path | None) -> settings.Settings:
    if settings_path is not None:

        with open(settings_path) as f:
            settings_dict = yaml.safe_load(f)

        the_settings = settings.Settings.model_validate(settings_dict)
        return the_settings
    else:
        return settings.get_settings()


@the_cli.command(
    "list-environments",
)
def list_environments(
    ctx: typer.Context,
    settings_path: pathlib.Path = settings_path_option,
):
    """List environments defined in the given path"""
    the_console.line()
    the_console.rule("Available environments")
    the_console.line()

    the_settings = get_the_settings(settings_path)
    root = the_settings.environments_path

    for subpath in sorted(root.glob("*")):
        if (subpath / ".venv").is_dir():
            the_console.print(f"- {subpath.name}")

    the_console.print()


@the_cli.command(
    "exec-script",
)
def exec_script(
    ctx: typer.Context,
    settings_path: pathlib.Path = settings_path_option,
    script: str | None = script_option,
    script_file: pathlib.Path | None = script_file_option,
    environment_name: str = environment_name_option,
):
    """Run a script / script file in a given environment"""
    the_settings = get_the_settings(settings_path)

    the_sandbox = sandbox.BwrapSandbox(
        default_environment_name=environment_name,
        settings=the_settings,
    )
    if script is not None:
        str_or_file = f"'{script}'"
    elif script_file is not None:
        str_or_file = f"@{script_file}"
        script = script_file.read_text()

    the_console.line()
    the_console.rule(f"Running script: {str_or_file}")
    the_console.line()

    response = asyncio.run(the_sandbox.execute_script(script=script))

    if response.exit_code:
        print(f"Exited with code: {response.exit_code}")

    print(response.output)
    if (response.truncated):
        print("<truncated>")
