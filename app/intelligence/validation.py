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


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _nfc_keys(mapping: dict) -> dict:
    """NFC-normalize every key of a word/phrase lookup table.

    A Devanagari nukta letter (e.g. ज़) can be typed/transcribed either
    precomposed (one codepoint) or decomposed (base consonant +
    combining nukta) -- visually identical, but a different codepoint
    sequence, so a table entry in one form silently never matches
    lookup text in the other. Every word/phrase table in this module
    is normalized through this (or ``_nfc`` for tuples) so it doesn't
    matter which form a given entry happened to be typed in.
    """
    return {_nfc(key): value for key, value in mapping.items()}


def _is_word_char(char: str) -> bool:
    """True for a letter, digit, underscore, or a combining mark.

    Python's ``\\w``/``\\b`` do not treat Unicode combining marks
    (category ``Mn``/``Mc``) as word characters. That breaks a plain
    ``\\b...\\b`` boundary check right at the end of any Devanagari
    word that ends in a dependent vowel sign -- which is extremely
    common in Hindi (e.g. "दिल्ली" ends in "ी", U+0940, category
    ``Mc``) -- because both the mark and the space/punctuation after it
    read as non-word, so no boundary transition is ever seen there.
    Treating marks as word-continuing fixes that without pulling in a
    new regex dependency.
    """
    category = unicodedata.category(char)
    return category[0] in ("L", "N", "M") or char == "_"


def _contains_as_word(haystack: str, needle: str) -> bool:
    """Whether ``needle`` occurs in ``haystack`` as a whole word.

    Equivalent in intent to ``re.search(rf"\\b{re.escape(needle)}\\b",
    haystack)``, but correct for Devanagari (and any other script using
    combining marks) -- see ``_is_word_char``.
    """
    if not needle:
        return False
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            return False
        before_ok = idx == 0 or not _is_word_char(haystack[idx - 1])
        after = idx + len(needle)
        after_ok = after == len(haystack) or not _is_word_char(haystack[after])
        if before_ok and after_ok:
            return True
        start = idx + 1

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


# A vehicle number is frequently spoken, not written -- spelled out one
# letter/digit at a time ("R J one four G B one one two two"), which is
# how STT will transcribe it whether the speaker used Hindi, English, or
# Hinglish letter/digit names. Recognizing this requires mapping each
# spoken letter-name and digit-word to its character, then collapsing a
# run of them back into the same compact form the compact-form regex
# above already knows how to find -- rather than a second, parallel
# vehicle-number grammar.
_PHONETIC_LETTER_WORDS: dict[str, str] = {
    "a": "A", "ए": "A", "e": "A", "ay": "A",
    "b": "B", "बी": "B", "bee": "B", "bi": "B",
    "c": "C", "सी": "C", "see": "C", "si": "C",
    "d": "D", "डी": "D", "dee": "D", "di": "D",
    "ee": "E", "ई": "E",
    "f": "F", "एफ": "F", "ef": "F",
    "g": "G", "जी": "G", "jee": "G", "ji": "G",
    "h": "H", "एच": "H", "ech": "H", "aitch": "H",
    "i": "I", "आई": "I", "aai": "I", "ai": "I",
    "j": "J", "जे": "J", "jay": "J", "je": "J",
    "k": "K", "के": "K", "kay": "K", "ke": "K",
    "l": "L", "एल": "L", "el": "L",
    "m": "M", "एम": "M", "em": "M",
    "n": "N", "एन": "N", "en": "N",
    "o": "O", "ओ": "O",
    "p": "P", "पी": "P", "pee": "P", "pi": "P",
    "q": "Q", "क्यू": "Q", "kyu": "Q", "kyoo": "Q",
    "r": "R", "आर": "R", "aar": "R", "ar": "R",
    "s": "S", "एस": "S", "es": "S",
    "t": "T", "टी": "T", "tee": "T", "ti": "T",
    "u": "U", "यू": "U", "yoo": "U", "you": "U",
    "v": "V", "वी": "V", "vee": "V", "vi": "V",
    "w": "W", "डब्ल्यू": "W", "dablyu": "W",
    "x": "X", "एक्स": "X", "eks": "X", "ex": "X",
    "y": "Y", "वाय": "Y", "why": "Y", "vai": "Y",
    "z": "Z", "ज़ेड": "Z", "zed": "Z", "ज़ी": "Z", "zee": "Z",
}
_PHONETIC_LETTER_WORDS = _nfc_keys(_PHONETIC_LETTER_WORDS)

