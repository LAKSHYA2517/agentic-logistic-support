import logging

from app.logging_config import RedactAccessLogQueryFilter


def test_uvicorn_access_log_query_string_is_removed() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:12345",
            "GET",
            "/meta-webhook?hub.verify_token=do-not-log-me&hub.challenge=123",
            "1.1",
            200,
        ),
        exc_info=None,
    )

    RedactAccessLogQueryFilter().filter(record)

    assert record.getMessage() == '127.0.0.1:12345 - "GET /meta-webhook HTTP/1.1" 200'
    assert "do-not-log-me" not in record.getMessage()
