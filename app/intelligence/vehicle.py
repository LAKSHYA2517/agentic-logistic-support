"""Shared Indian vehicle-number regex fragment and formatter.

``normalization.py`` (whole-transcript, hyphen-only separators -- see
its own module for why a bare space is deliberately excluded there)
and ``validation.py`` (isolated single-token checks, hyphen-or-space
separators) each need to recognize the same underlying vehicle-number
shape but apply different separator strictness. Previously each module
hardcoded its own copy of the 4-group pattern, which could silently
drift out of sync (e.g. one gaining support for a new plate format
without the other). This module is the single source of truth for the
group shape and the canonical-form formatter; only the separator
policy is left to each caller.
"""

from __future__ import annotations

import re

# Indian state/union-territory RTO codes: a closed, well-known set.
# Restricting the "state" group to these (instead of any 2 letters)
# is what makes it safe to scan whole, free-flowing transcript text
# for vehicle-number mentions -- an ordinary two-letter word like "to"
# or "in" followed by digits/letters/digits (e.g. "to 12 pm 2023")
# can no longer be mistaken for a vehicle number, because "TO" and
# "IN" are not RTO codes, while a real code like "RJ" or "MH" still is.
STATE_CODES = frozenset(
    {
        "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DL", "DN", "GA", "GJ",
        "HR", "HP", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
        "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UA",
        "UK", "UP", "WB",
    }
)

_STATE_CODE_PATTERN = "|".join(sorted(STATE_CODES))


def vehicle_number_groups(sep: str) -> str:
    """Build the 4-group vehicle-number pattern body, joined by ``sep``.

    Shape: 2-letter RTO state/UT code - 1-2 digits (RTO) - 1-2 letters
    (series) - 1-4 digits (number). The state group is restricted to
    ``STATE_CODES`` rather than any 2 letters, which is what keeps
    whole-transcript scanning safe (see module docstring). ``sep`` is
    a regex fragment describing what may appear *between* consecutive
    groups (e.g. ``r"-?"`` or ``r"\\s*[-\\s]?\\s*"``); callers add
    their own anchors/word boundaries and flags around the result.
    """
    return (
        rf"({_STATE_CODE_PATTERN})" + sep
        + r"(\d{1,2})" + sep
        + r"([A-Za-z]{1,2})" + sep
        + r"(\d{1,4})"
    )


def format_vehicle_number(state: str, rto: str, series: str, number: str) -> str:
    """Canonical form: uppercase letters, groups joined with no separator."""
    return f"{state.upper()}{rto}{series.upper()}{number}"