_PHONETIC_DIGIT_WORDS: dict[str, str] = {
    # English-borrowed digit words, as spoken (Hinglish and Devanagari
    # transliteration) -- alongside the native Hindi cardinal words for
    # 1-9 (duplicated here rather than derived from _NUMBER_WORDS below,
    # since that table is defined later in this module) -- both are
    # common ways to spell out a vehicle number digit by digit.
    "zero": "0", "ज़ीरो": "0", "जीरो": "0", "शून्य": "0", "sifar": "0", "सिफ़र": "0",
    "one": "1", "वन": "1", "ek": "1", "एक": "1",
    "two": "2", "टू": "2", "do": "2", "दो": "2",
    "three": "3", "थ्री": "3", "teen": "3", "तीन": "3",
    "four": "4", "फोर": "4", "char": "4", "chaar": "4", "चार": "4",
    "five": "5", "फाइव": "5", "paanch": "5", "panch": "5", "पांच": "5", "पाँच": "5",
    "six": "6", "सिक्स": "6", "chhe": "6", "che": "6", "छह": "6",
    "seven": "7", "सेवन": "7", "saat": "7", "सात": "7",
    "eight": "8", "एट": "8", "aath": "8", "आठ": "8",
    "nine": "9", "नाइन": "9", "nau": "9", "नौ": "9",
}
_PHONETIC_DIGIT_WORDS = _nfc_keys(_PHONETIC_DIGIT_WORDS)


def _phonetic_char(token: str) -> str | None:
    normalized = _nfc(token.strip(".,;:!?()\"'")).lower()
    if normalized in _PHONETIC_LETTER_WORDS:
        return _PHONETIC_LETTER_WORDS[normalized]
    if normalized in _PHONETIC_DIGIT_WORDS:
        return _PHONETIC_DIGIT_WORDS[normalized]
    return None


def _delatinize_phonetic_spelling(transcript: str) -> str:
    """Collapse runs of spelled-out letter/digit words into compact tokens.

    "आर जे वन फोर जी बी वन वन टू टू" becomes a single "RJ14GB1122" token
    inserted in place of those ten words, so the existing compact-form
    vehicle-number regex can find it exactly as if it had been written
    that way. Only runs of four or more consecutive recognizable
    letter/digit words are collapsed, so an isolated word that happens
    to also be a letter/digit name (e.g. a stray "do"/"two") is left
    alone rather than being swept into an unrelated match. The letter
    run and digit run within a genuine vehicle-number mention are still
    naturally distinguished by the compact-form regex afterwards, since
    it requires the real Indian state-code + digit + letter + digit
    shape -- this step only makes that shape visible in the text.
    """
    tokens = transcript.split()
    collapsed: list[str] = []
    i, n = 0, len(tokens)
    while i < n:
        run: list[str] = []
        j = i
        while j < n:
            char = _phonetic_char(tokens[j])
            if char is None:
                break
            run.append(char)
            j += 1
        if len(run) >= 4:
            collapsed.append("".join(run))
            i = j
        else:
            collapsed.append(tokens[i])
            i += 1
    return " ".join(collapsed)


