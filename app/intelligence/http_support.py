"""Shared HTTP-adapter plumbing used by every Phase 2 external provider adapter.

Sarvam STT (``stt.py``), Groq/Qwen3 extraction (``extraction.py``), and
AI4Bharat IndicOCR (``ocr.py``) each call an external HTTP API under
the same operational policy: a lazily-created, injectable
``httpx.AsyncClient``, and bounded exponential backoff on
rate-limiting/server errors. This module is the single place that
policy lives, so a future change to it (e.g. adding jitter, honoring
``Retry-After``) only needs to be made once instead of three times.

What is deliberately NOT unified here: each adapter's own typed
exception hierarchy, its exact status-code-to-outcome mapping, and
whether a terminal failure is raised (``stt.py``/``extraction.py``) or
returned as data (``ocr.py``, by design -- see its module docstring).
Those are meaningful, adapter-specific choices, not accidental
duplication, so collapsing them would trade a real behavioral
distinction for surface-level uniformity.
"""

from __future__ import annotations

import httpx

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


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
