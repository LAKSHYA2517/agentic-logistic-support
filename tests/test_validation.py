from app.intelligence.models import (
    FieldStatus,
    LogisticsExtraction,
    ValidationStatus,
)
from app.intelligence.validation import normalize_truck_number, validate_extraction


def extraction(**kwargs) -> LogisticsExtraction:
    return LogisticsExtraction(**kwargs)


# ---------------------------------------------------------------------------
# Truck number
# ---------------------------------------------------------------------------


def test_valid_truck_number():
    result = validate_extraction(
        extraction(truck_number="RJ14GB1122"),
        "truck number RJ14GB1122 confirmed",
    )

    assert result.truck_number.status == FieldStatus.VALID
    assert result.truck_number.valid is True
    assert result.truck_number.normalized_value == "RJ14GB1122"


def test_invalid_truck_number_format():
    result = validate_extraction(
        extraction(truck_number="RJ1"),
        "the truck RJ1 is on its way",
    )

    assert result.truck_number.status == FieldStatus.INVALID
    assert result.truck_number.normalized_value is None
    assert normalize_truck_number("RJ1") is None


def test_truck_number_separator_normalization_variants():
    for raw in ("RJ14-GB-1122", "RJ14 GB 1122", "RJ14GB1122"):
        assert normalize_truck_number(raw) == "RJ14GB1122"

    result = validate_extraction(
        extraction(truck_number="RJ14-GB-1122"),
        "gaadi RJ14 GB 1122 nikal chuki hai",
    )

    assert result.truck_number.status == FieldStatus.VALID
    assert result.truck_number.normalized_value == "RJ14GB1122"


def test_missing_truck_number():
    result = validate_extraction(extraction(truck_number=None), "no vehicle mentioned")

    assert result.truck_number.status == FieldStatus.NOT_STATED
    assert result.truck_number.valid is True
    assert result.truck_number.normalized_value is None


def test_fabricated_truck_number():
    result = validate_extraction(
        extraction(truck_number="RJ14GB1122"),
        "advance paid 5000, no vehicle mentioned",
    )

    assert result.truck_number.status == FieldStatus.INVALID
    assert result.truck_number.normalized_value == "RJ14GB1122"
    assert "not found" in result.truck_number.evidence


def test_shape_coincidental_phrase_is_not_mistaken_for_truck_number_evidence():
    # Regression test: scanning the transcript for truck-number evidence
    # must not treat an ordinary phrase shaped like "2 letters + digits +
    # letters + digits" (e.g. a time/date mention) as a vehicle-number
    # mention just because it fits the shape with space separators.
    # "TO" is not a real Indian RTO state code, so this must not match.
    result = validate_extraction(
        extraction(truck_number="TO12PM2023"),
        "meeting to 12 pm 2023 confirmed",
    )

    assert result.truck_number.status == FieldStatus.INVALID


def test_real_state_code_with_space_separators_still_recognized():
    # The state-code restriction must not break legitimate space-separated
    # truck-number mentions, which is how spoken numbers often transcribe.
    result = validate_extraction(
        extraction(truck_number="RJ14GB1122"),
        "gaadi RJ 14 GB 1122 nikal chuki hai",
    )

    assert result.truck_number.status == FieldStatus.VALID


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


def test_valid_money():
    result = validate_extraction(
        extraction(advance_paid=5000),
        "advance paid was 5000 rupees",
    )

    assert result.advance_paid.status == FieldStatus.VALID


def test_missing_money():
    result = validate_extraction(extraction(advance_paid=None), "truck left the yard")

    assert result.advance_paid.status == FieldStatus.NOT_STATED
    assert result.advance_paid.valid is True


def test_negative_money_is_invalid():
    result = validate_extraction(
        extraction(advance_paid=-500),
        "advance paid was 500 rupees",
    )

    assert result.advance_paid.status == FieldStatus.INVALID
    assert "negative" in result.advance_paid.evidence


def test_ambiguous_money_hedged_language_needs_review():
    result = validate_extraction(
        extraction(advance_paid=10000),
        "shayad das hazaar advance diya tha",
    )

    assert result.advance_paid.status == FieldStatus.NEEDS_REVIEW
    assert result.advance_paid.valid is False


def test_conflicting_amounts_needs_review():
    result = validate_extraction(
        extraction(advance_paid=5000),
        "advance 5000 diya, advance bhi 8000 hua tha",
    )

    assert result.advance_paid.status == FieldStatus.NEEDS_REVIEW
    assert "multiple" in result.advance_paid.evidence


def test_fabricated_money_not_mentioned_at_all():
    result = validate_extraction(
        extraction(advance_paid=7000),
        "truck reached the destination safely",
    )

    assert result.advance_paid.status == FieldStatus.INVALID


def test_balance_due_valid_independent_of_advance():
    result = validate_extraction(
        extraction(advance_paid=10000, balance_due=5000),
        "advance das hazaar diya, balance 5000 baaki hai",
    )

    assert result.advance_paid.status == FieldStatus.VALID
    assert result.balance_due.status == FieldStatus.VALID


