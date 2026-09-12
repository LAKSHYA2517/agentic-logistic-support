"""Pydantic request and response schemas."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response returned by the health endpoint."""

    status: Literal["ok"] = "ok"


class WebhookResponse(BaseModel):
    """Acknowledgement returned after webhook ingestion."""

    status: Literal["accepted", "ignored"]
    shipments_created: int = 0
    duplicates: int = 0
    processing_queued: int = 0
    media_downloaded: int = 0
    failed: int = 0
