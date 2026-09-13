from types import SimpleNamespace

import pytest

from app.intelligence.exceptions import OcrConfigurationError
from app.intelligence.models import OCRQuality, OCRResult
from app.intelligence.ocr import (
    PADDLE_PROVIDER_NAME,
    PROVIDER_NAME,
    PaddleOcrProvider,
    SarvamVisionProvider,
    evaluate_ocr_quality,
)


@pytest.fixture
def image_file(tmp_path):
    path = tmp_path / "pod.jpg"
    path.write_bytes(b"\xff\xd8\xff fake jpeg bytes")
    return str(path)


class FakeDocAI:
    def __init__(
        self,
        *,
        initial_status="pending",
        statuses=None,
        pages=None,
        digitise_error: Exception | None = None,
        job_id="vision-job-1",
    ):
        self.initial_status = initial_status
        self.statuses = list(statuses or ["completed"])
        self.pages = pages if pages is not None else ["Delivery challan", "Truck RJ14GB1122"]
        self.digitise_error = digitise_error
        self.job_id = job_id
        self.digitise_kwargs = None
        self.status_calls = 0
        self.results_calls = 0

    async def digitise(self, **kwargs):
        self.digitise_kwargs = kwargs
        if self.digitise_error is not None:
            raise self.digitise_error
        return SimpleNamespace(job_id=self.job_id, status=self.initial_status)

    async def get_status(self, job_id):
        assert job_id == self.job_id
        self.status_calls += 1
        status = self.statuses.pop(0) if self.statuses else "completed"
        return SimpleNamespace(status=status)

    async def get_results(self, job_id):
        assert job_id == self.job_id
        self.results_calls += 1
        pages = [SimpleNamespace(content=content) for content in self.pages]
        return SimpleNamespace(documents=[SimpleNamespace(pages=pages)])


class FakeClient:
    def __init__(self, doc_ai: FakeDocAI):
        self.doc_ai = doc_ai


def make_provider(doc_ai: FakeDocAI, **kwargs) -> SarvamVisionProvider:
    return SarvamVisionProvider(
        client=FakeClient(doc_ai),
        language="hi-IN",
        output_format="md",
        content_type="mixed",
        poll_interval_seconds=0,
        max_wait_seconds=1,
        **kwargs,
    )


class FakePaddleEngine:
    def __init__(self, pages=None, error: Exception | None = None):
        self.pages = pages if pages is not None else []
        self.error = error
        self.inputs: list[str] = []

    def predict(self, file_path: str):
        self.inputs.append(file_path)
        if self.error is not None:
            raise self.error
        return self.pages


async def test_paddle_ocr_extracts_lines_and_average_confidence(image_file):
    engine = FakePaddleEngine(
        pages=[
            {
                "res": {
                    "rec_texts": ["Vehicle No. RJ14GB1122", "Destination Delhi"],
                    "rec_scores": [0.98, 0.94],
                }
            }
        ]
    )

    result = await PaddleOcrProvider(engine=engine).extract_text(image_file)

    assert result.text == "Vehicle No. RJ14GB1122\nDestination Delhi"
    assert result.provider == PADDLE_PROVIDER_NAME
    assert result.confidence == pytest.approx(0.96)
    assert result.success is True
    assert result.metadata == {"pages": 1, "lines": 2}
    assert engine.inputs == [image_file]


async def test_paddle_ocr_empty_output_is_a_safe_failure(image_file):
    result = await PaddleOcrProvider(engine=FakePaddleEngine()).extract_text(image_file)

    assert result.success is False
    assert result.provider == PADDLE_PROVIDER_NAME
    assert "no document text" in result.metadata["error"]


async def test_paddle_ocr_error_is_sanitized(image_file):
    result = await PaddleOcrProvider(
        engine=FakePaddleEngine(
            error=RuntimeError("failed at https://private.example/pod with Bearer secret")
        )
    ).extract_text(image_file)

    assert result.success is False
    assert "https://" not in result.metadata["error"]
    assert "Bearer secret" not in result.metadata["error"]


async def test_successful_extraction_and_request_shape(image_file):
    doc_ai = FakeDocAI()

    result = await make_provider(doc_ai).extract_text(image_file)

    assert result == OCRResult(
        text="Delivery challan\n\nTruck RJ14GB1122",
        provider=PROVIDER_NAME,
        confidence=None,
        success=True,
        metadata={
            "job_id": "vision-job-1",
            "status": "completed",
            "pages": 2,
            "language": "hi-IN",
            "output_format": "md",
        },
    )
    assert doc_ai.digitise_kwargs["language"] == "hi-IN"
    assert doc_ai.digitise_kwargs["output_format"] == "md"
    assert doc_ai.digitise_kwargs["content_type"] == "mixed"
    assert doc_ai.digitise_kwargs["model"] == "sarvam-vision"
    filename, data, media_type = doc_ai.digitise_kwargs["file"][0]
    assert filename == "pod.jpg"
    assert data.startswith(b"\xff\xd8\xff")
    assert media_type == "image/jpeg"
    assert doc_ai.status_calls == 1
    assert doc_ai.results_calls == 1


