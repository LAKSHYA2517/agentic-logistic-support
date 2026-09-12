"""Primary OCR: AI4Bharat IndicOCR, behind a provider-agnostic interface.

    IMAGE / DOCUMENT
           |
    AI4BHARAT INDICOCR
           |
      OCRResult
           |
    evaluate_ocr_quality()
           |
      GOOD / POOR / FAILED

This module is responsible ONLY for file -> raw OCR text. It does not
perform logistics/POD field extraction, truck-number normalization,
money extraction, Shipment updates, database operations, or Qwen3
inference -- all of that is strictly out of scope here.

Repository check performed before writing this file: no OCR/IndicOCR/
Vision code, dependency, or configuration existed anywhere in the
project (``app/``, ``tests/``, ``pyproject.toml``), so this is a new,
clean adapter rather than a competing implementation of something that
already existed. It reuses the existing Phase-2-local configuration
pattern (``app.intelligence.config``) rather than introducing a second
one.

Provider naming: the single consistent identifier used everywhere in
this codebase for this provider is ``"ai4bharat_indicocr"`` (see
``PROVIDER_NAME`` below) -- never hardcode the literal string
elsewhere.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Protocol

import httpx

from app.intelligence.config import get_indicocr_api_key, get_indicocr_api_url
from app.intelligence.exceptions import (
    OcrAuthenticationError,
    OcrError,
    OcrInvalidRequestError,
    OcrInvalidResponseError,
    OcrNetworkError,
    OcrProviderError,
    OcrRateLimitError,
    OcrTimeoutError,
)
from app.intelligence.http_support import (
    RETRYABLE_STATUS_CODES,
    HttpClientLifecycleMixin,
    backoff_delay_seconds,
)
from app.intelligence.models import OCRQuality, OCRResult

PROVIDER_NAME = "ai4bharat_indicocr"

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 0.5

# Deterministic text-quality signal: never trust a provider-reported
# confidence score (IndicOCR may not supply one, or it may be
# unreliable) -- classify quality purely from the text itself.
# "Meaningful" = a plain-language character: Latin letters, digits, or
# a character from one of the scripts used to write India's 22
# scheduled languages -- deliberately excludes symbol noise like
# "@ # ^ ~" so garbled OCR output is recognized as such regardless of
# which Indian language (or code-mixed Hinglish) the real text is in.
#
# Unicode block coverage (script -> languages that use it):
#   Devanagari    U+0900-U+097F  Hindi, Marathi, Nepali, Sanskrit,
#                                 Konkani, Maithili, Bodo, Dogri,
#                                 Sindhi (also written in Devanagari)
#   Bengali       U+0980-U+09FF  Bengali, Assamese, Manipuri (also
#                                 historically written in Bengali)
#   Gurmukhi      U+0A00-U+0A7F  Punjabi
#   Gujarati      U+0A80-U+0AFF  Gujarati
#   Oriya/Odia    U+0B00-U+0B7F  Odia
#   Tamil         U+0B80-U+0BFF  Tamil
#   Telugu        U+0C00-U+0C7F  Telugu
#   Kannada       U+0C80-U+0CFF  Kannada
#   Malayalam     U+0D00-U+0D7F  Malayalam
#   Arabic        U+0600-U+06FF, U+0750-U+077F,
#                 U+FB50-U+FDFF, U+FE70-U+FEFF
#                                 Urdu, Kashmiri, Sindhi (Perso-Arabic)
#   Ol Chiki      U+1C50-U+1C7F  Santali
#   Meetei Mayek  U+ABC0-U+ABFF  Manipuri (official script)
# Together these cover the script of every one of the 22 scheduled
# languages, so OCR output in any of them is recognized as meaningful
# text rather than misclassified as noise.
_MEANINGFUL_CHAR_RE = re.compile(
    r"[A-Za-z0-9"
    r"ऀ-ॿ"
    r"ঀ-৿"
    r"਀-੿"
    r"઀-૿"
    r"଀-୿"
    r"஀-௿"
    r"ఀ-౿"
    r"ಀ-೿"
    r"ഀ-ൿ"
    r"؀-ۿ"
    r"ݐ-ݿ"
    r"ﭐ-﷿"
    r"ﹰ-﻿"
    r"᱐-᱿"
    r"ꯀ-꯿"
    r"]"
)
_MIN_MEANINGFUL_CHARS = 3
_MIN_MEANINGFUL_RATIO = 0.5


class OCRProvider(Protocol):
    """Interface the perception layer depends on -- never a concrete provider."""

    async def extract_text(self, file_path: str) -> OCRResult: ...


class VisionProvider(Protocol):
    """Interface for a vision-based fallback perception provider.

    Structurally identical to ``OCRProvider`` -- a fallback provider
    (e.g. Sarvam Vision) plays the same file -> ``OCRResult`` role, so
    the perception orchestration layer can treat both uniformly. Kept
    as a separate name only to make call sites self-documenting about
    which role a given provider is filling.
    """

    async def extract_text(self, file_path: str) -> OCRResult: ...


def evaluate_ocr_quality(result: OCRResult) -> OCRQuality:
    """Classify an ``OCRResult`` as GOOD / POOR / FAILED, deterministically.

    Ignores ``result.confidence`` entirely (it may be absent or
    unreliable) and never fabricates a score. Works for text in
    English, Hindi (Devanagari), or Hinglish/code-mixed content alike,
    since it only asks whether *enough* of the text is plain-language
    characters -- not which language they belong to.
    """
    if not result.success:
        return OCRQuality.FAILED

    text = result.text.strip()
    if not text:
        return OCRQuality.FAILED

    non_space = re.sub(r"\s+", "", text)
    if not non_space:
        return OCRQuality.FAILED

    meaningful_count = len(_MEANINGFUL_CHAR_RE.findall(non_space))
    ratio = meaningful_count / len(non_space)

    if meaningful_count < _MIN_MEANINGFUL_CHARS or ratio < _MIN_MEANINGFUL_RATIO:
        return OCRQuality.POOR

    return OCRQuality.GOOD


class IndicOCRProvider(HttpClientLifecycleMixin):
    """``OCRProvider`` backed by AI4Bharat IndicOCR.

    The exact hosted IndicOCR endpoint is deployment-specific (there
    is no single universally-documented public URL to hardcode), so
    the base URL is required configuration (``INDICOCR_API_URL``)
    rather than a guessed constant -- see
    ``app.intelligence.config.get_indicocr_api_url``. The request is a
    simple multipart file upload; adjust ``_build_request``/
    ``_parse_success`` here if the real deployment's contract differs
    once it is confirmed.

    An ``httpx.AsyncClient`` can be injected (e.g. built with a
    ``httpx.MockTransport``) so unit tests never hit the network.

    Runtime failures (network, timeout, rate limit, provider 5xx,
    malformed response) are never raised out of ``extract_text`` --
    they come back as ``OCRResult(success=False, ...)`` so a caller
    never needs a try/except to observe an OCR failure; only
    configuration errors (missing URL) raise, at construction time.
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_url = api_url or get_indicocr_api_url()
        self._api_key = api_key if api_key is not None else get_indicocr_api_key()
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._http_client = http_client
        self._owns_client = http_client is None

    async def extract_text(self, file_path: str) -> OCRResult:
        """Extract raw text from an image/document via AI4Bharat IndicOCR.

        Always returns an ``OCRResult``. On any runtime failure,
        returns ``success=False`` with the error described in
        ``metadata["error"]`` rather than raising.
        """
        path = Path(file_path)
        try:
            file_bytes = path.read_bytes()
        except OSError as exc:
            return self._failure(f"unable to read file: {exc}")

        client = await self._get_client()

        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        files = {"file": (path.name, file_bytes)}

        last_error: OcrError | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await client.post(self._api_url, headers=headers, files=files)
            except httpx.TimeoutException as exc:
                last_error = OcrTimeoutError(f"IndicOCR request timed out: {exc}")
            except httpx.RequestError as exc:
                last_error = OcrNetworkError(f"IndicOCR request failed: {exc}")
            else:
                try:
                    return self._handle_response(response)
                except (OcrInvalidRequestError, OcrAuthenticationError, OcrInvalidResponseError) as exc:
                    return self._failure(str(exc))
                except OcrError as exc:
                    last_error = exc

            if attempt < self._max_retries:
                await asyncio.sleep(backoff_delay_seconds(attempt, self._backoff_base_seconds))
                continue

        assert last_error is not None
        return self._failure(str(last_error))

    def _handle_response(self, response: httpx.Response) -> OCRResult:
        """Return an OCRResult on success, or raise an OcrError.

        Retryable failures (429/5xx) are raised as ``OcrError``
        subclasses for the retry loop to catch; non-retryable failures
        (400/401/403/malformed 200) are also raised here, but the
        caller converts them straight to a failed ``OCRResult`` rather
        than retrying.
        """
        status = response.status_code

        if status == 200:
            return self._parse_success(response)
        if status == 400:
            raise OcrInvalidRequestError(f"IndicOCR rejected the request (400): {response.text}")
        if status in (401, 403):
            raise OcrAuthenticationError(
                f"IndicOCR authentication failed ({status}): {response.text}"
            )
        if status == 429:
            raise OcrRateLimitError(f"IndicOCR rate limit exceeded (429): {response.text}")
        if status in RETRYABLE_STATUS_CODES:
            raise OcrProviderError(f"IndicOCR provider error ({status}): {response.text}")

        raise OcrInvalidResponseError(f"Unexpected IndicOCR response status {status}: {response.text}")

    def _parse_success(self, response: httpx.Response) -> OCRResult:
        try:
            payload = response.json()
        except ValueError as exc:
            raise OcrInvalidResponseError(f"IndicOCR response was not valid JSON: {exc}") from exc

        if not isinstance(payload, dict) or "text" not in payload:
            raise OcrInvalidResponseError(f"IndicOCR response missing 'text' field: {payload!r}")

        text = payload["text"]
        if not isinstance(text, str):
            raise OcrInvalidResponseError(f"IndicOCR 'text' field was not a string: {text!r}")

        confidence = payload.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = None

        return OCRResult(
            text=text,
            provider=PROVIDER_NAME,
            confidence=confidence,
            success=True,
            metadata={k: v for k, v in payload.items() if k not in ("text", "confidence")},
        )

    def _failure(self, error: str) -> OCRResult:
        return OCRResult(
            text="",
            provider=PROVIDER_NAME,
            confidence=None,
            success=False,
            metadata={"error": error},
        )
