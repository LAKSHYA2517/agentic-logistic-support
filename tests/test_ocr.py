import httpx
import pytest

from app.intelligence.exceptions import OcrConfigurationError
from app.intelligence.models import OCRQuality, OCRResult
from app.intelligence.ocr import PROVIDER_NAME, IndicOCRProvider, evaluate_ocr_quality


@pytest.fixture
def image_file(tmp_path):
    path = tmp_path / "pod.jpg"
    path.write_bytes(b"\xff\xd8\xff fake jpeg bytes")
    return str(path)


def make_provider(handler, **kwargs) -> IndicOCRProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return IndicOCRProvider(
        api_url="https://indicocr.example.internal/ocr",
        api_key="test-key",
        http_client=client,
        backoff_base_seconds=0,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Adapter: success cases across languages
# ---------------------------------------------------------------------------


async def test_successful_extraction_english(image_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "Ramesh Logistics Pvt Ltd\nTruck RJ14GB1122"})

    result = await make_provider(handler).extract_text(image_file)

    assert isinstance(result, OCRResult)
    assert result.success is True
    assert result.provider == PROVIDER_NAME
    assert "RJ14GB1122" in result.text


async def test_successful_extraction_hindi(image_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "प्राप्तकर्ता: रमेश\nदिनांक: 12/09/2026"})

    result = await make_provider(handler).extract_text(image_file)

    assert result.success is True
    assert "रमेश" in result.text


async def test_successful_extraction_hinglish(image_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "Truck RJ14GB1122 delivery Delhi mein hui"})

    result = await make_provider(handler).extract_text(image_file)

    assert result.success is True
    assert "Delhi" in result.text


async def test_confidence_passed_through_when_provided(image_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "some text", "confidence": 0.92})

    result = await make_provider(handler).extract_text(image_file)

    assert result.confidence == 0.92


async def test_confidence_none_when_not_provided(image_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "some text"})

    result = await make_provider(handler).extract_text(image_file)

    assert result.confidence is None


async def test_confidence_never_fabricated_when_field_is_wrong_type(image_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "some text", "confidence": "high"})

    result = await make_provider(handler).extract_text(image_file)

    assert result.confidence is None


# ---------------------------------------------------------------------------
# Adapter: failures are returned as data, never raised
# ---------------------------------------------------------------------------


