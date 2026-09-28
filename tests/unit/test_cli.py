import pytest

from bubble_sandbox import cli as bs_cli
from bubble_sandbox import models as bs_models


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
