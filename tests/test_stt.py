import json

import httpx
import pytest

from app.intelligence.exceptions import (
    SttAuthenticationError,
    SttInvalidResponseError,
    SttNetworkError,
    SttProviderError,
    SttRateLimitError,
    SttTimeoutError,
)
from app.intelligence.models import STTResult
from app.intelligence.stt import SARVAM_MODE, SARVAM_MODEL, SarvamSTTAdapter


@pytest.fixture
def audio_file(tmp_path):
    path = tmp_path / "note.ogg"
    path.write_bytes(b"OggS fake audio bytes")
    return str(path)


def make_adapter(handler, **kwargs) -> SarvamSTTAdapter:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return SarvamSTTAdapter(
        api_key="test-key",
        http_client=client,
        backoff_base_seconds=0,
        **kwargs,
    )


async def test_successful_transcription(audio_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transcript": "namaste truck aa gaya", "language_code": "hi-en"})

    adapter = make_adapter(handler)

    result = await adapter.transcribe(audio_file)

    assert isinstance(result, STTResult)
    assert result.transcript == "namaste truck aa gaya"
    assert result.provider == "sarvam"
    assert result.model == SARVAM_MODEL
    assert result.language_code == "hi-en"


async def test_empty_transcript_is_valid(audio_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transcript": ""})

    adapter = make_adapter(handler)

    result = await adapter.transcribe(audio_file)

    assert result.transcript == ""


async def test_invalid_response_missing_transcript_field(audio_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    adapter = make_adapter(handler)

    with pytest.raises(SttInvalidResponseError):
        await adapter.transcribe(audio_file)


async def test_invalid_response_not_json(audio_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    adapter = make_adapter(handler)

    with pytest.raises(SttInvalidResponseError):
        await adapter.transcribe(audio_file)


async def test_401_raises_authentication_error_without_retry(audio_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, text="invalid api key")

    adapter = make_adapter(handler, max_retries=3)

    with pytest.raises(SttAuthenticationError):
        await adapter.transcribe(audio_file)

    assert call_count == 1


async def test_403_raises_authentication_error(audio_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    adapter = make_adapter(handler)

    with pytest.raises(SttAuthenticationError):
        await adapter.transcribe(audio_file)


async def test_429_retries_then_raises_rate_limit_error(audio_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(429, text="rate limited")

    adapter = make_adapter(handler, max_retries=2)

    with pytest.raises(SttRateLimitError):
        await adapter.transcribe(audio_file)

    assert call_count == 3  # initial + 2 retries


async def test_429_then_success_returns_result(audio_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={"transcript": "ok"})

    adapter = make_adapter(handler, max_retries=3)

    result = await adapter.transcribe(audio_file)

    assert result.transcript == "ok"
    assert call_count == 2


async def test_5xx_retries_then_raises_provider_error(audio_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(503, text="service unavailable")

    adapter = make_adapter(handler, max_retries=2)

    with pytest.raises(SttProviderError):
        await adapter.transcribe(audio_file)

    assert call_count == 3


async def test_timeout_retries_then_raises(audio_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("timed out", request=request)

    adapter = make_adapter(handler, max_retries=1)

    with pytest.raises(SttTimeoutError):
        await adapter.transcribe(audio_file)

    assert call_count == 2


async def test_network_error_retries_then_raises(audio_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connection refused", request=request)

    adapter = make_adapter(handler, max_retries=1)

    with pytest.raises(SttNetworkError):
        await adapter.transcribe(audio_file)

    assert call_count == 2


async def test_optional_keyterms_included_in_request(audio_file):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8", errors="ignore")
        captured["body"] = body
        return httpx.Response(200, json={"transcript": "ok"})

    adapter = make_adapter(handler)

    await adapter.transcribe(audio_file, keyterms=["Ashok Leyland", "RJ14GB1122"])

    assert "Ashok Leyland" in captured["body"]
    assert "RJ14GB1122" in captured["body"]


async def test_no_keyterms_omits_field(audio_file):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode("utf-8", errors="ignore")
        return httpx.Response(200, json={"transcript": "ok"})

    adapter = make_adapter(handler)

    await adapter.transcribe(audio_file, keyterms=None)

    assert "keyterms" not in captured["body"]


async def test_correct_multipart_request_shape(audio_file):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["content_type"] = request.headers.get("content-type", "")
        captured["body"] = request.read().decode("utf-8", errors="ignore")
        return httpx.Response(200, json={"transcript": "ok"})

    adapter = make_adapter(handler)

    await adapter.transcribe(audio_file)

    assert captured["headers"]["api-subscription-key"] == "test-key"
    assert "multipart/form-data" in captured["content_type"]
    assert f'name="model"' in captured["body"]
    assert SARVAM_MODEL in captured["body"]
    assert SARVAM_MODE in captured["body"]
    assert 'name="file"' in captured["body"]


async def test_400_raises_invalid_request_error(audio_file):
    from app.intelligence.exceptions import SttInvalidRequestError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    adapter = make_adapter(handler)

    with pytest.raises(SttInvalidRequestError):
        await adapter.transcribe(audio_file)


async def test_missing_api_key_raises_configuration_error(monkeypatch, audio_file):
    from app.intelligence.exceptions import SttConfigurationError

    monkeypatch.delenv("SARVAM_API_KEY", raising=False)

    with pytest.raises(SttConfigurationError):
        SarvamSTTAdapter()