async def test_empty_text_response_is_represented_as_success_with_empty_text(image_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": ""})

    result = await make_provider(handler).extract_text(image_file)

    assert result.success is True
    assert result.text == ""


async def test_malformed_json_returns_failed_result_not_exception(image_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    result = await make_provider(handler).extract_text(image_file)

    assert result.success is False
    assert "error" in result.metadata


async def test_missing_text_field_returns_failed_result(image_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    result = await make_provider(handler).extract_text(image_file)

    assert result.success is False


async def test_400_returns_failed_result_without_retry(image_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(400, text="bad request")

    result = await make_provider(handler, max_retries=3).extract_text(image_file)

    assert result.success is False
    assert call_count == 1


async def test_401_returns_failed_result_without_retry(image_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, text="invalid api key")

    result = await make_provider(handler, max_retries=3).extract_text(image_file)

    assert result.success is False
    assert call_count == 1


async def test_403_returns_failed_result(image_file):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    result = await make_provider(handler).extract_text(image_file)

    assert result.success is False


async def test_429_retries_then_returns_failed_result(image_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(429, text="rate limited")

    result = await make_provider(handler, max_retries=2).extract_text(image_file)

    assert result.success is False
    assert call_count == 3


async def test_429_then_success_returns_successful_result(image_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={"text": "recovered text"})

    result = await make_provider(handler, max_retries=3).extract_text(image_file)

    assert result.success is True
    assert result.text == "recovered text"
    assert call_count == 2


async def test_5xx_retries_then_returns_failed_result(image_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(503, text="service unavailable")

    result = await make_provider(handler, max_retries=2).extract_text(image_file)

    assert result.success is False
    assert call_count == 3


async def test_timeout_retries_then_returns_failed_result(image_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("timed out", request=request)

    result = await make_provider(handler, max_retries=1).extract_text(image_file)

    assert result.success is False
    assert call_count == 2


async def test_network_error_retries_then_returns_failed_result(image_file):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connection refused", request=request)

    result = await make_provider(handler, max_retries=1).extract_text(image_file)

    assert result.success is False
    assert call_count == 2


async def test_missing_file_returns_failed_result(tmp_path):
    provider = make_provider(lambda request: httpx.Response(200, json={"text": "unused"}))

    result = await provider.extract_text(str(tmp_path / "does_not_exist.jpg"))

    assert result.success is False
    assert "error" in result.metadata


# ---------------------------------------------------------------------------
# Adapter: configuration / request shape
# ---------------------------------------------------------------------------


async def test_missing_api_url_raises_configuration_error(monkeypatch):
    monkeypatch.delenv("INDICOCR_API_URL", raising=False)

    with pytest.raises(OcrConfigurationError):
        IndicOCRProvider()


async def test_api_key_included_when_provided(image_file):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        return httpx.Response(200, json={"text": "ok"})

    await make_provider(handler).extract_text(image_file)

    assert captured["headers"]["authorization"] == "Bearer test-key"


async def test_api_key_omitted_when_not_configured(image_file):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        return httpx.Response(200, json={"text": "ok"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    provider = IndicOCRProvider(
        api_url="https://indicocr.example.internal/ocr",
        api_key=None,
        http_client=client,
        backoff_base_seconds=0,
    )

    await provider.extract_text(image_file)

    assert "authorization" not in captured["headers"]


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------


def test_quality_gate_good_english_logistics_text():
    result = OCRResult(
        text="Ramesh Logistics Pvt Ltd\nTruck RJ14GB1122\nDelivered",
        provider=PROVIDER_NAME,
        success=True,
    )

    assert evaluate_ocr_quality(result) == OCRQuality.GOOD


def test_quality_gate_good_hindi_text():
    result = OCRResult(
        text="प्राप्तकर्ता रमेश दिनांक 12/09/2026",
        provider=PROVIDER_NAME,
        success=True,
    )

    assert evaluate_ocr_quality(result) == OCRQuality.GOOD


def test_quality_gate_good_hinglish_text():
    result = OCRResult(
        text="Truck RJ14GB1122 ka delivery challan Delhi mein",
        provider=PROVIDER_NAME,
        success=True,
    )

    assert evaluate_ocr_quality(result) == OCRQuality.GOOD


def test_quality_gate_good_tamil_text():
    result = OCRResult(text="வணக்கம் ராமேஷ் லாரி எண் 1122", provider=PROVIDER_NAME, success=True)

    assert evaluate_ocr_quality(result) == OCRQuality.GOOD


def test_quality_gate_good_telugu_text():
    result = OCRResult(text="నమస్కారం రమేష్ లారీ సంఖ్య 1122", provider=PROVIDER_NAME, success=True)

    assert evaluate_ocr_quality(result) == OCRQuality.GOOD


def test_quality_gate_good_bengali_text():
    result = OCRResult(text="নমস্কার রমেশ ট্রাক নম্বর 1122", provider=PROVIDER_NAME, success=True)

    assert evaluate_ocr_quality(result) == OCRQuality.GOOD


def test_quality_gate_good_urdu_text():
    result = OCRResult(text="خوش آمدید رمیش ٹرک نمبر 1122", provider=PROVIDER_NAME, success=True)

    assert evaluate_ocr_quality(result) == OCRQuality.GOOD


def test_quality_gate_poor_symbol_noise():
    result = OCRResult(text="@@@ ### ^^^", provider=PROVIDER_NAME, success=True)

    assert evaluate_ocr_quality(result) == OCRQuality.POOR


def test_quality_gate_failed_empty_text():
    result = OCRResult(text="", provider=PROVIDER_NAME, success=True)

    assert evaluate_ocr_quality(result) == OCRQuality.FAILED


def test_quality_gate_failed_whitespace_only():
    result = OCRResult(text="   \n\t  ", provider=PROVIDER_NAME, success=True)

    assert evaluate_ocr_quality(result) == OCRQuality.FAILED


def test_quality_gate_failed_when_success_is_false_regardless_of_text():
    result = OCRResult(
        text="this text should be ignored",
        provider=PROVIDER_NAME,
        success=False,
        metadata={"error": "network failure"},
    )

    assert evaluate_ocr_quality(result) == OCRQuality.FAILED


def test_quality_gate_ignores_confidence_score():
    # A high self-reported confidence must not override a text-based POOR verdict.
    result = OCRResult(
        text="###", provider=PROVIDER_NAME, success=True, confidence=0.99
    )

    assert evaluate_ocr_quality(result) == OCRQuality.POOR


def test_quality_gate_poor_mostly_noise_with_a_little_text():
    result = OCRResult(text="RJ ##### @@@@@ ^^^^^", provider=PROVIDER_NAME, success=True)

    assert evaluate_ocr_quality(result) == OCRQuality.POOR


def test_quality_gate_good_truck_number_and_indian_names():
    result = OCRResult(
        text="Suresh Transport Co, Vehicle No RJ14GB1122, Jaipur to Delhi",
        provider=PROVIDER_NAME,
        success=True,
    )

    assert evaluate_ocr_quality(result) == OCRQuality.GOOD
