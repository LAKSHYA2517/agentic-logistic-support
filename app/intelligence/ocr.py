"""Sarvam Vision document digitisation and deterministic output quality checks."""

from __future__ import annotations

import asyncio
import re
import threading
from numbers import Real
from pathlib import Path
from time import monotonic
from typing import Any, Protocol

from sarvamai import AsyncSarvamAI

from app.config import AppSettings
from app.intelligence.exceptions import OcrConfigurationError
from app.intelligence.http_support import sanitize_provider_message
from app.intelligence.models import OCRQuality, OCRResult


PROVIDER_NAME = "sarvam_vision"
PADDLE_PROVIDER_NAME = "paddleocr"
MODEL_NAME = "sarvam-vision"
TERMINAL_STATUSES = frozenset(
    {"completed", "partially_completed", "failed", "rejected"}
)
SUCCESS_STATUSES = frozenset({"completed", "partially_completed"})
SUPPORTED_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".zip": "application/zip",
}


class VisionProvider(Protocol):
    """Provider contract used by the document perception service."""

    async def extract_text(self, file_path: str) -> OCRResult: ...


# Deterministic quality signal based only on returned text. It covers Latin,
# digits, and scripts used by the 22 scheduled Indian languages.
_MEANINGFUL_CHAR_RE = re.compile(
    r"[A-Za-z0-9"
    r"ऀ-ॿ"
    r"ঀ-৿"
    r"਀-੿"
    r"઀-૿"
    r"଀-୿"
    r"஀-௿"
    r"ఀ-౿"
    r"ಀ-೿"
    r"ഀ-ൿ"
    r"؀-ۿ"
    r"ݐ-ݿ"
    r"ﭐ-﷿"
    r"ﹰ-﻿"
    r"᱐-᱿"
    r"ꯀ-꯿"
    r"]"
)
_MIN_MEANINGFUL_CHARS = 3
_MIN_MEANINGFUL_RATIO = 0.5


def evaluate_ocr_quality(result: OCRResult) -> OCRQuality:
    """Classify provider output without trusting a fabricated confidence score."""

    if not result.success:
        return OCRQuality.FAILED

    text = result.text.strip()
    if not text:
        return OCRQuality.FAILED

    non_space = re.sub(r"\s+", "", text)
    if not non_space:
        return OCRQuality.FAILED

    meaningful_count = len(_MEANINGFUL_CHAR_RE.findall(non_space))
    ratio = meaningful_count / len(non_space)
    if meaningful_count < _MIN_MEANINGFUL_CHARS or ratio < _MIN_MEANINGFUL_RATIO:
        return OCRQuality.POOR
    return OCRQuality.GOOD


_paddle_engine: Any | None = None
_paddle_lock = threading.Lock()


class PaddleOcrProvider:
    """Read POD images locally with one lazily initialized PaddleOCR engine."""

    def __init__(self, *, engine: Any | None = None) -> None:
        self._engine = engine
        self._lock = threading.Lock() if engine is not None else _paddle_lock

    async def extract_text(self, file_path: str) -> OCRResult:
        path = Path(file_path)
        if not path.is_file():
            return self._failure("POD file was not found")
        if path.suffix.lower() not in SUPPORTED_MEDIA_TYPES:
            return self._failure("unsupported POD type; expected PDF, PNG, or JPEG")

        try:
            return await asyncio.to_thread(self._extract_sync, path)
        except Exception as exc:
            detail = sanitize_provider_message(str(exc)) or type(exc).__name__
            return self._failure(f"PaddleOCR failed: {detail}")

    def _extract_sync(self, path: Path) -> OCRResult:
        with self._lock:
            engine = self._engine or _get_paddle_engine()
            pages = list(engine.predict(str(path)))

        texts: list[str] = []
        scores: list[float] = []
        for page in pages:
            page_data = _paddle_page_data(page)
            for text in page_data.get("rec_texts") or []:
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
            for score in page_data.get("rec_scores") or []:
                if isinstance(score, Real) and not isinstance(score, bool):
                    scores.append(float(score))

        if not texts:
            return self._failure("PaddleOCR returned no document text")
        confidence = sum(scores) / len(scores) if scores else None
        return OCRResult(
            text="\n".join(texts),
            provider=PADDLE_PROVIDER_NAME,
            confidence=confidence,
            success=True,
            metadata={"pages": len(pages), "lines": len(texts)},
        )

    @staticmethod
    def _failure(message: str) -> OCRResult:
        return OCRResult(
            text="",
            provider=PADDLE_PROVIDER_NAME,
            confidence=None,
            success=False,
            metadata={"error": message},
        )