def _truck_numbers_mentioned_in(transcript: str) -> set[str]:
    found = {format_vehicle_number(*groups) for groups in _TRUCK_SEARCH_RE.findall(transcript)}
    phonetic_variant = _delatinize_phonetic_spelling(transcript)
    if phonetic_variant != transcript:
        found |= {
            format_vehicle_number(*groups)
            for groups in _TRUCK_SEARCH_RE.findall(phonetic_variant)
        }
    return found


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
    # 21-99: standard Hindi cardinal numbers, unlike 1-19/round-tens above
    # these are irregular compound words (not "twenty" + "five" the way
    # English is), so each needs its own table entry rather than being
    # derivable from the tens/units already above. Previously missing
    # entirely, which meant any spoken amount using one of these (e.g.
    # "pachees hazaar" / "पच्चीस हज़ार" = 25000) had no recognized number
    # word and could never be confirmed as evidence.
    "ikkees": 21, "इक्कीस": 21, "baais": 22, "बाईस": 22, "teis": 23, "तेईस": 23,
    "chaubees": 24, "चौबीस": 24, "pachees": 25, "pachis": 25, "पच्चीस": 25,
    "chhabbees": 26, "छब्बीस": 26, "sattaais": 27, "सत्ताईस": 27,
    "atthaais": 28, "अट्ठाईस": 28, "unatees": 29, "उनतीस": 29,
    "ikatees": 31, "इकतीस": 31, "battees": 32, "बत्तीस": 32,
    "taintees": 33, "तैंतीस": 33, "chauntees": 34, "चौंतीस": 34,
    "paintees": 35, "पैंतीस": 35, "chhattees": 36, "छत्तीस": 36,
    "saintees": 37, "सैंतीस": 37, "adatees": 38, "अड़तीस": 38,
    "unataalees": 39, "उनतालीस": 39,
    "iktalis": 41, "इकतालीस": 41, "bayaalees": 42, "बयालीस": 42,
    "taintalis": 43, "तैंतालीस": 43, "chavaalees": 44, "चवालीस": 44,
    "paintalis": 45, "पैंतालीस": 45, "chhiyaalees": 46, "छियालीस": 46,
    "saintalis": 47, "सैंतालीस": 47, "adtalis": 48, "अड़तालीस": 48,
    "unchas": 49, "उनचास": 49,
    "ikyaavan": 51, "इक्यावन": 51, "baavan": 52, "बावन": 52,
    "tirepan": 53, "तिरेपन": 53, "chauvan": 54, "चौवन": 54,
    "pachpan": 55, "पचपन": 55, "chhappan": 56, "छप्पन": 56,
    "sattaavan": 57, "सत्तावन": 57, "atthaavan": 58, "अट्ठावन": 58,
    "unsath": 59, "उनसठ": 59,
    "iksath": 61, "इकसठ": 61, "baasath": 62, "बासठ": 62,
    "tirsath": 63, "तिरसठ": 63, "chaunsath": 64, "चौंसठ": 64,
    "painsath": 65, "पैंसठ": 65, "chhiyaasath": 66, "छियासठ": 66,
    "sadsath": 67, "सड़सठ": 67, "adsath": 68, "अड़सठ": 68,
    "unhattar": 69, "उनहत्तर": 69,
    "ikhattar": 71, "इकहत्तर": 71, "bahattar": 72, "बहत्तर": 72,
    "tihattar": 73, "तिहत्तर": 73, "chauhattar": 74, "चौहत्तर": 74,
    "pachhattar": 75, "पचहत्तर": 75, "chhihattar": 76, "छिहत्तर": 76,
    "sathattar": 77, "सतहत्तर": 77, "athhattar": 78, "अठहत्तर": 78,
    "unaasee": 79, "उनासी": 79,
    "ikyaasee": 81, "इक्यासी": 81, "bayaasee": 82, "बयासी": 82,
    "tiraasee": 83, "तिरासी": 83, "chauraasee": 84, "चौरासी": 84,
    "pachaasee": 85, "पचासी": 85, "chhiyaasee": 86, "छियासी": 86,
    "sattaasee": 87, "सत्तासी": 87, "atthaasee": 88, "अट्ठासी": 88,
    "navaasee": 89, "नवासी": 89,
    "ikyaanave": 91, "इक्यानवे": 91, "baanave": 92, "बानवे": 92,
    "tiraanave": 93, "तिरानवे": 93, "chauraanave": 94, "चौरानवे": 94,
    "panchaanave": 95, "पंचानवे": 95, "chhiyaanave": 96, "छियानवे": 96,
    "sattaanave": 97, "सत्तानवे": 97, "atthaanave": 98, "अट्ठानवे": 98,
    "ninyaanave": 99, "निन्यानवे": 99,
}
_NUMBER_WORDS = _nfc_keys(_NUMBER_WORDS)

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
_MULTIPLIER_WORDS = _nfc_keys(_MULTIPLIER_WORDS)

