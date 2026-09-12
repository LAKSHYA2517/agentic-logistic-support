"""Sarvam speech-to-text adapter.

Converts a local .ogg audio file into a transcript using Sarvam's
Saaras v3 model. This module knows nothing about Shipment, WhatsApp,
or any other part of the system -- its only job is audio -> transcript.

Provider-specific HTTP details (endpoint, headers, multipart shape,
status-code handling, retry policy) are fully contained in
``SarvamSTTAdapter``. Callers should use the module-level ``transcribe``
function, which is the one stable integration point documented at the
bottom of this file.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from app.intelligence.config import get_sarvam_api_key, get_sarvam_stt_url
from app.intelligence.exceptions import (
    SttAuthenticationError,
    SttError,
    SttInvalidRequestError,
    SttInvalidResponseError,
    SttNetworkError,
    SttProviderError,
    SttRateLimitError,
    SttTimeoutError,
)
from app.intelligence.http_support import (
    RETRYABLE_STATUS_CODES,
    HttpClientLifecycleMixin,
    backoff_delay_seconds,
)
from app.intelligence.models import STTResult

SARVAM_MODEL = "saaras:v3"
SARVAM_MODE = "codemix"
PROVIDER_NAME = "sarvam"

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 0.5


class SarvamSTTAdapter(HttpClientLifecycleMixin):
    """Adapter encapsulating all Sarvam-specific STT logic.

    An ``httpx.AsyncClient`` can be injected (e.g. built with a
    ``httpx.MockTransport``) so unit tests never hit the network.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key or get_sarvam_api_key()
        self._base_url = base_url or get_sarvam_stt_url()
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._http_client = http_client
        self._owns_client = http_client is None

    async def transcribe(
        self,
        file_path: str,
        keyterms: list[str] | None = None,
    ) -> STTResult:
        """Transcribe a local .ogg file via Sarvam Saaras v3.

        Raises:
            SttInvalidRequestError: provider rejected the request (400).
            SttAuthenticationError: invalid/missing credentials (401/403).
            SttRateLimitError: rate limited and retries exhausted (429).
            SttProviderError: provider failed persistently (5xx).
            SttTimeoutError: request timed out and retries exhausted.
            SttNetworkError: network failure and retries exhausted.
            SttInvalidResponseError: response body was malformed/unusable.
        """
        path = Path(file_path)
        try:
            audio_bytes = path.read_bytes()
        except OSError as exc:
            raise SttInvalidRequestError(f"Unable to read audio file: {exc}") from exc

        client = await self._get_client()
        headers = {"api-subscription-key": self._api_key}
        data = {"model": SARVAM_MODEL, "mode": SARVAM_MODE}
        if keyterms:
            data["keyterms"] = ",".join(keyterms)

        last_error: SttError | None = None

        for attempt in range(self._max_retries + 1):
            files = {"file": (path.name, audio_bytes, "audio/ogg")}
            try:
                response = await client.post(
                    self._base_url, headers=headers, data=data, files=files
                )
            except httpx.TimeoutException as exc:
                last_error = SttTimeoutError(f"Sarvam request timed out: {exc}")
            except httpx.RequestError as exc:
                last_error = SttNetworkError(f"Sarvam request failed: {exc}")
            else:
                result = self._handle_response(response)
                if isinstance(result, STTResult):
                    return result
                last_error = result

            if attempt < self._max_retries:
                await asyncio.sleep(backoff_delay_seconds(attempt, self._backoff_base_seconds))
                continue

        assert last_error is not None
        raise last_error

    def _handle_response(self, response: httpx.Response) -> STTResult | SttError:
        """Return an STTResult on success, or a retryable error to raise/retry.

        Non-retryable failures (400/401/403) are raised immediately.
        """
        status = response.status_code

        if status == 200:
            return self._parse_success(response)

        if status == 400:
            raise SttInvalidRequestError(
                f"Sarvam rejected the request (400): {response.text}"
            )
        if status in (401, 403):
            raise SttAuthenticationError(
                f"Sarvam authentication failed ({status}): {response.text}"
            )
        if status == 429:
            return SttRateLimitError(f"Sarvam rate limit exceeded (429): {response.text}")
        if status in RETRYABLE_STATUS_CODES:
            return SttProviderError(
                f"Sarvam provider error ({status}): {response.text}"
            )

        raise SttInvalidResponseError(
            f"Unexpected Sarvam response status {status}: {response.text}"
        )

    def _parse_success(self, response: httpx.Response) -> STTResult:
        try:
            payload = response.json()
        except ValueError as exc:
            raise SttInvalidResponseError(
                f"Sarvam response was not valid JSON: {exc}"
            ) from exc

        if not isinstance(payload, dict) or "transcript" not in payload:
            raise SttInvalidResponseError(
                f"Sarvam response missing 'transcript' field: {payload!r}"
            )

        transcript = payload["transcript"]
        if not isinstance(transcript, str):
            raise SttInvalidResponseError(
                f"Sarvam 'transcript' field was not a string: {transcript!r}"
            )

        return STTResult(
            transcript=transcript,
            provider=PROVIDER_NAME,
            model=SARVAM_MODEL,
            language_code=payload.get("language_code"),
            request_id=payload.get("request_id"),
        )


_default_adapter: SarvamSTTAdapter | None = None


def _get_default_adapter() -> SarvamSTTAdapter:
    global _default_adapter
    if _default_adapter is None:
        _default_adapter = SarvamSTTAdapter()
    return _default_adapter


async def transcribe(file_path: str, keyterms: list[str] | None = None) -> STTResult:
    """Stable Phase 2B integration point: audio file -> transcript.

    Reads ``SARVAM_API_KEY`` (required) and ``SARVAM_STT_URL``
    (optional, defaults to the production endpoint) from the
    environment on first use. See the module docstring and README for
    the full contract.
    """
    adapter = _get_default_adapter()
    return await adapter.transcribe(file_path, keyterms=keyterms)
