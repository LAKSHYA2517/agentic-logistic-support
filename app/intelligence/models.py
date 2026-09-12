"""Pydantic models for the media intake layer."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class MediaMetadata(BaseModel):
    """Validated metadata for an inbound voice-note file.

    Produced by ``validate_media`` once a file has passed all integrity
    checks. Downstream stages (STT, extraction) should depend on this
    model rather than re-touching the filesystem.
    """

    file_path: str
    file_size: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64)
    extension: str


class STTResult(BaseModel):
    """Result of transcribing an audio file via a speech-to-text provider.

    This is a Phase-2-local model. It intentionally knows nothing about
    Shipment or any other Phase 1 concept -- it only describes the
    audio-to-transcript outcome.
    """

    transcript: str
    provider: str
    model: str
    language_code: str | None = None
    request_id: str | None = None


class NormalizedTranscript(BaseModel):
    """Result of deterministic normalization of an STT transcript.

    ``raw_transcript`` is preserved verbatim for audit/debugging.
    ``normalized_transcript`` only differs from it in whitespace,
    Unicode form, and punctuation/separator cleanup -- never in
    semantic content.
    """

    raw_transcript: str
    normalized_transcript: str


class LogisticsExtraction(BaseModel):
    """Structured logistics fields extracted from a transcript.

    Every field is optional and defaults to ``None``. The extraction
    provider must represent anything not explicitly stated in the
    transcript as ``null`` rather than guessing -- this model carries
    no confidence/certainty metadata of its own, by design.
    """

    party_name: str | None = None
    truck_number: str | None = None
    advance_paid: int | None = None
    balance_due: int | None = None


class FieldStatus(str, Enum):
    """Outcome of deterministically validating one extracted field."""

    VALID = "VALID"
    """The field has a value and the transcript supports it."""

    INVALID = "INVALID"
    """The field has a value that fails format rules or is unsupported
    by (not evidenced in) the transcript."""

    NEEDS_REVIEW = "NEEDS_REVIEW"
    """The field has a value, but the transcript is ambiguous about it
    (hedged language, or multiple conflicting mentions)."""

    NOT_STATED = "NOT_STATED"
    """The field is ``null`` -- no claim was made, so there is nothing
    to validate."""


class ValidationStatus(str, Enum):
    """Overall gate outcome for a ``LogisticsExtraction``."""

    ACCEPTED = "ACCEPTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class FieldValidation(BaseModel):
    """Deterministic validation outcome for a single extracted field.

    ``normalized_value`` is only populated for fields that have a
    canonical form (currently ``truck_number``); it is ``None`` for
    every other field.
    """

    value: Any
    status: FieldStatus
    evidence: str | None = None
    normalized_value: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def valid(self) -> bool:
        """True iff nothing needs to be distrusted about this field.

        Deliberately computed from ``status`` rather than stored
        separately -- a stored, independently-settable ``valid`` field
        could disagree with ``status`` (e.g. a caller setting
        ``status=INVALID, valid=True``), silently breaking the
        ACCEPTED/NEEDS_REVIEW/FAILED gate downstream. Computing it
        makes that class of bug impossible.
        """
        return self.status in (FieldStatus.VALID, FieldStatus.NOT_STATED)


class ValidationResult(BaseModel):
    """Field-by-field deterministic validation of a ``LogisticsExtraction``
    against the transcript it was extracted from.

    Matching the JSON Schema alone never sets ``status`` to
    ``ACCEPTED`` -- every non-null field must also be evidenced in the
    transcript, AND at least one field must actually be ``VALID``.
    ``status`` is ``NEEDS_REVIEW`` if any field is ``INVALID`` or
    ``NEEDS_REVIEW``, and also if every field is merely ``NOT_STATED``
    -- an extraction with nothing confirmed in it is not the same as
    one that has been positively confirmed, so it is not auto-accepted
    either.

    ``extraction`` carries the exact ``LogisticsExtraction`` this
    result was computed from, so downstream code (the review-gate
    decision layer) never needs to reconstruct it from the individual
    ``FieldValidation.value``s -- which previously risked silently
    reintroducing a field's raw, un-normalized value instead of its
    validated ``normalized_value``.
    """

    status: ValidationStatus
    extraction: LogisticsExtraction
    party_name: FieldValidation
    truck_number: FieldValidation
    advance_paid: FieldValidation
    balance_due: FieldValidation
    issues: list[str] = Field(default_factory=list)


class ProcessingStatus(str, Enum):
    """Final disposition of one voice-note processing attempt."""

    ACCEPTED = "ACCEPTED"
    """Every field is confirmed by transcript evidence or not stated."""

    NEEDS_REVIEW = "NEEDS_REVIEW"
    """At least one field is ambiguous, contradictory, or unsupported,
    but at least part of the extraction is trustworthy or there is
    something concrete for a human to look at."""

    FAILED = "FAILED"
    """The extraction could not be trusted at all: either every field
    the model claimed a value for was unsupported by the transcript,
    or no usable structured output was ever produced (e.g. malformed
    output that survived bounded retries)."""


class ProcessingDecision(BaseModel):
    """Explainable ACCEPTED / NEEDS_REVIEW / FAILED decision.

    ``extraction`` and ``validation`` are ``None`` only for the
    no-structured-output-at-all case (e.g. the provider never returned
    parseable JSON even after bounded retries) -- there is nothing to
    reconstruct or validate in that situation.
    """

    status: ProcessingStatus
    extraction: LogisticsExtraction | None
    validation: ValidationResult | None
    review_required: bool
    reason: str


class ProcessingResult(BaseModel):
    """The single object Phase 2's orchestration layer hands back to Phase 1.

    The Shipment-oriented service persists this result through the
    canonical SQLAlchemy model. The pure pipeline can still return it
    without touching application state.

    ``extraction`` is always ``None`` when ``status == FAILED`` -- a
    failed run has nothing trustworthy to hand over. ``reason`` is
    always ``None`` when ``status == ACCEPTED`` -- there is nothing to
    explain when every field was confirmed.
    """

    shipment_id: int
    status: ProcessingStatus
    transcript: str | None = None
    extraction: LogisticsExtraction | None = None
    reason: str | None = None


class OCRResult(BaseModel):
    """Result of running a document-perception provider over a file.

    The provider converts a supported image/document into raw text, and
    the perception orchestration layer adds a deterministic quality verdict.

    ``confidence`` is ``None`` whenever the underlying provider does
    not supply a reliable confidence score -- it is never fabricated.
    ``success=False`` is how a failed extraction is represented; this
    model is always returned, never replaced by a raised exception,
    so failure is visible as ordinary data to whatever quality gate
    inspects it.
    """

    text: str
    provider: str
    confidence: float | None = None
    success: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class OCRQuality(str, Enum):
    """Deterministic quality classification of one ``OCRResult``.

    Never derived from a provider's self-reported confidence score
    (which may be absent or unreliable) -- always computed from the
    text itself via ``app.intelligence.ocr.evaluate_ocr_quality``.
    """

    GOOD = "GOOD"
    """Enough real text was recovered to proceed without a fallback provider."""

    POOR = "POOR"
    """Text came back, but too little of it looks like real content
    (e.g. mostly symbols/noise) to trust as-is."""

    FAILED = "FAILED"
    """No usable text at all (empty, whitespace-only, or the provider
    call itself failed)."""
