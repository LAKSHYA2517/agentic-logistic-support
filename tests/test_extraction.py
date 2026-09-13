import json

import httpx
import pytest

from app.intelligence.exceptions import (
    ExtractionAuthenticationError,
    ExtractionInvalidRequestError,
    ExtractionInvalidResponseError,
    ExtractionNetworkError,
    ExtractionProviderError,
    ExtractionRateLimitError,
    ExtractionTimeoutError,
)
from app.intelligence.extraction import GroqQwenExtractor
from app.intelligence.models import LogisticsExtraction


def groq_response(fields: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": json.dumps(fields)}}
            ]
        },
    )


def make_extractor(handler, **kwargs) -> GroqQwenExtractor:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return GroqQwenExtractor(
        api_key="test-key",
        http_client=client,
        backoff_base_seconds=0,
        **kwargs,
    )


async def test_complete_hinglish_transcript():
    def handler(request: httpx.Request) -> httpx.Response:
        return groq_response(
            {
                "party_name": "Ramesh",
                "truck_number": "RJ14GB1122",
                "advance_paid": None,
                "balance_due": None,
            }
        )

    extractor = make_extractor(handler)

    result = await extractor.extract("Ramesh ko truck RJ14GB1122 bhejna hai")

    assert isinstance(result, LogisticsExtraction)
    assert result.party_name == "Ramesh"
    assert result.truck_number == "RJ14GB1122"
    assert result.advance_paid is None
    assert result.balance_due is None


async def test_hindi_transcript():
    def handler(request: httpx.Request) -> httpx.Response:
        return groq_response(
            {
                "party_name": "सुरेश",
                "truck_number": None,
                "advance_paid": None,
                "balance_due": None,
            }
        )

    extractor = make_extractor(handler)

    result = await extractor.extract("सुरेश को माल भेजना है")

    assert result.party_name == "सुरेश"


async def test_english_transcript():
    def handler(request: httpx.Request) -> httpx.Response:
        return groq_response(
            {
                "party_name": "John",
                "truck_number": "MH12AB1234",
                "advance_paid": 5000,
                "balance_due": 15000,
            }
        )

    extractor = make_extractor(handler)

    result = await extractor.extract(
        "Send the truck MH12AB1234 to John, advance 5000, balance 15000"
    )

    assert result.party_name == "John"
    assert result.truck_number == "MH12AB1234"
    assert result.advance_paid == 5000
    assert result.balance_due == 15000


async def test_all_fields_missing_returns_all_null():
    def handler(request: httpx.Request) -> httpx.Response:
        return groq_response(
            {
                "party_name": None,
                "truck_number": None,
                "advance_paid": None,
                "balance_due": None,
            }
        )

    extractor = make_extractor(handler)

    result = await extractor.extract("truck is on the way")

    assert result == LogisticsExtraction()


async def test_spoken_money_converted_to_integer():
    def handler(request: httpx.Request) -> httpx.Response:
        return groq_response(
            {
                "party_name": None,
                "truck_number": None,
                "advance_paid": 10000,
                "balance_due": None,
            }
        )

    extractor = make_extractor(handler)

    result = await extractor.extract("advance das hazaar diya")

    assert result.advance_paid == 10000


async def test_ambiguous_hedged_amount_stays_null():
    # The provider is expected to preserve uncertainty; this test only
    # verifies that the extractor faithfully passes through whatever the
    # provider decided (null here), rather than the extractor itself
    # inventing a value.
    def handler(request: httpx.Request) -> httpx.Response:
        return groq_response(
            {
                "party_name": None,
                "truck_number": None,
                "advance_paid": None,
                "balance_due": None,
            }
        )

    extractor = make_extractor(handler)

    result = await extractor.extract("shayad das hazaar advance diya tha")

    assert result.advance_paid is None


