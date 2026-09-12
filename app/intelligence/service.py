"""Pure intelligence pipeline plus the Shipment-oriented integration service.

Wires together every prior Phase 2 stage into a single pipeline:

    audio
    -> media validation      (app.intelligence.media_validator)
    -> Sarvam STT             (app.intelligence.stt)
    -> transcript normalization (app.intelligence.normalization)
    -> Qwen3/Groq extraction  (app.intelligence.extraction)
    -> deterministic validation (app.intelligence.validation)
    -> review decision         (app.intelligence.decision)

and reports the outcome as a single ``ProcessingResult``.

Integration contract
---------------------
``run_audio_pipeline`` preserves Phase 2's fully dependency-injected,
file-oriented pipeline for focused unit testing. ``process_audio`` is
the application boundary: it accepts only a shipment ID, loads the
downloaded ``media_path`` through the shared SQLAlchemy layer, runs the
pipeline, and applies the result to that same row.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Awaitable, Callable, Protocol

from sqlalchemy.orm import Session

from app.intelligence.decision import (
    decide_processing_result,
    decide_processing_result_for_extraction_failure,
)
from app.intelligence.exceptions import ExtractionError, MediaValidationError, SttError
from app.intelligence.extraction import extract_logistics_data
from app.intelligence.media_validator import validate_media
from app.intelligence.models import (
    LogisticsExtraction,
    MediaMetadata,
    NormalizedTranscript,
    ProcessingDecision,
    ProcessingResult,
    ProcessingStatus,
    STTResult,
    ValidationResult,
)
from app.intelligence.normalization import normalize_transcript
from app.intelligence.repository import ShipmentRepository
from app.intelligence.stt import transcribe
from app.intelligence.validation import validate_extraction
from app.database import SessionLocal

MediaValidator = Callable[[str], Awaitable[MediaMetadata]]
SttProvider = Callable[[str], Awaitable[STTResult]]
Normalizer = Callable[[str], NormalizedTranscript]
Extractor = Callable[[str], Awaitable[LogisticsExtraction]]
Validator = Callable[[LogisticsExtraction, str], ValidationResult]
Decider = Callable[[ValidationResult], ProcessingDecision]

IdempotencyKey = tuple[int, str]
SessionFactory = Callable[[], Session]

logger = logging.getLogger(__name__)


class IdempotencyStore(Protocol):
    """Phase-2-local idempotency cache, keyed by (shipment_id, media sha256).

    Deliberately not backed by any database -- this exists only to let
    ``run_audio_pipeline`` skip re-running STT/extraction for the exact
    same shipment_id + audio content it has already processed. It has
    no relationship to, and no dependency on, the Phase 1 database.
    """

    async def get(self, key: IdempotencyKey) -> ProcessingResult | None: ...

    async def set(self, key: IdempotencyKey, result: ProcessingResult) -> None: ...


class InMemoryIdempotencyStore:
    """Simple in-process ``IdempotencyStore`` implementation."""

    def __init__(self) -> None:
        self._results: dict[IdempotencyKey, ProcessingResult] = {}

    async def get(self, key: IdempotencyKey) -> ProcessingResult | None:
        return self._results.get(key)

    async def set(self, key: IdempotencyKey, result: ProcessingResult) -> None:
        self._results[key] = result


def _failed_result(
    shipment_id: int, reason: str, transcript: str | None = None
) -> ProcessingResult:
    return ProcessingResult(
        shipment_id=shipment_id,
        status=ProcessingStatus.FAILED,
        transcript=transcript,
        extraction=None,
        reason=reason,
    )


def _result_from_decision(
    shipment_id: int,
    decision: ProcessingDecision,
    transcript: str,
) -> ProcessingResult:
    if decision.status == ProcessingStatus.FAILED:
        return _failed_result(shipment_id, decision.reason, transcript)

    return ProcessingResult(
        shipment_id=shipment_id,
        status=decision.status,
        transcript=transcript,
        extraction=decision.extraction,
        reason=None if decision.status == ProcessingStatus.ACCEPTED else decision.reason,
    )


async def run_audio_pipeline(
    shipment_id: int,
    file_path: str,
    *,
    media_validator: MediaValidator = validate_media,
    stt: SttProvider = transcribe,
    normalizer: Normalizer = normalize_transcript,
    extractor: Extractor = extract_logistics_data,
    validator: Validator = validate_extraction,
    decider: Decider = decide_processing_result,
    idempotency_store: IdempotencyStore | None = None,
) -> ProcessingResult:
    """Run the full Phase 2 pipeline for one voice note.

    ``shipment_id`` is treated as an opaque identifier: it is never
    used to query anything, only carried through into the returned
    ``ProcessingResult`` and (if ``idempotency_store`` is given) used
    together with the audio's SHA-256 as a cache key.

    Every pipeline stage is dependency-injected with a production
    default, so tests can substitute fakes for the network-calling
    stages (``stt``, ``extractor``) without any real API calls or
    environment configuration.

    Only the outcome of a *complete* run (media validated, STT and
    extraction both succeeded, deterministic validation + decision
    applied) is written to ``idempotency_store``. A ``FAILED`` result
    caused by a provider-side failure -- STT/extraction raising after
    their own bounded retries were exhausted -- is deliberately never
    cached: that failure reflects the provider's transient state at
    call time, not a property of the audio content itself, so caching
    it would permanently block that exact audio from ever being
    processed successfully even after the provider recovers. A media
    validation failure is likewise not cached, since it depends on
    ``file_path`` rather than content and there is no useful sha256 to
    key it by.
    """
    try:
        metadata = await media_validator(file_path)
    except MediaValidationError as exc:
        return _failed_result(shipment_id, f"media validation failed: {exc}")

    cache_key: IdempotencyKey = (shipment_id, metadata.sha256)
    if idempotency_store is not None:
        cached = await idempotency_store.get(cache_key)
        if cached is not None:
            return cached

    try:
        stt_result = await stt(file_path)
    except SttError as exc:
        return _failed_result(shipment_id, f"speech-to-text failed: {exc}")

    normalized = normalizer(stt_result.transcript)

    try:
        extraction = await extractor(normalized.normalized_transcript)
    except ExtractionError as exc:
        decision = decide_processing_result_for_extraction_failure(
            f"logistics extraction failed: {exc}"
        )
        return _result_from_decision(shipment_id, decision, stt_result.transcript)

    validation = validator(extraction, normalized.normalized_transcript)
    decision = decider(validation)
    result = _result_from_decision(shipment_id, decision, stt_result.transcript)

    if idempotency_store is not None:
        await idempotency_store.set(cache_key, result)

    return result


def sanitize_processing_error(reason: str) -> str:
    """Remove configured credentials and URLs before persistence or logging."""

    safe_reason = " ".join(reason.split())
    for variable in (
        "META_ACCESS_TOKEN",
        "SARVAM_API_KEY",
        "GROQ_API_KEY",
        "INDICOCR_API_KEY",
    ):
        secret = os.getenv(variable)
        if secret:
            safe_reason = safe_reason.replace(secret, "<redacted>")
    safe_reason = re.sub(
        r"(?i)\b(bearer|token|api[_ -]?key)\s*[:=]?\s*[^\s,;]+",
        r"\1 <redacted>",
        safe_reason,
    )
    safe_reason = re.sub(r"https?://\S+", "<url>", safe_reason)
    return safe_reason[:1000]


async def process_audio(
    shipment_id: int,
    *,
    session_factory: SessionFactory = SessionLocal,
    media_validator: MediaValidator = validate_media,
    stt: SttProvider = transcribe,
    normalizer: Normalizer = normalize_transcript,
    extractor: Extractor = extract_logistics_data,
    validator: Validator = validate_extraction,
    decider: Decider = decide_processing_result,
    idempotency_store: IdempotencyStore | None = None,
) -> ProcessingResult:
    """Process the downloaded audio belonging to one canonical Shipment row."""

    with session_factory() as session:
        repository = ShipmentRepository(session)
        shipment = repository.get_shipment(shipment_id)
        if shipment is None:
            return _failed_result(shipment_id, "Shipment was not found.")
        if not shipment.media_path:
            reason = "Shipment does not have downloaded media."
            repository.mark_failed(shipment, reason)
            return _failed_result(shipment_id, reason)
        file_path = shipment.media_path
        repository.mark_processing_started(shipment)

    logger.info("intelligence_processing_started shipment_id=%s", shipment_id)
    try:
        result = await run_audio_pipeline(
            shipment_id,
            file_path,
            media_validator=media_validator,
            stt=stt,
            normalizer=normalizer,
            extractor=extractor,
            validator=validator,
            decider=decider,
            idempotency_store=idempotency_store,
        )
    except Exception as exc:
        result = _failed_result(
            shipment_id,
            sanitize_processing_error(f"Unexpected intelligence failure: {exc}"),
        )

    if result.reason is not None:
        result = result.model_copy(
            update={"reason": sanitize_processing_error(result.reason)}
        )

    with session_factory() as session:
        repository = ShipmentRepository(session)
        shipment = repository.get_shipment(shipment_id)
        if shipment is None:
            return _failed_result(shipment_id, "Shipment disappeared during processing.")
        repository.apply_result(shipment, result)

    logger.info(
        "intelligence_processing_completed shipment_id=%s outcome=%s",
        shipment_id,
        result.status.value,
    )
    return result
