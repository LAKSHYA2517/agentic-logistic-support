"""Deterministic transcript normalization.

Takes the raw transcript produced by the Phase 2B STT adapter
(``app.intelligence.stt``) and applies purely mechanical cleanup:
Unicode form, whitespace, punctuation, and vehicle-number separator
normalization. It never calls an LLM, never infers missing content,
and never changes what the transcript means.

This module knows nothing about Shipment, WhatsApp, Qwen, Groq, or
Claude -- its only job is text -> cleaner text.
"""

from __future__ import annotations

import re
import unicodedata

from app.intelligence.models import NormalizedTranscript
from app.intelligence.vehicle import format_vehicle_number, vehicle_number_groups

# Curly/typographic punctuation mapped to their plain ASCII equivalents.
# This only changes glyph shape, never wording.
_PUNCTUATION_MAP = {
    "‘": "'",  # left single quote
    "’": "'",  # right single quote
    "‚": "'",  # single low-9 quote
    "“": '"',  # left double quote
    "”": '"',  # right double quote
    "„": '"',  # double low-9 quote
    "–": "-",  # en dash
    "—": "-",  # em dash
    "…": "...",  # ellipsis
}

_WHITESPACE_RE = re.compile(r"\s+")

# Indian vehicle-number pattern, group-by-group:
#   2 letters (state) - 1-2 digits (RTO) - 1-2 letters (series) - 1-4 digits (number)
# Separators between groups may only be a hyphen (optionally padded with
# spaces) or nothing at all -- deliberately NOT a bare space. Allowing a
# bare space as a separator would make this fire on ordinary sentences
# that happen to contain a two-letter word followed by digits/letters/
# digits (e.g. "to 12 pm 2023"), silently mangling unrelated text. A
# hyphen is a strong, low-ambiguity signal that the writer intended a
# single structured token, so only that case is collapsed.
_SEP = r"(?:\s*-\s*)?"
_VEHICLE_NUMBER_RE = re.compile(rf"\b{vehicle_number_groups(_SEP)}\b", re.IGNORECASE)


def _normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _normalize_punctuation(text: str) -> str:
    for original, replacement in _PUNCTUATION_MAP.items():
        text = text.replace(original, replacement)
    return text


def _normalize_vehicle_number_separators(text: str) -> str:
    def _collapse(match: re.Match[str]) -> str:
        return format_vehicle_number(*match.groups())

    return _VEHICLE_NUMBER_RE.sub(_collapse, text)


def _normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalize_transcript(text: str) -> NormalizedTranscript:
    """Deterministically normalize a raw STT transcript.

    Applies, in order: Unicode NFC normalization, punctuation
    normalization, vehicle-number separator collapsing, and whitespace
    normalization. Does not touch case of ordinary words, does not
    translate or reword anything, and does not attempt to interpret
    ambiguous or malformed text.
    """
    normalized = _normalize_unicode(text)
    normalized = _normalize_punctuation(normalized)
    normalized = _normalize_vehicle_number_separators(normalized)
    normalized = _normalize_whitespace(normalized)

    return NormalizedTranscript(raw_transcript=text, normalized_transcript=normalized)
