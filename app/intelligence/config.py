"""Phase-2-local configuration helpers.

Kept isolated to ``app/intelligence`` so Phase 2 does not depend on, or
assume the existence of, a project-wide settings/config module owned by
another branch. If a shared config pattern already exists elsewhere in
the repo, downstream integration can wrap it instead of this file --
this module is intentionally a thin, replaceable shim.

All secrets live in a git-ignored ``.env`` file at the project root
(see ``.gitignore``) and are loaded into ``os.environ`` by
``_load_dotenv_into_environ`` below -- a real environment variable
already set (e.g. by the deployment platform) always takes precedence
over ``.env``. This is a small, dependency-free stand-in for
``python-dotenv``: only ``os``/``pathlib`` are used, consistent with
this module's "no unnecessary dependencies" rule.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.intelligence.exceptions import (
    ExtractionConfigurationError,
    OcrConfigurationError,
    SttConfigurationError,
)

SARVAM_API_KEY_ENV_VAR = "SARVAM_API_KEY"
SARVAM_STT_URL_ENV_VAR = "SARVAM_STT_URL"
GROQ_API_KEY_ENV_VAR = "GROQ_API_KEY"
GROQ_CHAT_COMPLETIONS_URL_ENV_VAR = "GROQ_CHAT_COMPLETIONS_URL"
INDICOCR_API_URL_ENV_VAR = "INDICOCR_API_URL"
INDICOCR_API_KEY_ENV_VAR = "INDICOCR_API_KEY"

DEFAULT_SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
DEFAULT_GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"

_DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _load_dotenv_into_environ(path: Path = _DOTENV_PATH) -> None:
    """Populate ``os.environ`` from a simple ``KEY=VALUE`` ``.env`` file.

    Never overrides a variable that is already set in the real
    environment. Silently does nothing if the file does not exist --
    ``.env`` is a local development convenience, not a requirement (a
    deployment can set real environment variables instead). Blank
    lines, ``#``-comments, and surrounding quotes on the value are
    handled; anything else is left for the real environment or the
    ``ConfigurationError`` a missing required key already raises.
    """
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv_into_environ()


def get_sarvam_api_key() -> str:
    """Read the Sarvam API key from the environment.

    Raises:
        SttConfigurationError: the environment variable is unset or empty.
    """
    api_key = os.environ.get(SARVAM_API_KEY_ENV_VAR)
    if not api_key:
        raise SttConfigurationError(
            f"{SARVAM_API_KEY_ENV_VAR} environment variable is not set"
        )
    return api_key


def get_sarvam_stt_url() -> str:
    """Read the Sarvam speech-to-text endpoint, defaulting to the production URL.

    Unlike the API keys, this has a known, stable public default, so
    it is optional configuration -- only needed to override it (e.g.
    to point at a staging environment or a regional endpoint).
    """
    return os.environ.get(SARVAM_STT_URL_ENV_VAR) or DEFAULT_SARVAM_STT_URL


def get_groq_api_key() -> str:
    """Read the Groq API key from the environment.

    Raises:
        ExtractionConfigurationError: the environment variable is unset or empty.
    """
    api_key = os.environ.get(GROQ_API_KEY_ENV_VAR)
    if not api_key:
        raise ExtractionConfigurationError(
            f"{GROQ_API_KEY_ENV_VAR} environment variable is not set"
        )
    return api_key


def get_groq_chat_completions_url() -> str:
    """Read the Groq chat-completions endpoint, defaulting to the production URL.

    Unlike the API keys, this has a known, stable public default, so
    it is optional configuration -- only needed to override it (e.g.
    to point at a proxy or a regional endpoint).
    """
    return os.environ.get(GROQ_CHAT_COMPLETIONS_URL_ENV_VAR) or DEFAULT_GROQ_CHAT_COMPLETIONS_URL


def get_indicocr_api_url() -> str:
    """Read the AI4Bharat IndicOCR service URL from the environment.

    There is no fixed, universally-documented public IndicOCR endpoint
    to default to -- deployments may point at a self-hosted service or
    a specific provider instance. The URL is therefore required
    configuration rather than a hardcoded constant.

    Raises:
        OcrConfigurationError: the environment variable is unset or empty.
    """
    api_url = os.environ.get(INDICOCR_API_URL_ENV_VAR)
    if not api_url:
        raise OcrConfigurationError(
            f"{INDICOCR_API_URL_ENV_VAR} environment variable is not set"
        )
    return api_url


def get_indicocr_api_key() -> str | None:
    """Read the (optional) AI4Bharat IndicOCR API key from the environment.

    Unlike the Sarvam/Groq keys, this is optional: some IndicOCR
    deployments (e.g. self-hosted) may not require authentication.
    """
    return os.environ.get(INDICOCR_API_KEY_ENV_VAR) or None
