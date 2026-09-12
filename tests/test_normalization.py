from app.intelligence.models import NormalizedTranscript
from app.intelligence.normalization import normalize_transcript


def test_returns_typed_result_and_preserves_raw():
    raw = "  Hello   World  "
    result = normalize_transcript(raw)

    assert isinstance(result, NormalizedTranscript)
    assert result.raw_transcript == raw
    assert result.raw_transcript == "  Hello   World  "  # never mutated


def test_english_extra_whitespace_collapsed():
    result = normalize_transcript("Truck   has    reached   the   warehouse")

    assert result.normalized_transcript == "Truck has reached the warehouse"


def test_leading_trailing_whitespace_and_newlines_stripped():
    result = normalize_transcript("\n\t  advance paid   ten thousand  \n")

    assert result.normalized_transcript == "advance paid ten thousand"


def test_hinglish_transcript_semantics_unchanged():
    raw = "bhai truck   RJ14-GB-1122   mein advance de diya"
    result = normalize_transcript(raw)

    assert result.normalized_transcript == "bhai truck RJ14GB1122 mein advance de diya"


def test_hindi_devanagari_text_preserved():
    raw = "गाड़ी   रवाना   हो   गई   है"
    result = normalize_transcript(raw)

    assert result.normalized_transcript == "गाड़ी रवाना हो गई है"
    # no characters dropped or reworded, only whitespace collapsed
    assert set(result.normalized_transcript.replace(" ", "")) == set(
        raw.replace(" ", "")
    )


def test_smart_quotes_and_dashes_normalized():
    raw = "party said “advance done” — balance pending"
    result = normalize_transcript(raw)

    assert result.normalized_transcript == 'party said "advance done" - balance pending'


def test_ellipsis_normalized():
    result = normalize_transcript("balance due… confirm later")

    assert result.normalized_transcript == "balance due... confirm later"


def test_unicode_nfd_input_normalized_to_nfc():
    # "e" + combining acute accent (NFD) should normalize to precomposed "é" (NFC)
    raw = "café truck driver"
    result = normalize_transcript(raw)

    assert result.normalized_transcript == "café truck driver"


def test_vehicle_number_hyphen_separators_collapsed():
    result = normalize_transcript("truck number is RJ14-GB-1122 confirmed")

    assert "RJ14GB1122" in result.normalized_transcript
    assert "-" not in result.normalized_transcript


def test_vehicle_number_already_joined_is_left_as_is():
    result = normalize_transcript("truck number is RJ14GB1122 confirmed")

    assert result.normalized_transcript == "truck number is RJ14GB1122 confirmed"


def test_vehicle_number_lowercase_letters_uppercased_in_match():
    result = normalize_transcript("gaadi rj14-gb-1122 hai")

    assert "RJ14GB1122" in result.normalized_transcript


def test_ambiguous_space_separated_groups_not_treated_as_vehicle_number():
    # Superficially matches (2 letters, digits, letters, digits) but is
    # ordinary free text, not a vehicle number written with a space
    # separator. Must not be collapsed -- that would change meaning.
    raw = "to 12 pm 2023 we will confirm"
    result = normalize_transcript(raw)

    assert result.normalized_transcript == raw


def test_malformed_partial_vehicle_number_not_altered():
    # Missing the trailing digit group -- not a complete, deterministic match.
    raw = "truck is RJ14-GB somewhere on the highway"
    result = normalize_transcript(raw)

    assert "RJ14-GB" in result.normalized_transcript
    assert result.normalized_transcript == raw


def test_empty_transcript():
    result = normalize_transcript("")

    assert result.raw_transcript == ""
    assert result.normalized_transcript == ""


def test_whitespace_only_transcript_normalizes_to_empty():
    result = normalize_transcript("   \n\t  ")

    assert result.normalized_transcript == ""


def test_does_not_infer_or_add_missing_information():
    raw = "advance de diya"
    result = normalize_transcript(raw)

    # No amount was ever mentioned; normalization must not invent one.
    assert result.normalized_transcript == raw