def test_comma_immediately_after_keyword_does_not_sever_amount():
    # Regression test: "advance," must not be split from its own amount
    # just because a comma sits right after the keyword.
    result = validate_extraction(
        extraction(advance_paid=10000),
        "advance, 10000 diya tha",
    )

    assert result.advance_paid.status == FieldStatus.VALID


def test_comma_after_keyword_still_reveals_genuine_conflict():
    # The keyword-comma guard must not swallow a real second amount
    # mentioned in the same keyword-adjacent clause.
    result = validate_extraction(
        extraction(advance_paid=5000),
        "advance, 5000 ya 8000 diya tha",
    )

    assert result.advance_paid.status == FieldStatus.NEEDS_REVIEW


# ---------------------------------------------------------------------------
# Party name
# ---------------------------------------------------------------------------


def test_fabricated_party_name():
    result = validate_extraction(
        extraction(party_name="Suresh"),
        "Ramesh ko truck bhejna hai",
    )

    assert result.party_name.status == FieldStatus.INVALID
    assert "not found" in result.party_name.evidence


def test_party_name_substring_of_a_different_name_is_not_a_match():
    # Regression test: "Ram" must not false-positive-match inside
    # "Raman" (a different person) just because it's a substring.
    result = validate_extraction(
        extraction(party_name="Ram"),
        "Raman ko truck bhejna hai",
    )

    assert result.party_name.status == FieldStatus.INVALID


def test_valid_party_name():
    result = validate_extraction(
        extraction(party_name="Ramesh"),
        "Ramesh ko truck bhejna hai",
    )

    assert result.party_name.status == FieldStatus.VALID


def test_missing_party_name():
    result = validate_extraction(extraction(party_name=None), "truck bhej diya")

    assert result.party_name.status == FieldStatus.NOT_STATED


# ---------------------------------------------------------------------------
# Hindi / Hinglish number expressions
# ---------------------------------------------------------------------------


def test_hindi_number_expression_devanagari():
    result = validate_extraction(
        extraction(advance_paid=10000),
        "एडवांस दस हज़ार दिया",
    )

    assert result.advance_paid.status == FieldStatus.VALID


def test_hinglish_number_expression():
    result = validate_extraction(
        extraction(advance_paid=500),
        "advance paanch sau diya",
    )

    assert result.advance_paid.status == FieldStatus.VALID


def test_hinglish_number_expression_das_hazaar():
    result = validate_extraction(
        extraction(balance_due=10000),
        "balance abhi das hazaar baaki hai",
    )

    assert result.balance_due.status == FieldStatus.VALID


def test_digit_amount_with_k_suffix_and_currency_symbol():
    result_k = validate_extraction(extraction(advance_paid=10000), "advance 10k diya")
    result_rupee = validate_extraction(
        extraction(advance_paid=10000), "advance ₹10,000 diya"
    )

    assert result_k.advance_paid.status == FieldStatus.VALID
    assert result_rupee.advance_paid.status == FieldStatus.VALID


def test_vehicle_number_digits_not_mistaken_for_money():
    result = validate_extraction(
        extraction(advance_paid=5000),
        "truck RJ14-GB-1122 ka advance 5000 diya",
    )

    assert result.advance_paid.status == FieldStatus.VALID


# ---------------------------------------------------------------------------
# Overall ValidationResult status
# ---------------------------------------------------------------------------


def test_overall_status_accepted_when_all_fields_valid_or_not_stated():
    result = validate_extraction(
        extraction(party_name="Ramesh", truck_number="RJ14GB1122", advance_paid=10000),
        "Ramesh ko truck RJ14GB1122 se advance das hazaar diya",
    )

    assert result.status == ValidationStatus.ACCEPTED
    assert result.issues == []


def test_overall_status_needs_review_when_any_field_invalid():
    result = validate_extraction(
        extraction(party_name="GhostParty"),
        "Ramesh ko truck bhejna hai",
    )

    assert result.status == ValidationStatus.NEEDS_REVIEW
    assert len(result.issues) == 1


def test_overall_status_needs_review_on_ambiguous_field_even_if_others_valid():
    result = validate_extraction(
        extraction(party_name="Ramesh", advance_paid=10000),
        "Ramesh shayad das hazaar advance dega",
    )

    assert result.party_name.status == FieldStatus.VALID
    assert result.advance_paid.status == FieldStatus.NEEDS_REVIEW
    assert result.status == ValidationStatus.NEEDS_REVIEW


def test_all_fields_null_is_needs_review_not_accepted():
    # An extraction with nothing stated at all must not be auto-accepted:
    # "nothing confirmed" is not the same as "everything confirmed".
    # Regression test for a bug where this incorrectly returned ACCEPTED.
    result = validate_extraction(extraction(), "just some unrelated chatter")

    assert result.status == ValidationStatus.NEEDS_REVIEW
    assert all(
        f.status == FieldStatus.NOT_STATED
        for f in (
            result.party_name,
            result.truck_number,
            result.advance_paid,
            result.balance_due,
        )
    )
    assert any("no logistics information was extracted" in issue for issue in result.issues)
