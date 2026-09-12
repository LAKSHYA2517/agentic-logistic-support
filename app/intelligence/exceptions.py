"""Custom exceptions for media intake and validation."""


class MediaValidationError(Exception):
    """Base class for all media validation failures."""


class MediaNotFoundError(MediaValidationError):
    """Raised when the given file path does not exist or is not a regular file."""


class EmptyMediaError(MediaValidationError):
    """Raised when the media file has zero bytes."""


class InvalidMediaExtensionError(MediaValidationError):
    """Raised when the media file does not have an accepted extension (.ogg)."""


class MediaTooLargeError(MediaValidationError):
    """Raised when the media file exceeds the maximum allowed size."""


class SttError(Exception):
    """Base class for all speech-to-text adapter failures."""


class SttConfigurationError(SttError):
    """Raised when required STT configuration (e.g. an API key) is missing."""


class SttInvalidRequestError(SttError):
    """Raised when the provider rejects the request as malformed (HTTP 400)."""


class SttAuthenticationError(SttError):
    """Raised on authentication/authorization failure (HTTP 401/403)."""


class SttRateLimitError(SttError):
    """Raised when the provider rate-limits the request (HTTP 429) and retries are exhausted."""


class SttProviderError(SttError):
    """Raised when the provider fails persistently (HTTP 5xx) after retries are exhausted."""


class SttTimeoutError(SttError):
    """Raised when the request times out after retries are exhausted."""


class SttNetworkError(SttError):
    """Raised on a non-timeout network failure after retries are exhausted."""


class SttInvalidResponseError(SttError):
    """Raised when the provider returns a 200 with an unusable/malformed body."""


class ExtractionError(Exception):
    """Base class for all logistics-extraction provider failures."""


class ExtractionConfigurationError(ExtractionError):
    """Raised when required extraction configuration (e.g. an API key) is missing."""


class ExtractionInvalidRequestError(ExtractionError):
    """Raised when the provider rejects the request as malformed (HTTP 400)."""


class ExtractionAuthenticationError(ExtractionError):
    """Raised on authentication/authorization failure (HTTP 401/403)."""


class ExtractionRateLimitError(ExtractionError):
    """Raised when the provider rate-limits the request (HTTP 429) and retries are exhausted."""


class ExtractionProviderError(ExtractionError):
    """Raised when the provider fails persistently (HTTP 5xx) after retries are exhausted."""


class ExtractionTimeoutError(ExtractionError):
    """Raised when the request times out after retries are exhausted."""


class ExtractionNetworkError(ExtractionError):
    """Raised on a non-timeout network failure after retries are exhausted."""


class ExtractionInvalidResponseError(ExtractionError):
    """Raised when the provider returns a 200 with structured output that is
    malformed, not valid JSON, or does not satisfy the ``LogisticsExtraction`` schema."""


class OcrError(Exception):
    """Base class for all OCR provider failures.

    Configuration errors (e.g. a missing endpoint/API key) are raised
    at provider construction time, same as the STT/extraction
    adapters. Runtime failures during ``extract_text`` (network,
    timeout, rate limit, provider 5xx, malformed response) are
    deliberately NOT raised out of ``extract_text`` -- they are
    reported as an ``OCRResult`` with ``success=False`` instead, so
    that OCR failure is always visible as ordinary data the quality
    gate can classify (``FAILED``), never as a try/except a caller
    must remember to add.
    """


class OcrConfigurationError(OcrError):
    """Raised when required OCR configuration (e.g. the service URL) is missing."""


class OcrInvalidRequestError(OcrError):
    """The provider rejected the request as malformed (HTTP 400)."""


class OcrAuthenticationError(OcrError):
    """Authentication/authorization failure (HTTP 401/403)."""


class OcrRateLimitError(OcrError):
    """The provider rate-limited the request (HTTP 429) and retries were exhausted."""


class OcrProviderError(OcrError):
    """The provider failed persistently (HTTP 5xx) after retries were exhausted."""


class OcrTimeoutError(OcrError):
    """The request timed out after retries were exhausted."""


class OcrNetworkError(OcrError):
    """A non-timeout network failure occurred after retries were exhausted."""


class OcrInvalidResponseError(OcrError):
    """The provider returned a 200 with a body that is malformed or missing the text field."""
