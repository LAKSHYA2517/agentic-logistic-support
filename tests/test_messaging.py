import httpx
import pytest

from app.services.messaging import MetaMessagingError, MetaMessagingService


def make_service(handler, **kwargs) -> MetaMessagingService:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return MetaMessagingService(
        access_token="test-access-token",
        graph_api_base_url="https://graph.test",
        graph_api_version="v25.0",
        phone_number_id="test-phone-number-id",
        http_client=client,
        **kwargs,
    )


def test_send_text_message_uses_correct_url_headers_and_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body"] = request.read()
        return httpx.Response(200, json={"messages": [{"id": "wamid.sent"}]})

    service = make_service(handler)
    service.send_text_message(to="15551234567", body="New shipment assigned.")

    assert captured["url"] == "https://graph.test/v25.0/test-phone-number-id/messages"
    assert captured["headers"]["authorization"] == "Bearer test-access-token"
    import json

    body = json.loads(captured["body"])
    assert body == {
        "messaging_product": "whatsapp",
        "to": "15551234567",
        "type": "text",
        "text": {"body": "New shipment assigned."},
    }


def test_send_text_message_missing_access_token_raises_without_request():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    service = MetaMessagingService(
        access_token=None,
        graph_api_base_url="https://graph.test",
        graph_api_version="v25.0",
        phone_number_id="test-phone-number-id",
        http_client=client,
    )

    with pytest.raises(MetaMessagingError):
        service.send_text_message(to="15551234567", body="hi")

    assert call_count == 0


def test_send_text_message_missing_phone_number_id_raises_without_request():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    service = MetaMessagingService(
        access_token="test-access-token",
        graph_api_base_url="https://graph.test",
        graph_api_version="v25.0",
        phone_number_id=None,
        http_client=client,
    )

    with pytest.raises(MetaMessagingError):
        service.send_text_message(to="15551234567", body="hi")

    assert call_count == 0


def test_send_text_message_http_error_raises_sanitized_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "message": (
                        "Invalid OAuth access token for test-access-token. "
                        "See https://example.test/error?token=secret"
                    ),
                    "type": "OAuthException",
                    "code": 190,
                }
            },
        )

    service = make_service(handler)

    with pytest.raises(MetaMessagingError) as exc_info:
        service.send_text_message(to="15551234567", body="hi")

    message = str(exc_info.value)
    assert "test-access-token" not in message
    assert "https://example.test" not in message
    assert "code=190" in message


def test_send_text_message_network_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("mock connection failed", request=request)

    service = make_service(handler)

    with pytest.raises(MetaMessagingError):
        service.send_text_message(to="15551234567", body="hi")


# ---------------------------------------------------------------------------
# Development visibility: status code, response body, message ID, errors
# ---------------------------------------------------------------------------


def test_send_text_message_returns_whatsapp_message_id_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": [{"id": "wamid.HBgL123"}]})

    service = make_service(handler)

    message_id = service.send_text_message(to="15551234567", body="hi")

    assert message_id == "wamid.HBgL123"


def test_send_text_message_returns_none_when_response_has_no_message_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    service = make_service(handler)

    assert service.send_text_message(to="15551234567", body="hi") is None


def test_successful_send_logs_status_body_and_message_id_without_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": [{"id": "wamid.HBgL123"}]})

    service = make_service(handler)
    caplog.set_level("INFO")

    service.send_text_message(to="919317708038", body="hi")

    assert "meta_outbound_message_accepted" in caplog.text
    assert "status=200" in caplog.text
    assert "wamid.HBgL123" in caplog.text
    assert "test-access-token" not in caplog.text


def test_failed_send_logs_status_body_and_error_code_without_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "message": "Invalid OAuth access token test-access-token",
                    "type": "OAuthException",
                    "code": 190,
                }
            },
        )

    service = make_service(handler)
    caplog.set_level("ERROR")

    with pytest.raises(MetaMessagingError) as exc_info:
        service.send_text_message(to="919317708038", body="hi")

    assert "meta_outbound_message_rejected" in caplog.text
    assert "status=401" in caplog.text
    assert '"code":190' in caplog.text
    assert "test-access-token" not in caplog.text
    assert "code=190" in str(exc_info.value)


def test_recipient_without_country_code_logs_warning_but_still_sends(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": [{"id": "wamid.sent"}]})

    service = make_service(handler)
    caplog.set_level("WARNING")

    service.send_text_message(to="9317708038", body="hi")

    assert "meta_outbound_recipient_format_suspect" in caplog.text
    assert "looks_like_missing_country_code" in caplog.text


def test_recipient_with_country_code_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": [{"id": "wamid.sent"}]})

    service = make_service(handler)
    caplog.set_level("WARNING")

    service.send_text_message(to="919317708038", body="hi")

    assert "meta_outbound_recipient_format_suspect" not in caplog.text
