import pydantic
import pytest

from bubble_sandbox import models as bs_models


def test_executeresult_rejects_unknown_field():
    with pytest.raises(pydantic.ValidationError, match="foo"):
        bs_models.ExecuteResult(foo="hello", exit_code=0)


def test_executeresult_model_validate_rejects_unknown_field():
    with pytest.raises(pydantic.ValidationError, match="foo"):
        bs_models.ExecuteResult.model_validate_json(
            '{"foo": "x", "exit_code": -1}'
        )
