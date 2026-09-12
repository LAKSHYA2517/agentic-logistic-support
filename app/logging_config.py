"""Minimal application logging configuration."""

import logging
from typing import Any
from urllib.parse import urlsplit


class RedactAccessLogQueryFilter(logging.Filter):
    """Remove query strings from Uvicorn access-log request targets."""

    def filter(self, record: logging.LogRecord) -> bool:
        args: Any = record.args
        if record.name == "uvicorn.access" and isinstance(args, tuple) and len(args) >= 3:
            sanitized_args = list(args)
            sanitized_args[2] = urlsplit(str(args[2])).path
            record.args = tuple(sanitized_args)
        return True


def configure_logging(level: str) -> None:
    """Configure concise logs and suppress URLs from HTTP client INFO logs."""

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("app").setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, RedactAccessLogQueryFilter) for item in access_logger.filters):
        access_logger.addFilter(RedactAccessLogQueryFilter())