async def test_polling_continues_until_completed(image_file):
    doc_ai = FakeDocAI(statuses=["running", "pending", "completed"])

    result = await make_provider(doc_ai).extract_text(image_file)

    assert result.success is True
    assert doc_ai.status_calls == 3


async def test_partially_completed_job_is_accepted(image_file):
    doc_ai = FakeDocAI(initial_status="partially_completed", pages=["Readable page"])

    result = await make_provider(doc_ai).extract_text(image_file)

    assert result.success is True
    assert result.metadata["status"] == "partially_completed"
    assert doc_ai.status_calls == 0


@pytest.mark.parametrize("status", ["failed", "rejected"])
async def test_terminal_failure_is_returned_as_data(image_file, status):
    result = await make_provider(FakeDocAI(initial_status=status)).extract_text(image_file)

    assert result.success is False
    assert status in result.metadata["error"]


async def test_missing_file_returns_failed_result(tmp_path):
    result = await make_provider(FakeDocAI()).extract_text(str(tmp_path / "missing.jpg"))

    assert result.success is False
    assert "not found" in result.metadata["error"]


async def test_unsupported_file_type_returns_failed_result(tmp_path):
    path = tmp_path / "pod.txt"
    path.write_text("not a supported document")

    result = await make_provider(FakeDocAI()).extract_text(str(path))

    assert result.success is False
    assert "unsupported" in result.metadata["error"]


async def test_invalid_job_response_returns_failed_result(image_file):
    result = await make_provider(FakeDocAI(job_id="")).extract_text(image_file)

    assert result.success is False
    assert "invalid job response" in result.metadata["error"]


async def test_invalid_status_response_returns_failed_result(image_file):
    doc_ai = FakeDocAI(statuses=[None])

    result = await make_provider(doc_ai).extract_text(image_file)

    assert result.success is False
    assert "invalid status response" in result.metadata["error"]


async def test_empty_results_return_failed_result(image_file):
    result = await make_provider(FakeDocAI(initial_status="completed", pages=[])).extract_text(
        image_file
    )

    assert result.success is False
    assert "no document text" in result.metadata["error"]


async def test_polling_timeout_returns_failed_result(image_file):
    provider = SarvamVisionProvider(
        client=FakeClient(FakeDocAI(statuses=["running"])),
        poll_interval_seconds=0,
        max_wait_seconds=0,
    )

    result = await provider.extract_text(image_file)

    assert result.success is False
    assert "timed out" in result.metadata["error"]


async def test_provider_error_is_sanitized(image_file, monkeypatch):
    secret = "sarvam-secret-value"
    monkeypatch.setenv("SARVAM_API_KEY", secret)
    error = RuntimeError(
        f"Bearer {secret} failed at https://api.sarvam.ai/doc-ai/v1"
    )

    result = await make_provider(FakeDocAI(digitise_error=error)).extract_text(image_file)

    message = result.metadata["error"]
    assert result.success is False
    assert secret not in message
    assert "https://" not in message
    assert "<redacted>" in message


def test_missing_api_key_raises_configuration_error(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)

    with pytest.raises(OcrConfigurationError):
        SarvamVisionProvider()


@pytest.mark.parametrize(
    "text",
    [
        "Ramesh Logistics Pvt Ltd Truck RJ14GB1122 Delivered",
        "प्राप्तकर्ता रमेश दिनांक 12/09/2026",
        "Truck RJ14GB1122 ka delivery challan Delhi mein",
        "வணக்கம் ராமேஷ் லாரி எண் 1122",
        "నమస్కారం రమేష్ లారీ సంఖ్య 1122",
        "নমস্কার রমেশ ট্রাক নম্বর 1122",
        "خوش آمدید رمیش ٹرک نمبر 1122",
    ],
)
def test_quality_gate_accepts_meaningful_multilingual_text(text):
    result = OCRResult(text=text, provider=PROVIDER_NAME, success=True)

    assert evaluate_ocr_quality(result) == OCRQuality.GOOD


@pytest.mark.parametrize("text", ["@@@ ### ^^^", "RJ ##### @@@@@ ^^^^^", "###"])
def test_quality_gate_marks_symbol_noise_poor(text):
    result = OCRResult(text=text, provider=PROVIDER_NAME, success=True, confidence=0.99)

    assert evaluate_ocr_quality(result) == OCRQuality.POOR


@pytest.mark.parametrize("text", ["", "   \n\t  "])
def test_quality_gate_marks_empty_text_failed(text):
    result = OCRResult(text=text, provider=PROVIDER_NAME, success=True)

    assert evaluate_ocr_quality(result) == OCRQuality.FAILED


def test_quality_gate_marks_provider_failure_failed():
    result = OCRResult(
        text="text is ignored",
        provider=PROVIDER_NAME,
        success=False,
        metadata={"error": "provider failure"},
    )

    assert evaluate_ocr_quality(result) == OCRQuality.FAILED
