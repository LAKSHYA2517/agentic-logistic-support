import pytest

import app.intelligence.perception as perception
from app.intelligence.models import OCRResult
from app.intelligence.ocr import PADDLE_PROVIDER_NAME, PROVIDER_NAME
from app.intelligence.perception import extract_document_text


@pytest.fixture
def image_file(tmp_path):
    path = tmp_path / "pod.jpg"
    path.write_bytes(b"\xff\xd8\xff fake jpeg bytes")
    return str(path)


def make_fake_vision(result: OCRResult, call_counter: list[int] | None = None):
    class _Fake:
        async def extract_text(self, file_path: str) -> OCRResult:
            if call_counter is not None:
                call_counter[0] += 1
            return result

    return _Fake()


async def test_sarvam_result_is_annotated_good(image_file):
    calls = [0]
    provider_result = OCRResult(
        text="Ramesh Logistics Pvt Ltd\nTruck RJ14GB1122\nDelivered",
        provider=PROVIDER_NAME,
        success=True,
        metadata={"job_id": "vision-job-1"},
    )

    result = await extract_document_text(
        image_file,
        vision_provider=make_fake_vision(provider_result, calls),
    )

    assert calls == [1]
    assert result.provider == PROVIDER_NAME
    assert result.metadata == {"job_id": "vision-job-1", "quality": "GOOD"}


async def test_poor_sarvam_result_is_annotated_poor(image_file):
    provider_result = OCRResult(text="@@@ ### ^^^", provider=PROVIDER_NAME, success=True)

    result = await extract_document_text(
        image_file, vision_provider=make_fake_vision(provider_result)
    )

    assert result.success is True
    assert result.metadata["quality"] == "POOR"


async def test_failed_sarvam_result_preserves_error_and_is_annotated_failed(image_file):
    provider_result = OCRResult(
        text="",
        provider=PROVIDER_NAME,
        success=False,
        metadata={"error": "vision outage"},
    )

    result = await extract_document_text(
        image_file, vision_provider=make_fake_vision(provider_result)
    )

    assert result.success is False
    assert result.metadata == {"error": "vision outage", "quality": "FAILED"}


async def test_default_document_reader_uses_local_paddle_ocr(image_file, monkeypatch):
    provider_result = OCRResult(
        text="Vehicle RJ14GB1122 Destination Delhi",
        provider=PADDLE_PROVIDER_NAME,
        success=True,
    )
    fake = make_fake_vision(provider_result)
    monkeypatch.setattr(perception, "PaddleOcrProvider", lambda: fake)

    result = await extract_document_text(image_file)

    assert result.provider == PADDLE_PROVIDER_NAME
    assert result.metadata["quality"] == "GOOD"
