"""Phase 2 orchestration layer -- the one function Phase 1 calls.

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
Phase 1 -> Phase 2:   ``shipment_id`` (opaque int) + ``file_path`` (local .ogg)
Phase 2 -> Phase 1:   ``ProcessingResult``

``process_audio`` never queries, reads, or writes anything belonging
to Phase 1. ``shipment_id`` is carried through purely as an opaque
label (and as half of the idempotency cache key) -- it is never used
to look up a Shipment. Phase 2 does not set a shipment to
``IN_TRANSIT`` and does not touch SQLite; that decision and that write
belong entirely to Phase 1, e.g.:

    result = await process_audio(shipment_id, file_path)
    if result.status == ProcessingStatus.ACCEPTED:
        # Phase 1's own code, against Phase 1's own schema:
        update_shipment(shipment_id, result.extraction)
        shipment.status = "IN_TRANSIT"
    elif result.status == ProcessingStatus.NEEDS_REVIEW:
        queue_for_human_review(shipment_id, result.extraction, result.reason)
    else:  # FAILED
        record_processing_failure(shipment_id, result.reason)

See ``app.intelligence.repository.ShipmentRepository`` for the
documented shape of the Phase 1 integration code itself; this module
never imports or calls it.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol

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
from app.intelligence.stt import transcribe
from app.intelligence.validation import validate_extraction

MediaValidator = Callable[[str], Awaitable[MediaMetadata]]
SttProvider = Callable[[str], Awaitable[STTResult]]
Normalizer = Callable[[str], NormalizedTranscript]
Extractor = Callable[[str], Awaitable[LogisticsExtraction]]
Validator = Callable[[LogisticsExtraction, str], ValidationResult]
Decider = Callable[[ValidationResult], ProcessingDecision]

IdempotencyKey = tuple[int, str]


class IdempotencyStore(Protocol):
    """Phase-2-local idempotency cache, keyed by (shipment_id, media sha256).

    Deliberately not backed by any database -- this exists only to let
    ``process_audio`` skip re-running STT/extraction for the exact
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


def _failed_result(shipment_id: int, reason: str) -> ProcessingResult:
    return ProcessingResult(
        shipment_id=shipment_id,
        status=ProcessingStatus.FAILED,
        extraction=None,
        reason=reason,
    )


def _result_from_decision(shipment_id: int, decision: ProcessingDecision) -> ProcessingResult:
    if decision.status == ProcessingStatus.FAILED:
        return _failed_result(shipment_id, decision.reason)

    return ProcessingResult(
        shipment_id=shipment_id,
        status=decision.status,
        extraction=decision.extraction,
        reason=None if decision.status == ProcessingStatus.ACCEPTED else decision.reason,
    )


async def process_audio(
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
        return _result_from_decision(shipment_id, decision)

    validation = validator(extraction, normalized.normalized_transcript)
    decision = decider(validation)
    result = _result_from_decision(shipment_id, decision)

    if idempotency_store is not None:
        await idempotency_store.set(cache_key, result)

    return result
