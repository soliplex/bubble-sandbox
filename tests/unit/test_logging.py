import copy
import json
import logging

import pytest

from bubble_sandbox import logging as bs_logging
from bubble_sandbox import settings as bs_settings

LOGGER_NAME = "test"
LOG_RECORD_LEVEL = logging.INFO
LOG_RECORD_PATHNAME = ""
LOG_RECORD_LINENO = 0
LOG_RECORD_MSG = "hello"
LOG_RECORD_ARGS = ()


@pytest.fixture
def log_record():
    return logging.LogRecord(
        name=LOGGER_NAME,
        level=LOG_RECORD_LEVEL,
        pathname=LOG_RECORD_PATHNAME,
        lineno=LOG_RECORD_LINENO,
        msg=LOG_RECORD_MSG,
        args=LOG_RECORD_ARGS,
        exc_info=None,
    )


def test_jsonlogger_basic_format(log_record):
    formatter = bs_logging.JsonFormatter()

    output = json.loads(formatter.format(log_record))

    assert output["name"] == LOGGER_NAME
    assert output["level"] == logging.getLevelName(LOG_RECORD_LEVEL)
    assert output["message"] == LOG_RECORD_MSG
    assert "timestamp" in output


def test_jsonlogger_extra_fields(log_record):
    log_record.session_id = "abc"

    formatter = bs_logging.JsonFormatter()

    output = json.loads(formatter.format(log_record))

    assert output["session_id"] == "abc"


def test_jsonlogger_exception_formatting(log_record):
    import sys

    try:
        raise ValueError("boom")  # noqa TRY301
    except ValueError:
        exc_info = sys.exc_info()

    log_record.exc_info = exc_info

    formatter = bs_logging.JsonFormatter()

    output = json.loads(formatter.format(log_record))

    assert "exception" in output
    assert "boom" in output["exception"]


def test_configure_audit_logging():
    settings = bs_settings.Settings()

    root_logger = logging.root

    def _root_settings():
        return copy.deepcopy(
            {
                key: value
                for key, value in root_logger.__dict__.items()
                if key != "handlers"
            }
        )

    before_handlers = set(root_logger.handlers)
    before_settings = _root_settings()

    bs_logging.configure_audit_logging(settings)

    # Check that we made no changes to root logger.
    after_handlers = set(root_logger.handlers)
    after_settings = _root_settings()

    assert after_handlers == before_handlers
    assert after_settings == before_settings

    audit = logging.getLogger(bs_logging.AUDIT_LOGGER_NAME)

    assert audit.level == logging.INFO
    assert audit.propagate is False
    assert len(audit.handlers) >= 1
    assert isinstance(
        audit.handlers[0].formatter,
        bs_logging.JsonFormatter,
    )