async def test_truck_number_extracted():
    def handler(request: httpx.Request) -> httpx.Response:
        return groq_response(
            {
                "party_name": None,
                "truck_number": "RJ14GB1122",
                "advance_paid": None,
                "balance_due": None,
            }
        )

    extractor = make_extractor(handler)

    result = await extractor.extract("truck number RJ14GB1122 confirmed")

    assert result.truck_number == "RJ14GB1122"


async def test_malformed_json_content_raises_invalid_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not valid json"}}]},
        )

    extractor = make_extractor(handler)

    with pytest.raises(ExtractionInvalidResponseError):
        await extractor.extract("some transcript")


async def test_response_violating_schema_raises_invalid_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return groq_response({"party_name": 12345, "truck_number": None})

    extractor = make_extractor(handler)

    with pytest.raises(ExtractionInvalidResponseError):
        await extractor.extract("some transcript")


async def test_response_missing_choices_raises_invalid_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    extractor = make_extractor(handler)

    with pytest.raises(ExtractionInvalidResponseError):
        await extractor.extract("some transcript")


async def test_400_raises_invalid_request_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    extractor = make_extractor(handler)

    with pytest.raises(ExtractionInvalidRequestError):
        await extractor.extract("some transcript")


async def test_401_raises_authentication_error_without_retry():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, text="invalid api key")

    extractor = make_extractor(handler, max_retries=3)

    with pytest.raises(ExtractionAuthenticationError):
        await extractor.extract("some transcript")

    assert call_count == 1


async def test_403_raises_authentication_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    extractor = make_extractor(handler)

    with pytest.raises(ExtractionAuthenticationError):
        await extractor.extract("some transcript")


async def test_429_retries_then_raises_rate_limit_error():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(429, text="rate limited")

    extractor = make_extractor(handler, max_retries=2)

    with pytest.raises(ExtractionRateLimitError):
        await extractor.extract("some transcript")

    assert call_count == 3


async def test_429_then_success_returns_result():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            return httpx.Response(429, text="rate limited")
        return groq_response(
            {
                "party_name": None,
                "truck_number": None,
                "advance_paid": None,
                "balance_due": None,
            }
        )

    extractor = make_extractor(handler, max_retries=3)

    result = await extractor.extract("some transcript")

    assert result == LogisticsExtraction()
    assert call_count == 2


async def test_5xx_retries_then_raises_provider_error():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(503, text="service unavailable")

    extractor = make_extractor(handler, max_retries=2)

    with pytest.raises(ExtractionProviderError):
        await extractor.extract("some transcript")

    assert call_count == 3


async def test_timeout_retries_then_raises():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("timed out", request=request)

    extractor = make_extractor(handler, max_retries=1)

    with pytest.raises(ExtractionTimeoutError):
        await extractor.extract("some transcript")

    assert call_count == 2


async def test_network_error_retries_then_raises():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connection refused", request=request)

    extractor = make_extractor(handler, max_retries=1)

    with pytest.raises(ExtractionNetworkError):
        await extractor.extract("some transcript")

    assert call_count == 2


async def test_request_uses_strict_json_schema_and_bearer_auth():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.read())
        return groq_response(
            {
                "party_name": None,
                "truck_number": None,
                "advance_paid": None,
                "balance_due": None,
            }
        )

    extractor = make_extractor(handler)

    await extractor.extract("some transcript")

    assert captured["headers"]["authorization"] == "Bearer test-key"
    body = captured["body"]
    assert body["response_format"]["type"] == "json_schema"
    schema = body["response_format"]["json_schema"]["schema"]
    assert set(schema["properties"]) == {
        "party_name",
        "truck_number",
        "destination",
        "advance_paid",
        "balance_due",
    }
    assert schema["additionalProperties"] is False
    assert body["messages"][-1]["content"] == "some transcript"


async def test_missing_api_key_raises_configuration_error(monkeypatch):
    from app.intelligence.exceptions import ExtractionConfigurationError

    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(ExtractionConfigurationError):
        GroqQwenExtractor()
