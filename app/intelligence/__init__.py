"""Sauda AI Phase 2 -- Intelligence Pack.

Turns raw voice notes and document photos into structured, validated
logistics data. Independent and isolated from Phase 1: this package
never imports Shipment, never touches SQLite, and never performs a
database operation. ``shipment_id`` is carried through as an opaque
identifier only.

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

:class:`ShipmentRepository` is the contract Phase 1 implements after
the two branches are merged -- Phase 2 never imports or calls it
itself; it exists so the integration boundary has one precise,
reviewable shape (see ``app.intelligence.repository``).
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
from app.intelligence.service import process_audio

__all__ = [
    "process_audio",
    "extract_document_text",
    "ProcessingResult",
    "ProcessingStatus",
    "LogisticsExtraction",
    "OCRResult",
    "OCRQuality",
    "ShipmentRepository",
]
