import json
from unittest import mock

import pytest
import typer.testing

from bubble_sandbox import cli as bs_cli
from bubble_sandbox import models as bs_models
from bubble_sandbox import sandbox as bs_sandbox


@pytest.mark.parametrize(
    "w_kwargs, exp_status, exp_code",
    [
        ({"stdout": "hi\n", "exit_code": 0}, None, 0),
        ({"stderr": "oops\n", "exit_code": 3}, "Exited with code: 3", 3),
        (
            {"timed_out": True, "timeout_seconds": 30.0},
            "Timed out after 30 seconds",
            124,
        ),
        ({"exit_code": -9}, "Terminated by signal 9", 137),
        ({"exit_code": -15}, "Terminated by signal 15", 143),
    ],
)
def test_response_reporting(w_kwargs, exp_status, exp_code):
    response = bs_models.ExecuteResult(**w_kwargs)

    assert bs_cli.response_status_line(response) == exp_status
    assert bs_cli.response_exit_code(response) == exp_code


@pytest.mark.parametrize(
    "w_args, w_side_effect, exp_code, exp_output",
    [
        ([], None, 0, "Sandbox available\n"),
        (
            [],
            bs_sandbox.BwrapNotFound(),
            1,
            "Sandbox unavailable: 'bwrap' not found on PATH\n",
        ),
        (
            ["-a"],
            None,
            0,
            {"available": True, "reason": None},
        ),
        (
            ["-a"],
            bs_sandbox.ProbeFailed(1, "bwrap: [denied]\n"),
            1,
            {
                "available": False,
                "reason": (
                    "Sandbox unavailable: probe failed: "
                    "exit code 1: bwrap: [denied]"
                ),
            },
        ),
    ],
)
@mock.patch("bubble_sandbox.sandbox.check_available")
def test_check(check_available, w_args, w_side_effect, exp_code, exp_output):
    check_available.side_effect = w_side_effect
    runner = typer.testing.CliRunner()

    result = runner.invoke(bs_cli.the_cli, ["check", *w_args])

    assert result.exit_code == exp_code
    if isinstance(exp_output, dict):
        assert json.loads(result.output) == exp_output
    else:
        assert result.output == exp_output
    check_available.assert_called_once_with(network=False)


@mock.patch("bubble_sandbox.sandbox.check_available")
def test_check_w_network(check_available):
    runner = typer.testing.CliRunner()

    result = runner.invoke(bs_cli.the_cli, ["check", "--network"])

    assert result.exit_code == 0
    check_available.assert_called_once_with(network=True)
