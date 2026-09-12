"""Deterministic validation of a ``LogisticsExtraction`` against its transcript.

This is the anti-hallucination boundary described in the Phase 2
architecture: a value is never trusted just because an LLM returned it
in valid JSON. Every non-null field is checked against the transcript
it was supposedly extracted from, using only regex/string rules -- no
LLM is called here, and none of this module's logic is probabilistic.

This module takes plain ``LogisticsExtraction``/``str`` inputs and
returns a plain ``ValidationResult``. It has no dependency on SQLite,
Shipment, WhatsApp, FastAPI, the Groq SDK, the Sarvam SDK, or Claude.
"""

from __future__ import annotations

import re
import unicodedata

from app.intelligence.models import (
    FieldStatus,
    FieldValidation,
    LogisticsExtraction,
    ValidationResult,
    ValidationStatus,
)
from app.intelligence.vehicle import format_vehicle_number, vehicle_number_groups

# ---------------------------------------------------------------------------
# Vehicle number
# ---------------------------------------------------------------------------

# Indian vehicle-number shape, group-by-group:
#   2-letter RTO state/UT code - 1-2 digits (RTO) - 1-2 letters (series) - 1-4 digits (number)
#
# Both the isolated-value check and the whole-transcript scan accept a
# hyphen, a bare space, or nothing as the separator between groups.
# Accepting a bare space when scanning the *whole transcript* would
# normally risk false positives (an ordinary "two-letter-word + digits
# + letters + digits" phrase, e.g. "to 12 pm 2023", shape-matching a
# vehicle number) -- but ``vehicle_number_groups`` restricts the first
# group to real Indian state/UT codes (``STATE_CODES`` in
# ``vehicle.py``), and "TO" is not one, so that class of false
# positive can't occur here even with the permissive separator. A
# bare space is also the common case for how a spoken truck number
# actually surfaces in a transcript (e.g. "RJ 14 GB 1122"), so keeping
# it permissive is necessary, not just convenient.
_TRUCK_SEP = r"\s*-?\s*"
_TRUCK_FULL_RE = re.compile(rf"^\s*{vehicle_number_groups(_TRUCK_SEP)}\s*$", re.IGNORECASE)
_TRUCK_SEARCH_RE = re.compile(rf"\b{vehicle_number_groups(_TRUCK_SEP)}\b", re.IGNORECASE)


def normalize_truck_number(value: str) -> str | None:
    """Collapse a vehicle number's separators into its canonical form.

    Returns ``None`` if the value does not match the deterministic
    Indian vehicle-number shape -- this function never invents
    characters or guesses at a malformed value.
    """
    match = _TRUCK_FULL_RE.match(value)
    if not match:
        return None
    return format_vehicle_number(*match.groups())


def _truck_numbers_mentioned_in(transcript: str) -> set[str]:
    return {format_vehicle_number(*groups) for groups in _TRUCK_SEARCH_RE.findall(transcript)}


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

# A deliberately small, deterministic Hindi/Hinglish number-word table.
# This is not a general natural-language number parser -- it exists
# only so the validator can check whether a transcript plausibly
# supports a specific already-extracted integer, never to extract new
# amounts itself.
_NUMBER_WORDS: dict[str, int] = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9,
    "das": 10, "dus": 10, "gyarah": 11, "barah": 12, "baarah": 12, "terah": 13,
    "chaudah": 14, "pandrah": 15, "solah": 16, "satrah": 17, "atharah": 18,
    "unnees": 19, "bees": 20, "tees": 30, "chalis": 40, "chaalis": 40,
    "pachas": 50, "pachaas": 50, "saath": 60, "sattar": 70, "assi": 80,
    "nabbe": 90, "sau": 100,
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6,
    "सात": 7, "आठ": 8, "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12,
    "तेरह": 13, "चौदह": 14, "पंद्रह": 15, "सोलह": 16, "सत्रह": 17,
    "अठारह": 18, "उन्नीस": 19, "बीस": 20, "तीस": 30, "चालीस": 40,
    "पचास": 50, "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90, "सौ": 100,
}

_MULTIPLIER_WORDS: dict[str, int] = {
    "hazaar": 1_000, "hazar": 1_000, "hajar": 1_000,
    "lakh": 100_000, "lac": 100_000,
    "crore": 10_000_000,
    "sau": 100,
    "हज़ार": 1_000, "हजार": 1_000,
    "लाख": 100_000,
    "करोड़": 10_000_000,
    "सौ": 100,
}

_AMOUNT_TOKEN_RE = re.compile(r"^₹?(\d[\d,]*)([kK])?$")

_HEDGE_MARKERS = (
    "shayad", "shid", "maybe", "perhaps", "probably", "pata nahi", "patanahi",
    "not sure", "i think", "lagta hai", "शायद", "पता नहीं",
)

