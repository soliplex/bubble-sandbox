import datetime
import json
import logging

from bubble_sandbox import config as bs_config

AUDIT_LOGGER_NAME = "bubble_sandbox.AUDIT"


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON object."""

    _BUILTIN_ATTRS = frozenset(
        vars(logging.LogRecord("", 0, "", 0, "", (), None))
    )

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.datetime.fromtimestamp(
            record.created,
            tz=datetime.UTC,
        ).strftime("%Y-%m-%dT%H:%M:%S")

        obj: dict = {
            "timestamp": ts,
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[0] is not None:
            obj["exception"] = self.formatException(record.exc_info)

        for key, val in record.__dict__.items():
            if key not in self._BUILTIN_ATTRS:
                obj[key] = val

        return json.dumps(obj, default=str)


def configure_audit_logging(config: bs_config.Config) -> None:
    """Configure AUDIT logger

    Note that we do *not* mess with the root logger.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    audit = logging.getLogger(AUDIT_LOGGER_NAME)
    audit.setLevel(config.log_level)
    audit.propagate = False
    audit.handlers.clear()
    audit.addHandler(handler)
