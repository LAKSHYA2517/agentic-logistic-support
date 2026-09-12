"""Logistics field extraction from a transcript, via Qwen3 on Groq.

Takes a transcript (normally the output of
``app.intelligence.normalization.normalize_transcript``) and returns a
``LogisticsExtraction`` with whatever fields were explicitly stated.
This module knows nothing about Shipment, WhatsApp, SQLite, or any
other Phase 1 concept -- its only job is text -> structured fields.

The extraction module depends on the ``ExtractionProvider`` protocol,
not on Groq directly, so the production implementation
(``GroqQwenExtractor``) can be swapped (e.g. for an evaluation
provider) without touching callers.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from app.config import AppSettings
from app.intelligence.exceptions import (
    ExtractionAuthenticationError,
    ExtractionConfigurationError,
    ExtractionError,
    ExtractionInvalidRequestError,
    ExtractionInvalidResponseError,
    ExtractionNetworkError,
    ExtractionProviderError,
    ExtractionRateLimitError,
    ExtractionTimeoutError,
)
from app.intelligence.http_support import (
    RETRYABLE_STATUS_CODES,
    HttpClientLifecycleMixin,
    backoff_delay_seconds,
)
from app.intelligence.models import LogisticsExtraction

GROQ_MODEL = "qwen/qwen3.8-27b"
PROVIDER_NAME = "groq"

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 0.5

_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "party_name": {"type": ["string", "null"]},
        "truck_number": {"type": ["string", "null"]},
        "advance_paid": {"type": ["integer", "null"]},
        "balance_due": {"type": ["integer", "null"]},
    },
    "required": ["party_name", "truck_number", "advance_paid", "balance_due"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """\
You extract logistics fields from a trucking-business voice-note transcript.

The transcript may be in Hindi, English, Hinglish, or code-mixed logistics
terminology (e.g. "bhada", "advance", "balance", "munshi", "gaadi").

Return ONLY the four fields defined by the schema:
- party_name: the name of the party/customer mentioned, if any.
- truck_number: the vehicle registration number mentioned, if any. Report
  it in compact canonical form (uppercase letters and digits only, no
  spaces or hyphens), preserving exactly the characters that were stated.
- advance_paid: an amount paid in advance, as an integer, if explicitly
  stated.
- balance_due: an amount still owed/pending, as an integer, if explicitly
  stated.

Strict rules:
1. Extract ONLY information explicitly present in the transcript. Never
   guess, infer, or fill in a value that was not actually said.
2. If a field is not explicitly mentioned, its value MUST be null.
3. Do not treat hedged, uncertain, or speculative statements (e.g. "shayad",
   "maybe", "I think") as confirmed facts. If the speaker expresses doubt
   about a value, treat that value as not reliably stated and return null
   for it rather than inventing a number.
4. Only convert spoken amounts to integers when the amount is unambiguous
   (e.g. "das hazaar" -> 10000, "10k" -> 10000, "₹10,000" -> 10000). If the
   amount is unclear or not stated, return null.
5. Do not add any fields beyond the four defined in the schema.
6. Do not perform any calculation, aggregation, or correction beyond
   reading what was explicitly said.