_AMOUNT_TOKEN_RE = re.compile(r"^₹?(\d[\d,]*)([kK])?$")

_HEDGE_MARKERS = tuple(
    _nfc(m)
    for m in (
        "shayad", "shid", "maybe", "perhaps", "probably", "pata nahi", "patanahi",
        "not sure", "i think", "lagta hai", "शायद", "पता नहीं",
    )
)

_ADVANCE_KEYWORDS = tuple(_nfc(k) for k in ("advance", "एडवांस", "पेशगी"))
_BALANCE_KEYWORDS = tuple(
    _nfc(k)
    for k in ("balance", "बैलेंस", "baaki", "baki", "बाकी", "शेष", "due", "pending")
)
_ALL_MONEY_KEYWORDS = _ADVANCE_KEYWORDS + _BALANCE_KEYWORDS
_KEYWORD_ALTERNATION = "|".join(re.escape(k) for k in _ALL_MONEY_KEYWORDS)

# Non-comma delimiters always split. Commas are handled specially below
# (Python's `re` lookbehind must be fixed-width, and the keyword
# alternation isn't, so the comma guards are applied programmatically
# in `_split_clauses` rather than folded into this regex).
_DELIMITER_RE = re.compile(
    r",|[.;!?]|\blekin\b|\bbut\b|\baur\b|\band\b|और|लेकिन|\n", re.IGNORECASE
)

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
    if needle and _contains_as_word(haystack, needle):
        return _field(value, FieldStatus.VALID, evidence="party name appears in transcript")

    return _field(value, FieldStatus.INVALID, evidence="party name not found in transcript")


