"""Application-level configuration loaded from environment variables."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


class AppSettings(BaseModel):
    """Runtime settings for the FastAPI application and Uvicorn."""

    model_config = ConfigDict(validate_default=True)

    name: str = Field(default_factory=lambda: os.getenv("APP_NAME", "Agentic Logistic Support"))
    debug: bool = Field(default_factory=lambda: _get_bool("APP_DEBUG", False))
    host: str = Field(default_factory=lambda: os.getenv("APP_HOST", "127.0.0.1"))
    port: int = Field(default_factory=lambda: int(os.getenv("APP_PORT", "8000")))
    reload: bool = Field(default_factory=lambda: _get_bool("APP_RELOAD", False))
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = Field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper()
    )
    meta_webhook_verify_token: Optional[str] = Field(
        default_factory=lambda: os.getenv("META_WEBHOOK_VERIFY_TOKEN") or None
    )
    meta_access_token: Optional[str] = Field(
        default_factory=lambda: os.getenv("META_ACCESS_TOKEN") or None
    )
    meta_waba_id: Optional[str] = Field(
        default_factory=lambda: os.getenv("META_WABA_ID") or None
    )
    meta_graph_api_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "META_GRAPH_API_BASE_URL", "https://graph.facebook.com"
        )
    )
    meta_api_version: str = Field(
        default_factory=lambda: os.getenv("META_API_VERSION")
        or os.getenv("META_GRAPH_API_VERSION")
        or "v25.0"
    )
    meta_phone_number_id: Optional[str] = Field(
        default_factory=lambda: os.getenv("META_PHONE_NUMBER_ID") or None
    )
    meta_request_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("META_REQUEST_TIMEOUT_SECONDS", "20")),
        gt=0,
    )
    media_download_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("MEDIA_DOWNLOAD_DIR", "/tmp"))
    )
    media_max_bytes: int = Field(
        default_factory=lambda: int(os.getenv("MEDIA_MAX_BYTES", str(16 * 1024 * 1024))),
        gt=0,
    )
    intelligence_enabled: bool = Field(
        default_factory=lambda: _get_bool("INTELLIGENCE_ENABLED", True)
    )
    sarvam_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("SARVAM_API_KEY") or None
    )
    sarvam_stt_url: str = Field(
        default_factory=lambda: os.getenv(
            "SARVAM_STT_URL", "https://api.sarvam.ai/speech-to-text"
        )
    )
    groq_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("GROQ_API_KEY") or None
    )
    groq_chat_completions_url: str = Field(
        default_factory=lambda: os.getenv(
            "GROQ_CHAT_COMPLETIONS_URL",
            "https://api.groq.com/openai/v1/chat/completions",
        )
    )
    sarvam_vision_language: str = Field(
        default_factory=lambda: os.getenv("SARVAM_VISION_LANGUAGE", "hi-IN")
    )
    sarvam_vision_output_format: Literal["md", "html"] = Field(
        default_factory=lambda: os.getenv("SARVAM_VISION_OUTPUT_FORMAT", "md")
    )
    sarvam_vision_content_type: Literal["printed", "handwritten", "mixed"] = Field(
        default_factory=lambda: os.getenv("SARVAM_VISION_CONTENT_TYPE", "mixed")
    )
    sarvam_vision_poll_interval_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("SARVAM_VISION_POLL_INTERVAL_SECONDS", "5")
        ),
        ge=0,
    )
    sarvam_vision_max_wait_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("SARVAM_VISION_MAX_WAIT_SECONDS", "120")
        ),
        gt=0,
    )


@lru_cache
def get_settings() -> AppSettings:
    """Return a cached application settings object."""

    return AppSettings()