def _get_paddle_engine() -> Any:
    global _paddle_engine
    if _paddle_engine is None:
        from paddleocr import PaddleOCR

        _paddle_engine = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            engine="paddle",
        )
    return _paddle_engine


def _paddle_page_data(page: Any) -> dict[str, Any]:
    if isinstance(page, dict):
        return page.get("res", page)
    try:
        data = page.json
    except (AttributeError, TypeError):
        return {}
    if callable(data):
        data = data()
    if not isinstance(data, dict):
        return {}
    return data.get("res", data)


class SarvamVisionProvider:
    """Digitise one document through Sarvam Vision's asynchronous Doc AI API."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        language: str | None = None,
        output_format: str | None = None,
        content_type: str | None = None,
        poll_interval_seconds: float | None = None,
        max_wait_seconds: float | None = None,
        client: Any | None = None,
    ) -> None:
        settings = AppSettings()
        resolved_api_key = api_key or settings.sarvam_api_key
        if client is None and not resolved_api_key:
            raise OcrConfigurationError(
                "SARVAM_API_KEY environment variable is not set"
            )

        self._client = client or AsyncSarvamAI(
            api_subscription_key=resolved_api_key,
            timeout=30.0,
        )
        self._language = language or settings.sarvam_vision_language
        self._output_format = output_format or settings.sarvam_vision_output_format
        self._content_type = content_type or settings.sarvam_vision_content_type
        self._poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else settings.sarvam_vision_poll_interval_seconds
        )
        self._max_wait_seconds = (
            max_wait_seconds
            if max_wait_seconds is not None
            else settings.sarvam_vision_max_wait_seconds
        )

    async def extract_text(self, file_path: str) -> OCRResult:
        """Submit, poll, and collect digitised page text as one ``OCRResult``."""

        path = Path(file_path)
        if not path.is_file():
            return self._failure("document file was not found")

        media_type = SUPPORTED_MEDIA_TYPES.get(path.suffix.lower())
        if media_type is None:
            return self._failure(
                "unsupported document type; expected PDF, PNG, JPEG, or ZIP"
            )

        try:
            file_bytes = await asyncio.to_thread(path.read_bytes)
            job = await self._client.doc_ai.digitise(
                file=[(path.name, file_bytes, media_type)],
                language=self._language,
                output_format=self._output_format,
                content_type=self._content_type,
                model=MODEL_NAME,
            )
            job_id = _value(job, "job_id")
            status = _normalized_status(job)
            if not isinstance(job_id, str) or not job_id or status is None:
                return self._failure("Sarvam Vision returned an invalid job response")

            deadline = monotonic() + self._max_wait_seconds
            while status not in TERMINAL_STATUSES:
                if monotonic() >= deadline:
                    return self._failure("Sarvam Vision processing timed out", job_id)
                await asyncio.sleep(self._poll_interval_seconds)
                status_response = await self._client.doc_ai.get_status(job_id)
                status = _normalized_status(status_response)
                if status is None:
                    return self._failure(
                        "Sarvam Vision returned an invalid status response", job_id
                    )

            if status not in SUCCESS_STATUSES:
                return self._failure(
                    f"Sarvam Vision job ended with status {status}", job_id
                )

            results = await self._client.doc_ai.get_results(job_id)
            text, page_count = _document_text(results)
            if not text:
                return self._failure(
                    "Sarvam Vision returned no document text", job_id
                )
            return OCRResult(
                text=text,
                provider=PROVIDER_NAME,
                confidence=None,
                success=True,
                metadata={
                    "job_id": job_id,
                    "status": status,
                    "pages": page_count,
                    "language": self._language,
                    "output_format": self._output_format,
                },
            )
        except Exception as exc:
            message = sanitize_provider_message(str(exc))
            detail = message or type(exc).__name__
            return self._failure(f"Sarvam Vision request failed: {detail}")

    @staticmethod
    def _failure(message: str, job_id: str | None = None) -> OCRResult:
        metadata: dict[str, Any] = {"error": message}
        if job_id is not None:
            metadata["job_id"] = job_id
        return OCRResult(
            text="",
            provider=PROVIDER_NAME,
            confidence=None,
            success=False,
            metadata=metadata,
        )


def _value(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _normalized_status(item: Any) -> str | None:
    status = _value(item, "status")
    if not isinstance(status, str) or not status.strip():
        return None
    return status.strip().lower()


def _document_text(results: Any) -> tuple[str, int]:
    pages: list[str] = []
    for document in _value(results, "documents") or []:
        for page in _value(document, "pages") or []:
            content = _value(page, "content")
            if isinstance(content, str) and content.strip():
                pages.append(content.strip())
    return "\n\n".join(pages), len(pages)
