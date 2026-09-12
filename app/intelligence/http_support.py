"""Shared HTTP-adapter plumbing for Phase 2's direct HTTP integrations.

Sarvam STT (``stt.py``) and Groq/Qwen3 extraction (``extraction.py``)
call external HTTP APIs under the same operational policy: a lazily-created, injectable
``httpx.AsyncClient``, and bounded exponential backoff on
rate-limiting/server errors. Sarvam Vision uses Sarvam's official SDK, but
shares the credential-safe error sanitizer defined here.

What is deliberately NOT unified here: each adapter's own typed
exception hierarchy, its exact status-code-to-outcome mapping, and
whether a terminal failure is raised (``stt.py``/``extraction.py``) or
returned as data (``ocr.py``).
Those are meaningful, adapter-specific choices, not accidental
duplication, so collapsing them would trade a real behavioral
distinction for surface-level uniformity.
"""

from __future__ import annotations

import os
import re

import httpx

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def sanitize_provider_message(message: str) -> str:
    """Redact configured credentials and URLs from provider failure text."""

    safe_message = " ".join(message.split())
    for variable in (
        "META_ACCESS_TOKEN",
        "SARVAM_API_KEY",
        "GROQ_API_KEY",
    ):
        secret = os.getenv(variable)
        if secret:
            safe_message = safe_message.replace(secret, "<redacted>")
    safe_message = re.sub(
        r"(?i)\b(bearer|token|api[_ -]?key)\s*[:=]?\s*[^\s,;]+",
        r"\1 <redacted>",
        safe_message,
    )
    safe_message = re.sub(r"https?://\S+", "<url>", safe_message)
    return safe_message[:1000]


def backoff_delay_seconds(attempt: int, backoff_base_seconds: float) -> float:
    """Bounded exponential backoff delay for retry attempt ``attempt`` (0-indexed)."""
    return backoff_base_seconds * (2**attempt)


class HttpClientLifecycleMixin:
    """Lazy, injectable ``httpx.AsyncClient`` management.

    The including class must set ``self._timeout``, ``self._http_client``
    (an injected client, or ``None``), and ``self._owns_client =
    self._http_client is None`` in its own ``__init__`` before these
    methods are used.
    """

    _timeout: float
    _http_client: httpx.AsyncClient | None
    _owns_client: bool

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self._timeout)
        return self._http_client

    async def aclose(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
