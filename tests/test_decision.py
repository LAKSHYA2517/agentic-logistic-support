from app.intelligence.decision import (
    decide_processing_result,
    decide_processing_result_for_extraction_failure,
)
from app.intelligence.models import (
    FieldStatus,
    FieldValidation,
    LogisticsExtraction,
    ProcessingStatus,
    ValidationResult,
    ValidationStatus,
)
from app.intelligence.validation import validate_extraction


def field(value, status, evidence=None, normalized_value=None) -> FieldValidation:
    return FieldValidation(
        value=value,
        status=status,
        evidence=evidence,
        normalized_value=normalized_value,
    )


def not_stated() -> FieldValidation:
    return field(None, FieldStatus.NOT_STATED)


# ---------------------------------------------------------------------------
# ACCEPTED
# ---------------------------------------------------------------------------


def test_accepted_when_validation_fully_confirmed():
    result = validate_extraction(
        LogisticsExtraction(
            party_name="Ramesh",
            truck_number="RJ14GB1122",
            advance_paid=10000,
        ),
        "Ramesh ko truck RJ14GB1122 se advance das hazaar diya",
    )

    decision = decide_processing_result(result)

    assert decision.status == ProcessingStatus.ACCEPTED
    assert decision.review_required is False
    assert decision.extraction == LogisticsExtraction(
        party_name="Ramesh", truck_number="RJ14GB1122", advance_paid=10000
    )
    assert decision.validation is result
    assert "confirmed" in decision.reason


def test_empty_extraction_is_needs_review_not_accepted():
    # Regression test: an extraction where nothing was stated at all
    # (every field null) must NOT be auto-accepted -- there is nothing
    # confirmed here, so it is not equivalent to a positively-validated
    # result. Previously this incorrectly returned ACCEPTED.
    result = validate_extraction(LogisticsExtraction(), "just some unrelated chatter")

    decision = decide_processing_result(result)

    assert decision.status == ProcessingStatus.NEEDS_REVIEW
    assert decision.review_required is True
    assert "no logistics information" in decision.reason


def test_explicit_example_truck_number_accepted():
    result = validate_extraction(
        LogisticsExtraction(truck_number="RJ14-GB-1122"),
        "Ramesh ko truck RJ14-GB-1122 bhejna hai",
    )

    decision = decide_processing_result(result)

    assert decision.status == ProcessingStatus.ACCEPTED
    # The canonical (normalized) form is what flows through to Phase 1,
    # not the raw hyphenated value the extractor happened to emit.
    assert decision.extraction.truck_number == "RJ14GB1122"


# ---------------------------------------------------------------------------
# NEEDS_REVIEW
# ---------------------------------------------------------------------------


def test_explicit_example_ambiguous_hedged_amount_needs_review():
    result = validate_extraction(
        LogisticsExtraction(advance_paid=10000),
        "shayad dus hazaar advance",
    )

    decision = decide_processing_result(result)

    assert decision.status == ProcessingStatus.NEEDS_REVIEW
    assert decision.review_required is True
    assert "review" in decision.reason.lower()


def test_explicit_example_contradiction_needs_review():
    result = validate_extraction(
        LogisticsExtraction(advance_paid=10000),
        "advance paid 10,000, advance is actually 15,000",
    )

    decision = decide_processing_result(result)

    assert decision.status == ProcessingStatus.NEEDS_REVIEW
    assert decision.review_required is True


def test_needs_review_when_mixed_valid_and_invalid_fields():
    result = ValidationResult(
        status=ValidationStatus.NEEDS_REVIEW,
        extraction=LogisticsExtraction(party_name="Ramesh", truck_number="RJ14GB1122"),
        party_name=field("Ramesh", FieldStatus.VALID, evidence="found"),
        truck_number=field(
            "RJ14GB1122",
            FieldStatus.INVALID,
            evidence="vehicle number not found in transcript",
            normalized_value="RJ14GB1122",
        ),
        advance_paid=not_stated(),
        balance_due=not_stated(),
        issues=["vehicle number not found in transcript"],
    )

    decision = decide_processing_result(result)

    assert decision.status == ProcessingStatus.NEEDS_REVIEW
    assert decision.review_required is True
    assert decision.extraction.party_name == "Ramesh"
    assert decision.extraction.truck_number == "RJ14GB1122"


