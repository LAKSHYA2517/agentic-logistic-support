import pytest

from app.intelligence.models import OCRResult
from app.intelligence.ocr import PROVIDER_NAME
from app.intelligence.perception import extract_document_text


@pytest.fixture
def image_file(tmp_path):
    path = tmp_path / "pod.jpg"
    path.write_bytes(b"\xff\xd8\xff fake jpeg bytes")
    return str(path)


def make_fake_ocr(result: OCRResult, call_counter: list[int] | None = None):
    class _Fake:
        async def extract_text(self, file_path: str) -> OCRResult:
            if call_counter is not None:
                call_counter[0] += 1
            return result

    return _Fake()


GOOD_RESULT = OCRResult(
    text="Ramesh Logistics Pvt Ltd\nTruck RJ14GB1122\nDelivered",
    provider=PROVIDER_NAME,
    success=True,
)
POOR_RESULT = OCRResult(text="@@@ ### ^^^", provider=PROVIDER_NAME, success=True)
FAILED_RESULT = OCRResult(
    text="", provider=PROVIDER_NAME, success=False, metadata={"error": "network failure"}
)
VISION_RESULT = OCRResult(
    text="Ramesh Logistics Pvt Ltd\nTruck RJ14GB1122\nDelivered",
    provider="sarvam_vision",
    success=True,
)


# ---------------------------------------------------------------------------
# GOOD primary OCR -> vision never called
# ---------------------------------------------------------------------------


async def test_good_ocr_returns_primary_result_without_calling_vision(image_file):
    vision_calls: list[int] = [0]

    result = await extract_document_text(
        image_file,
        ocr_provider=make_fake_ocr(GOOD_RESULT),
        vision_provider=make_fake_ocr(VISION_RESULT, call_counter=vision_calls),
    )

    assert result.provider == PROVIDER_NAME
    assert result.text == GOOD_RESULT.text
    assert vision_calls[0] == 0
    assert result.metadata["quality"] == "GOOD"
    assert result.metadata["fallback_used"] is False


async def test_good_ocr_with_no_vision_provider_configured(image_file):
    result = await extract_document_text(image_file, ocr_provider=make_fake_ocr(GOOD_RESULT))

    assert result.provider == PROVIDER_NAME
    assert result.metadata["fallback_used"] is False


# ---------------------------------------------------------------------------
# POOR / FAILED primary OCR -> vision called
# ---------------------------------------------------------------------------


async def test_poor_ocr_triggers_vision_fallback(image_file):
    ocr_calls: list[int] = [0]
    vision_calls: list[int] = [0]

    result = await extract_document_text(
        image_file,
        ocr_provider=make_fake_ocr(POOR_RESULT, call_counter=ocr_calls),
        vision_provider=make_fake_ocr(VISION_RESULT, call_counter=vision_calls),
    )

    assert ocr_calls[0] == 1
    assert vision_calls[0] == 1
    assert result.provider == "sarvam_vision"
    assert result.metadata["fallback_used"] is True
    assert result.metadata["primary_quality"] == "POOR"


async def test_failed_ocr_triggers_vision_fallback(image_file):
    vision_calls: list[int] = [0]

    result = await extract_document_text(
        image_file,
        ocr_provider=make_fake_ocr(FAILED_RESULT),
        vision_provider=make_fake_ocr(VISION_RESULT, call_counter=vision_calls),
    )

    assert vision_calls[0] == 1
    assert result.provider == "sarvam_vision"
    assert result.metadata["fallback_used"] is True
    assert result.metadata["primary_quality"] == "FAILED"


async def test_poor_ocr_without_vision_provider_returns_primary_as_is(image_file):
    result = await extract_document_text(image_file, ocr_provider=make_fake_ocr(POOR_RESULT))

    assert result.provider == PROVIDER_NAME
    assert result.metadata["fallback_used"] is False
    assert result.metadata["quality"] == "POOR"


async def test_failed_ocr_without_vision_provider_returns_primary_as_is(image_file):
    result = await extract_document_text(image_file, ocr_provider=make_fake_ocr(FAILED_RESULT))

    assert result.provider == PROVIDER_NAME
    assert result.success is False
    assert result.metadata["fallback_used"] is False


# ---------------------------------------------------------------------------
# Both OCR and Vision fail
# ---------------------------------------------------------------------------


async def test_ocr_and_vision_both_fail(image_file):
    vision_failed = OCRResult(
        text="", provider="sarvam_vision", success=False, metadata={"error": "vision outage"}
    )

    result = await extract_document_text(
        image_file,
        ocr_provider=make_fake_ocr(FAILED_RESULT),
        vision_provider=make_fake_ocr(vision_failed),
    )

    assert result.success is False
    assert result.provider == "sarvam_vision"
    assert result.metadata["fallback_used"] is True


# ---------------------------------------------------------------------------
# No duplicate/unnecessary calls
# ---------------------------------------------------------------------------


async def test_good_ocr_calls_ocr_exactly_once_and_vision_never(image_file):
    ocr_calls: list[int] = [0]
    vision_calls: list[int] = [0]

    await extract_document_text(
        image_file,
        ocr_provider=make_fake_ocr(GOOD_RESULT, call_counter=ocr_calls),
        vision_provider=make_fake_ocr(VISION_RESULT, call_counter=vision_calls),
    )

    assert ocr_calls[0] == 1
    assert vision_calls[0] == 0