_ADVANCE_KEYWORDS = ("advance", "एडवांस", "पेशगी")
_BALANCE_KEYWORDS = ("balance", "baaki", "baki", "बाकी", "शेष", "due", "pending")
_ALL_MONEY_KEYWORDS = _ADVANCE_KEYWORDS + _BALANCE_KEYWORDS
_KEYWORD_ALTERNATION = "|".join(re.escape(k) for k in _ALL_MONEY_KEYWORDS)

# Non-comma delimiters always split. Commas are handled specially below
# (Python's `re` lookbehind must be fixed-width, and the keyword
# alternation isn't, so the comma guards are applied programmatically
# in `_split_clauses` rather than folded into this regex).
_DELIMITER_RE = re.compile(r",|[.;!?]|\blekin\b|\bbut\b|\baur\b|\band\b|\n", re.IGNORECASE)

# A comma only counts as a clause separator when it is not:
#   - acting as a thousands-grouping separator inside a number (e.g. the
#     comma in "10,000" must not split the clause and sever the amount
#     in two), or
#   - sitting immediately after a money keyword (e.g. "advance, 10000
#     diya tha" must not be severed into a keyword-only clause and an
#     amount-only clause that then can't see each other -- a keyword
#     followed by a comma is normally just a spoken pause, not a
#     boundary between two different concepts).
_KEYWORD_SUFFIX_RE = re.compile(rf"\b(?:{_KEYWORD_ALTERNATION})\s*$", re.IGNORECASE)


def _split_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    start = 0
    for match in _DELIMITER_RE.finditer(text):
        if match.group() == ",":
            before_char = text[match.start() - 1 : match.start()]
            after_char = text[match.end() : match.end() + 1]
            digit_grouping = before_char.isdigit() and after_char.isdigit()
            keyword_adjacent = bool(_KEYWORD_SUFFIX_RE.search(text[: match.start()]))
            if digit_grouping or keyword_adjacent:
                continue
        clauses.append(text[start : match.start()])
        start = match.end()
    clauses.append(text[start:])
    return clauses


def _tokenize(text: str) -> list[str]:
    return text.split()


def _extract_amount_candidates(text: str) -> set[int]:
    """Deterministically find explicit amounts mentioned in ``text``.

    Digit tokens (optionally ₹-prefixed, comma-grouped, or k-suffixed)
    and known Hindi/Hinglish number words are recognized. Tokens that
    mix letters and digits (e.g. a vehicle number like "RJ14GB1122")
    never match the digit-amount pattern, so vehicle numbers cannot be
    mistaken for monetary amounts.
    """
    candidates: set[int] = set()
    raw_tokens = _tokenize(text)

    for raw in raw_tokens:
        stripped = raw.strip(".,;:!?()\"'")
        match = _AMOUNT_TOKEN_RE.match(stripped)
        if not match:
            continue
        digits = match.group(1).replace(",", "")
        if not digits:
            continue
        value = int(digits)
        if match.group(2):
            value *= 1000
        candidates.add(value)

    normalized_tokens = [t.strip(".,;:!?()\"'").lower() for t in raw_tokens]
    i, n = 0, len(normalized_tokens)
    while i < n:
        tok = normalized_tokens[i]
        unit = _NUMBER_WORDS.get(tok)
        if unit is not None:
            if i + 1 < n and normalized_tokens[i + 1] in _MULTIPLIER_WORDS:
                candidates.add(unit * _MULTIPLIER_WORDS[normalized_tokens[i + 1]])
                i += 2
                continue
            candidates.add(unit)
            i += 1
            continue
        if tok in _MULTIPLIER_WORDS:
            candidates.add(_MULTIPLIER_WORDS[tok])
        i += 1

    return candidates


def _contains_hedge(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _HEDGE_MARKERS)


def _relevant_clauses(text: str, keywords: tuple[str, ...]) -> str:
    clauses = _split_clauses(text)
    matching = [c for c in clauses if any(kw.lower() in c.lower() for kw in keywords)]
    return " ".join(matching)


# ---------------------------------------------------------------------------
# Field validators
# ---------------------------------------------------------------------------


def _field(
    value: object,
    status: FieldStatus,
    evidence: str | None,
    normalized_value: str | None = None,
) -> FieldValidation:
    return FieldValidation(
        value=value,
        status=status,
        evidence=evidence,
        normalized_value=normalized_value,
    )