def test_needs_review_when_ambiguous_field_present_even_with_no_invalid_fields():
    result = ValidationResult(
        status=ValidationStatus.NEEDS_REVIEW,
        extraction=LogisticsExtraction(party_name="Ramesh", advance_paid=10000),
        party_name=field("Ramesh", FieldStatus.VALID, evidence="found"),
        truck_number=not_stated(),
        advance_paid=field(
            10000, FieldStatus.NEEDS_REVIEW, evidence="transcript expresses uncertainty"
        ),
        balance_due=not_stated(),
        issues=["transcript expresses uncertainty"],
    )

    decision = decide_processing_result(result)

    assert decision.status == ProcessingStatus.NEEDS_REVIEW
    assert decision.review_required is True


# ---------------------------------------------------------------------------
# FAILED
# ---------------------------------------------------------------------------


def test_failed_when_the_only_stated_field_is_fabricated():
    result = validate_extraction(
        LogisticsExtraction(party_name="GhostParty"),
        "Ramesh ko truck bhejna hai",
    )

    decision = decide_processing_result(result)

    assert decision.status == ProcessingStatus.FAILED
    assert decision.review_required is True
    assert "cannot" not in decision.reason  # sanity: reason is populated, not a stub
    assert "unsupported" in decision.reason


def test_failed_when_every_stated_field_is_invalid():
    result = ValidationResult(
        status=ValidationStatus.NEEDS_REVIEW,
        extraction=LogisticsExtraction(party_name="GhostParty", truck_number="RJ14GB1122"),
        party_name=field("GhostParty", FieldStatus.INVALID, evidence="not found in transcript"),
        truck_number=field(
            "RJ14GB1122",
            FieldStatus.INVALID,
            evidence="vehicle number not found in transcript",
            normalized_value="RJ14GB1122",
        ),
        advance_paid=not_stated(),
        balance_due=not_stated(),
        issues=["not found in transcript", "vehicle number not found in transcript"],
    )

    decision = decide_processing_result(result)

    assert decision.status == ProcessingStatus.FAILED
    assert decision.review_required is True


def test_explicit_example_malformed_output_after_retry_failed():
    decision = decide_processing_result_for_extraction_failure(
        "Groq structured output did not match LogisticsExtraction schema after 3 retries"
    )

    assert decision.status == ProcessingStatus.FAILED
    assert decision.review_required is True
    assert decision.extraction is None
    assert decision.validation is None
    assert "3 retries" in decision.reason


# ---------------------------------------------------------------------------
# General invariants
# ---------------------------------------------------------------------------


def test_review_required_is_false_only_for_accepted():
    accepted = validate_extraction(
        LogisticsExtraction(advance_paid=10000), "advance das hazaar diya"
    )
    needs_review = validate_extraction(
        LogisticsExtraction(advance_paid=10000), "shayad das hazaar advance diya tha"
    )

    accepted_decision = decide_processing_result(accepted)
    needs_review_decision = decide_processing_result(needs_review)

    assert accepted_decision.review_required is False
    assert needs_review_decision.review_required is True


def test_decision_reason_is_always_non_empty():
    for transcript, extraction in (
        ("no claims at all", LogisticsExtraction()),
        ("shayad das hazaar advance diya tha", LogisticsExtraction(advance_paid=10000)),
        ("Ramesh ko truck bhejna hai", LogisticsExtraction(party_name="GhostParty")),
    ):
        result = validate_extraction(extraction, transcript)
        decision = decide_processing_result(result)
        assert decision.reason.strip() != ""