# Common Indian city/place names, Devanagari <-> Latin canonical
# spelling. Not exhaustive -- covers state capitals, major metros, and
# major logistics-corridor cities; a place outside this set still
# validates fine as long as the extracted value and the transcript
# agree on script. This exists because a destination is often spoken
# in Hindi (matching the transcript's Devanagari script) while the
# extractor may report it transliterated into Latin script (e.g.
# "Delhi" for a transcript that actually said "दिल्ली") -- without an
# equivalence table, a genuinely-stated destination would be marked
# unsupported purely because of a script mismatch, not because it
# wasn't actually said.
_CITY_NAME_PAIRS: tuple[tuple[str, str], ...] = (
    ("दिल्ली", "delhi"), ("मुंबई", "mumbai"), ("बॉम्बे", "bombay"),
    ("जयपुर", "jaipur"), ("कोलकाता", "kolkata"), ("चेन्नई", "chennai"),
    ("बेंगलुरु", "bengaluru"), ("बैंगलोर", "bangalore"), ("हैदराबाद", "hyderabad"),
    ("पुणे", "pune"), ("अहमदाबाद", "ahmedabad"), ("सूरत", "surat"),
    ("लखनऊ", "lucknow"), ("कानपुर", "kanpur"), ("नागपुर", "nagpur"),
    ("इंदौर", "indore"), ("भोपाल", "bhopal"), ("पटना", "patna"),
    ("वडोदरा", "vadodara"), ("लुधियाना", "ludhiana"), ("आगरा", "agra"),
    ("नासिक", "nashik"), ("फरीदाबाद", "faridabad"), ("मेरठ", "meerut"),
    ("राजकोट", "rajkot"), ("वाराणसी", "varanasi"), ("श्रीनगर", "srinagar"),
    ("अमृतसर", "amritsar"), ("इलाहाबाद", "allahabad"), ("प्रयागराज", "prayagraj"),
    ("रांची", "ranchi"), ("जोधपुर", "jodhpur"), ("कोयंबटूर", "coimbatore"),
    ("गुवाहाटी", "guwahati"), ("चंडीगढ़", "chandigarh"), ("गुरुग्राम", "gurugram"),
    ("गुड़गांव", "gurgaon"), ("नोएडा", "noida"), ("भुवनेश्वर", "bhubaneswar"),
    ("देहरादून", "dehradun"), ("रायपुर", "raipur"), ("जालंधर", "jalandhar"),
    ("कोटा", "kota"), ("तिरुवनंतपुरम", "thiruvananthapuram"), ("विजयवाड़ा", "vijayawada"),
    ("विशाखापत्तनम", "visakhapatnam"), ("मैसूर", "mysuru"), ("मदुरै", "madurai"),
    ("जमशेदपुर", "jamshedpur"), ("ग्वालियर", "gwalior"), ("औरंगाबाद", "aurangabad"),
    ("सेलम", "salem"), ("वारंगल", "warangal"), ("तिरुचिरापल्ली", "tiruchirappalli"),
)
_CITY_EQUIVALENTS: dict[str, str] = {}
for _devanagari, _latin in _CITY_NAME_PAIRS:
    _devanagari, _latin = _nfc(_devanagari), _nfc(_latin)
    _CITY_EQUIVALENTS[_devanagari] = _latin
    _CITY_EQUIVALENTS[_latin] = _devanagari


def _validate_destination(value: str | None, transcript: str) -> FieldValidation:
    if value is None:
        return _field(None, FieldStatus.NOT_STATED, evidence=None)

    needle = unicodedata.normalize("NFC", value).strip().lower()
    haystack = unicodedata.normalize("NFC", transcript).lower()

    candidates = {needle}
    equivalent = _CITY_EQUIVALENTS.get(needle)
    if equivalent:
        candidates.add(equivalent)

    for candidate in candidates:
        if candidate and _contains_as_word(haystack, candidate):
            return _field(value, FieldStatus.VALID, evidence="destination appears in transcript")

    return _field(value, FieldStatus.INVALID, evidence="destination not found in transcript")


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
    # Normalize once, up front: a Devanagari nukta letter (e.g. ज़) can
    # arrive either precomposed (one codepoint) or decomposed (base
    # consonant + combining nukta, two codepoints) -- visually and
    # semantically identical, but a different codepoint sequence, so a
    # transcript in one form would silently fail to match a number/
    # keyword table entry written in the other form. NFC canonicalizes
    # both to the same sequence. ``normalize_transcript`` (Phase 2C)
    # already does this before validation runs in the real pipeline,
    # but validate_extraction is also called directly (including by
    # tests), so it must not depend on that having already happened.
    transcript = unicodedata.normalize("NFC", transcript)

    party_name = _validate_party_name(extraction.party_name, transcript)
    truck_number = _validate_truck_number(extraction.truck_number, transcript)
    destination = _validate_destination(extraction.destination, transcript)
    advance_paid = _validate_money_field(extraction.advance_paid, transcript, _ADVANCE_KEYWORDS)
    balance_due = _validate_money_field(extraction.balance_due, transcript, _BALANCE_KEYWORDS)

    fields = (party_name, truck_number, destination, advance_paid, balance_due)
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
        destination=destination.value,
        advance_paid=advance_paid.value,
        balance_due=balance_due.value,
    )

    return ValidationResult(
        status=overall,
        extraction=validated_extraction,
        party_name=party_name,
        truck_number=truck_number,
        destination=destination,
        advance_paid=advance_paid,
        balance_due=balance_due,
        issues=issues,
    )
