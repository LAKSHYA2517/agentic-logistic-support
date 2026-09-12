"""Phase 2 intelligence package integrated with the Phase 1 application.

Turns downloaded voice notes and document photos into structured,
validated logistics data. Provider stages remain independent, while
the public ``process_audio(shipment_id)`` service persists its result
through the application's canonical Shipment model.

Two independent pipelines are exposed here:

Voice notes (Phase 2A-2G):
    ``.ogg`` file -> media validation -> Sarvam STT -> transcript
    normalization -> Qwen3/Groq extraction -> deterministic evidence
    validation -> review-gate decision -> :class:`ProcessingResult`.
    Entry point: :func:`process_audio`.

Documents/photos (Phase 2H):
    image/document -> AI4Bharat IndicOCR -> quality gate -> Sarvam
    Vision fallback (only if OCR quality is POOR/FAILED) ->
    :class:`OCRResult`. Entry point: :func:`extract_document_text`.

:class:`ShipmentRepository` is the concrete adapter over the shared
SQLAlchemy session and model.
"""

from __future__ import annotations

from app.intelligence.models import (
    LogisticsExtraction,
    OCRQuality,
    OCRResult,
    ProcessingResult,
    ProcessingStatus,
)
from app.intelligence.perception import extract_document_text
from app.intelligence.repository import ShipmentRepository
from app.intelligence.service import process_audio, run_audio_pipeline

__all__ = [
    "process_audio",
    "run_audio_pipeline",
    "extract_document_text",
    "ProcessingResult",
    "ProcessingStatus",
    "LogisticsExtraction",
    "OCRResult",
    "OCRQuality",
    "ShipmentRepository",
]
