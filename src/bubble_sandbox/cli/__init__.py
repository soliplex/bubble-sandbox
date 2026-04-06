import pathlib
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
    pretty_exceptions_show_locals=False,
)

the_console = console.Console()


settings_path_option: pathlib.Path = typer.Option(
    None,
    "--settings",
    help="Settings file",
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