"""


class ExtractionProvider(Protocol):
    """Interface the rest of Phase 2 depends on, not any concrete provider."""

    async def extract(self, transcript: str) -> LogisticsExtraction: ...


class GroqQwenExtractor(HttpClientLifecycleMixin):
    """Extraction provider backed by Qwen3 served through Groq.

    Uses Groq's OpenAI-compatible chat completions endpoint with strict
    JSON Schema structured outputs. An ``httpx.AsyncClient`` can be
    injected (e.g. built with a ``httpx.MockTransport``) so unit tests
    never hit the network.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str = GROQ_MODEL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = AppSettings()
        self._api_key = api_key or settings.groq_api_key
        if not self._api_key:
            raise ExtractionConfigurationError(
                "GROQ_API_KEY environment variable is not set"
            )
        self._base_url = base_url or settings.groq_chat_completions_url
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._http_client = http_client
        self._owns_client = http_client is None

    async def extract(self, transcript: str) -> LogisticsExtraction:
        """Extract logistics fields from a transcript via Groq/Qwen3.

        Raises:
            ExtractionInvalidRequestError: provider rejected the request (400).
            ExtractionAuthenticationError: invalid/missing credentials (401/403).
            ExtractionRateLimitError: rate limited and retries exhausted (429).
            ExtractionProviderError: provider failed persistently (5xx).
            ExtractionTimeoutError: request timed out and retries exhausted.
            ExtractionNetworkError: network failure and retries exhausted.
            ExtractionInvalidResponseError: response body was malformed/unusable
                or did not satisfy the ``LogisticsExtraction`` schema.
        """
        client = await self._get_client()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "logistics_extraction",
                    "schema": _JSON_SCHEMA,
                    "strict": True,
                },
            },
        }

        last_error: ExtractionError | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await client.post(self._base_url, headers=headers, json=body)
            except httpx.TimeoutException as exc:
                last_error = ExtractionTimeoutError(f"Groq request timed out: {exc}")
            except httpx.RequestError as exc:
                last_error = ExtractionNetworkError(f"Groq request failed: {exc}")
            else:
                result = self._handle_response(response)
                if isinstance(result, LogisticsExtraction):
                    return result
                last_error = result

            if attempt < self._max_retries:
                await asyncio.sleep(backoff_delay_seconds(attempt, self._backoff_base_seconds))
                continue

        assert last_error is not None
        raise last_error

    def _handle_response(
        self, response: httpx.Response
    ) -> LogisticsExtraction | ExtractionError:
        """Return a LogisticsExtraction on success, or a retryable error.

        Non-retryable failures (400/401/403) are raised immediately.
        """
        status = response.status_code

        if status == 200:
            return self._parse_success(response)

        if status == 400:
            raise ExtractionInvalidRequestError(
                f"Groq rejected the request (400): {response.text}"
            )
        if status in (401, 403):
            raise ExtractionAuthenticationError(
                f"Groq authentication failed ({status}): {response.text}"
            )
        if status == 429:
            return ExtractionRateLimitError(
                f"Groq rate limit exceeded (429): {response.text}"
            )
        if status in RETRYABLE_STATUS_CODES:
            return ExtractionProviderError(
                f"Groq provider error ({status}): {response.text}"
            )

        raise ExtractionInvalidResponseError(
            f"Unexpected Groq response status {status}: {response.text}"
        )

    def _parse_success(self, response: httpx.Response) -> LogisticsExtraction:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ExtractionInvalidResponseError(
                f"Groq response was not valid JSON: {exc}"
            ) from exc

        content = self._extract_message_content(payload)

        try:
            fields: Any = json.loads(content)
        except (ValueError, TypeError) as exc:
            raise ExtractionInvalidResponseError(
                f"Groq structured output was not valid JSON: {exc}"
            ) from exc

        try:
            return LogisticsExtraction.model_validate(fields)
        except ValidationError as exc:
            raise ExtractionInvalidResponseError(
                f"Groq structured output did not match LogisticsExtraction schema: {exc}"
            ) from exc

    @staticmethod
    def _extract_message_content(payload: Any) -> str:
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExtractionInvalidResponseError(
                f"Groq response missing expected choices/message/content: {payload!r}"
            ) from exc


_default_provider: ExtractionProvider | None = None


def _get_default_provider() -> ExtractionProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = GroqQwenExtractor()
    return _default_provider


async def extract_logistics_data(transcript: str) -> LogisticsExtraction:
    """Stable Phase 2D integration point: transcript -> structured fields.

    Reads ``GROQ_API_KEY`` from the environment on first use. Delegates
    to the configured ``ExtractionProvider`` (Qwen3 via Groq in
    production); callers do not need to know about the Groq SDK/API.
    """
    provider = _get_default_provider()
    return await provider.extract(transcript)
