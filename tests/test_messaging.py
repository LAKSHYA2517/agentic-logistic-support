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
