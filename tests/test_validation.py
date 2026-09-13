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


def test_ocr_table_amounts_on_lines_after_labels_are_valid():
    result = validate_extraction(
        extraction(advance_paid=10000, balance_due=25000),
        "Advanced\n₹10,000\nBalance\n₹25,000\nTotal Amount\n₹35,000",
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
            result.destination,
            result.advance_paid,
            result.balance_due,
        )
    )
    assert any("no logistics information was extracted" in issue for issue in result.issues)


# ---------------------------------------------------------------------------
# Destination
# ---------------------------------------------------------------------------


def test_destination_present_and_matching_is_valid():
    result = validate_extraction(
        extraction(destination="Jaipur"),
        "gaadi Jaipur bhejni hai",
    )

    assert result.destination.status == FieldStatus.VALID


def test_destination_absent_is_not_stated():
    result = validate_extraction(extraction(destination=None), "truck bhej diya")

    assert result.destination.status == FieldStatus.NOT_STATED
    assert result.destination.valid is True


def test_destination_fabricated_is_invalid():
    result = validate_extraction(
        extraction(destination="Mumbai"),
        "truck jaa raha hai Pune",
    )

    assert result.destination.status == FieldStatus.INVALID
    assert "not found" in result.destination.evidence


def test_destination_cross_script_devanagari_transcript_latin_extraction_is_valid():
    # Regression test: the LLM may report a well-known city in Latin
    # script (e.g. "Delhi") even when the transcript said it in Hindi
    # ("दिल्ली") -- a plain same-script substring check would wrongly
    # mark this unsupported purely due to the script difference.
    result = validate_extraction(
        extraction(destination="Delhi"),
        "truck दिल्ली bhejna hai",
    )

    assert result.destination.status == FieldStatus.VALID


def test_destination_devanagari_word_ending_in_vowel_sign_matches_as_whole_word():
    # Regression test: Python's regex \b treats a Devanagari dependent
    # vowel sign (e.g. the "ी" ending "दिल्ली") as a non-word character,
    # which silently broke the word-boundary check right after any
    # Hindi word ending in one -- an extremely common word shape.
    result = validate_extraction(
        extraction(destination="दिल्ली"),
        "truck दिल्ली bhejna hai",
    )

    assert result.destination.status == FieldStatus.VALID


# ---------------------------------------------------------------------------
# Hindi phonetic (spelled-out) vehicle numbers
# ---------------------------------------------------------------------------


def test_hindi_phonetic_spelled_out_vehicle_number_matches():
    result = validate_extraction(
        extraction(truck_number="RJ14GB1122"),
        "truck आर जे वन फोर "
        "जी बी वन वन टू टू bhejna hai",
    )

    assert result.truck_number.status == FieldStatus.VALID
    assert result.truck_number.normalized_value == "RJ14GB1122"


def test_hinglish_phonetic_spelled_out_vehicle_number_matches():
    result = validate_extraction(
        extraction(truck_number="MH12AB1234"),
        "gaadi em aitch one two e bee one two three four ja rahi hai",
    )

    assert result.truck_number.status == FieldStatus.VALID
    assert result.truck_number.normalized_value == "MH12AB1234"


def test_isolated_phonetic_looking_word_does_not_falsely_form_a_vehicle_number():
    # "do" (Hindi for "two") appearing on its own, not as part of a
    # genuine spelled-out sequence, must not be swept into a false match.
    result = validate_extraction(
        extraction(truck_number="RJ14GB1122"),
        "usko do baar bola advance dena hai",
    )

    assert result.truck_number.status == FieldStatus.INVALID


# ---------------------------------------------------------------------------
# Full Hindi cardinal number table (1-99)
# ---------------------------------------------------------------------------


def test_hindi_compound_number_pachees_25():
    result = validate_extraction(
        extraction(balance_due=25000),
        "बैलेंस पच्चीस हज़ार रुपये है",
    )

    assert result.balance_due.status == FieldStatus.VALID


def test_hindi_compound_numbers_across_ranges():
    cases = (
        (21000, "advance इक्कीस हजार diya"),
        (47000, "advance सैंतालीस हजार diya"),
        (63000, "advance तिरसठ हजार diya"),
        (89000, "advance नवासी हजार diya"),
        (99000, "advance निन्यानवे हजार diya"),
    )
    for amount, transcript in cases:
        result = validate_extraction(extraction(advance_paid=amount), transcript)
        assert result.advance_paid.status == FieldStatus.VALID, (amount, transcript)


# ---------------------------------------------------------------------------
# Advance/balance context isolation (Devanagari "aur"/"balance")
# ---------------------------------------------------------------------------


def test_devanagari_balance_keyword_and_aur_separator_isolate_each_field():
    # Regression test: "बैलेंस" (Devanagari
    # spelling of "balance") was not recognized as a balance keyword at
    # all, and "और" (Devanagari "and") was not a clause
    # delimiter -- together this meant an advance+balance sentence
    # joined by "aur" was treated as one undivided clause, so both
    # amounts became candidates for *both* fields.
    transcript = (
        "advance दस हजार रुपये है "
        "और बैलेंस पच्चीस "
        "हजार रुपये है"
    )
    result = validate_extraction(
        extraction(advance_paid=10000, balance_due=25000), transcript
    )

    assert result.advance_paid.status == FieldStatus.VALID
    assert result.balance_due.status == FieldStatus.VALID


# ---------------------------------------------------------------------------
# Genuine conflicts must still be caught
# ---------------------------------------------------------------------------


def test_genuinely_conflicting_amounts_still_needs_review_with_destination_present():
    result = validate_extraction(
        extraction(destination="Jaipur", advance_paid=5000),
        "truck Jaipur ja raha hai, advance 5000 diya, advance bhi 8000 hua tha",
    )

    assert result.destination.status == FieldStatus.VALID
    assert result.advance_paid.status == FieldStatus.NEEDS_REVIEW
    assert result.status == ValidationStatus.NEEDS_REVIEW


# ---------------------------------------------------------------------------
# End-to-end example from the product spec
# ---------------------------------------------------------------------------


def test_full_hindi_voice_note_example_is_accepted():
    transcript = (
        "रमेश ट्रेडर्स के लिए ट्रक "
        "आर जे वन फोर जी बी वन वन टू टू "
        "में दिल्ली भेजना है "
        "एडवांस दस हज़ार रुपये है "
        "और बैलेंस पच्चीस हज़ार "
        "रुपये है"
    )
    result = validate_extraction(
        extraction(
            party_name="रमेश ट्रेडर्स",
            truck_number="RJ14GB1122",
            destination="Delhi",
            advance_paid=10000,
            balance_due=25000,
        ),
        transcript,
    )

    assert result.status == ValidationStatus.ACCEPTED
    assert result.party_name.status == FieldStatus.VALID
    assert result.truck_number.status == FieldStatus.VALID
    assert result.truck_number.normalized_value == "RJ14GB1122"
    assert result.destination.status == FieldStatus.VALID
    assert result.advance_paid.status == FieldStatus.VALID
    assert result.balance_due.status == FieldStatus.VALID
