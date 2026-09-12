"""Confidence / review decision layer.

Turns a Phase 2E ``ValidationResult`` into an explainable
``ProcessingDecision``: ACCEPTED, NEEDS_REVIEW, or FAILED. This module
performs no database operation and does not call any LLM or external
API -- the decision is a deterministic function of the validation
outcome (schema validity, transcript evidence, ambiguity,
contradictions, and field completeness), never an opaque model
confidence score.

This module has no dependency on SQLite, Shipment, WhatsApp, FastAPI,
webhook handling, or any external API adapter.
"""

from __future__ import annotations

from app.intelligence.models import (
    FieldStatus,
    ProcessingDecision,
    ProcessingStatus,
    ValidationResult,
    ValidationStatus,
)


def decide_processing_result(validation_result: ValidationResult) -> ProcessingDecision:
    """Decide ACCEPTED / NEEDS_REVIEW / FAILED from a deterministic validation result.

    Rules, in priority order:

    1. If every field is ``VALID`` or ``NOT_STATED`` (i.e.
       ``validation_result.status == ACCEPTED``): **ACCEPTED**. Every
       claim the extractor made is either confirmed by transcript
       evidence or simply wasn't made.
    2. Else, if at least one field claimed a value but *none* of the
       claimed fields could be confirmed, and none are merely
       ambiguous (no ``VALID`` and no ``NEEDS_REVIEW`` fields, only
       ``INVALID`` ones): **FAILED**. Nothing in the extraction can be
       trusted -- this is functionally equivalent to a malformed or
       hallucinated result, not a case for human triage of a plausible
       partial answer.
    3. Otherwise (some fields are ambiguous/contradictory, or invalid
       fields are mixed with at least one confirmed field):
       **NEEDS_REVIEW**. There is something concrete for a human to
       look at -- either genuine ambiguity/contradiction in the
       transcript, or a partially-trustworthy extraction.

    In every case ``review_required`` is ``True`` unless the status is
    ``ACCEPTED``.
    """
    extraction = validation_result.extraction

    fields = (
        validation_result.party_name,
        validation_result.truck_number,
        validation_result.advance_paid,
        validation_result.balance_due,
    )
    valid_count = sum(1 for f in fields if f.status == FieldStatus.VALID)
    needs_review_count = sum(1 for f in fields if f.status == FieldStatus.NEEDS_REVIEW)
    invalid_count = sum(1 for f in fields if f.status == FieldStatus.INVALID)

    if validation_result.status == ValidationStatus.ACCEPTED:
        return ProcessingDecision(
            status=ProcessingStatus.ACCEPTED,
            extraction=extraction,
            validation=validation_result,
            review_required=False,
            reason="All extracted fields are confirmed by transcript evidence or were not stated.",
        )

    if invalid_count > 0 and valid_count == 0 and needs_review_count == 0:
        return ProcessingDecision(
            status=ProcessingStatus.FAILED,
            extraction=extraction,
            validation=validation_result,
            review_required=True,
            reason=(
                "Every field the extraction claimed a value for is unsupported by the "
                "transcript; nothing in this result can be trusted: "
                + "; ".join(validation_result.issues)
            ),
        )

    return ProcessingDecision(
        status=ProcessingStatus.NEEDS_REVIEW,
        extraction=extraction,
        validation=validation_result,
        review_required=True,
        reason="One or more fields need human review: " + "; ".join(validation_result.issues),
    )


def decide_processing_result_for_extraction_failure(reason: str) -> ProcessingDecision:
    """FAILED decision for when no structured output was ever produced.

    Covers the case where the extraction provider (Phase 2D) never
    returned a parseable ``LogisticsExtraction`` at all -- e.g.
    malformed/non-schema-conforming output that survived bounded
    retries. There is no extraction or validation result to attach in
    that situation, so both are ``None``.
    """
    return ProcessingDecision(
        status=ProcessingStatus.FAILED,
        extraction=None,
        validation=None,
        review_required=True,
        reason=reason,
    )