def _validate_party_name(value: str | None, transcript: str) -> FieldValidation:
    if value is None:
        return _field(None, FieldStatus.NOT_STATED, evidence=None)

    needle = unicodedata.normalize("NFC", value).strip().lower()
    haystack = unicodedata.normalize("NFC", transcript).lower()

    # A bare substring test would let "Ram" false-positive-match inside
    # "Raman" (a different person) -- require the name to appear as a
    # whole word (or word sequence), not merely as a substring of a
    # longer word.
    if needle and re.search(rf"\b{re.escape(needle)}\b", haystack):
        return _field(value, FieldStatus.VALID, evidence="party name appears in transcript")

    return _field(value, FieldStatus.INVALID, evidence="party name not found in transcript")


def _validate_truck_number(value: str | None, transcript: str) -> FieldValidation:
    if value is None:
        return _field(None, FieldStatus.NOT_STATED, evidence=None, normalized_value=None)

    normalized = normalize_truck_number(value)
    if normalized is None:
        return _field(
            value,
            FieldStatus.INVALID,
            evidence="does not match a deterministic Indian vehicle-number pattern",
            normalized_value=None,
        )

    mentioned = _truck_numbers_mentioned_in(transcript)
    if normalized in mentioned:
        return _field(
            value,
            FieldStatus.VALID,
            evidence=f"matches vehicle number mentioned in transcript ({normalized})",
            normalized_value=normalized,
        )

    return _field(
        value,
        FieldStatus.INVALID,
        evidence="vehicle number not found in transcript",
        normalized_value=normalized,
    )


def _validate_money_field(
    value: int | None, transcript: str, keywords: tuple[str, ...]
) -> FieldValidation:
    if value is None:
        return _field(None, FieldStatus.NOT_STATED, evidence=None)

    if value < 0:
        return _field(
            value,
            FieldStatus.INVALID,
            evidence=f"amount {value} is negative; monetary values must be >= 0",
        )

    relevant_text = _relevant_clauses(transcript, keywords)
    if not relevant_text.strip():
        return _field(
            value,
            FieldStatus.INVALID,
            evidence="no mention of this field's context found in transcript",
        )

    if _contains_hedge(relevant_text):
        return _field(
            value,
            FieldStatus.NEEDS_REVIEW,
            evidence="transcript expresses uncertainty about this amount",
        )

    candidates = _extract_amount_candidates(relevant_text)

    if len(candidates) > 1:
        return _field(
            value,
            FieldStatus.NEEDS_REVIEW,
            evidence=(
                f"transcript mentions multiple differing amounts {sorted(candidates)}; "
                "cannot confirm which one applies"
            ),
        )

    if value in candidates:
        return _field(
            value,
            FieldStatus.VALID,
            evidence=f"matches amount mentioned in transcript ({value})",
        )

    return _field(value, FieldStatus.INVALID, evidence="amount not supported by transcript")


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def validate_extraction(extraction: LogisticsExtraction, transcript: str) -> ValidationResult:
    """Deterministically validate every field of ``extraction`` against ``transcript``.

    Passing Pydantic/JSON-Schema validation at extraction time is not
    enough on its own: this function re-checks format (truck number),
    domain constraints (non-negative money), and -- critically --
    whether the transcript actually supports each non-null value.
    """
    party_name = _validate_party_name(extraction.party_name, transcript)
    truck_number = _validate_truck_number(extraction.truck_number, transcript)
    advance_paid = _validate_money_field(extraction.advance_paid, transcript, _ADVANCE_KEYWORDS)
    balance_due = _validate_money_field(extraction.balance_due, transcript, _BALANCE_KEYWORDS)

    fields = (party_name, truck_number, advance_paid, balance_due)
    issues = [f.evidence for f in fields if not f.valid and f.evidence]

    all_valid = all(f.valid for f in fields)
    any_confirmed = any(f.status == FieldStatus.VALID for f in fields)

    if all_valid and any_confirmed:
        overall = ValidationStatus.ACCEPTED
    else:
        overall = ValidationStatus.NEEDS_REVIEW
        if all_valid and not any_confirmed:
            # Every field is NOT_STATED: nothing was extracted at all.
            # That is not the same as everything being positively
            # confirmed, so it must not auto-accept -- a human should
            # see that this voice note yielded no usable information.
            issues.append("no logistics information was extracted from the transcript")

    # Carry the validated extraction forward with normalized values
    # substituted where available (currently truck_number), so
    # downstream consumers never need to reconstruct it from
    # individual FieldValidation.value's and risk dropping
    # normalization in the process.
    validated_extraction = LogisticsExtraction(
        party_name=party_name.value,
        truck_number=truck_number.normalized_value or truck_number.value,
        advance_paid=advance_paid.value,
        balance_due=balance_due.value,
    )

    return ValidationResult(
        status=overall,
        extraction=validated_extraction,
        party_name=party_name,
        truck_number=truck_number,
        advance_paid=advance_paid,
        balance_due=balance_due,
        issues=issues,
    )
