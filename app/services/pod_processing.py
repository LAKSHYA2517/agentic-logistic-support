"""Background orchestration for a driver's POD (proof of delivery) message.

Mirrors ``app.services.processing.ShipmentTaskRunner``'s shape (download,
then a slow external call, then persist an outcome), but for the
delivery-confirmation leg of the flow rather than the initial voice
note. Kept as a fully separate runner -- rather than extending
``ShipmentTaskRunner`` -- so that already-tested class is never touched.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import AppSettings, get_settings
from app.database import SessionLocal
from app.intelligence.models import OCRResult
from app.intelligence.perception import extract_document_text
from app.models import Shipment, ShipmentStatus
from app.services.meta import MetaMediaError, MetaMediaService
from app.services.pod import verify_pod

logger = logging.getLogger(__name__)
SessionFactory = Callable[[], Session]
PODMediaDownloader = Callable[[str, int], Path]
DocumentExtractor = Callable[[str], Awaitable[OCRResult]]


class PODTaskRunner:
    """Download, digitise, and verify one driver-submitted POD document."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        session_factory: SessionFactory = SessionLocal,
        media_downloader: PODMediaDownloader | None = None,
        document_extractor: DocumentExtractor | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._media_downloader = media_downloader or self._download_from_meta
        self._document_extractor = document_extractor or extract_document_text

    async def __call__(self, shipment_id: int, media_id: str) -> None:
        """Run the full POD pipeline for one shipment; never raises."""

        try:
            file_path = await asyncio.to_thread(self._media_downloader, media_id, shipment_id)
        except MetaMediaError as exc:
            self._mark_needs_review(shipment_id, f"POD download failed: {exc}")
            logger.warning("pod_download_failed shipment_id=%s reason=%s", shipment_id, exc)
            return
        except Exception as exc:
            self._mark_needs_review(
                shipment_id, f"Unexpected POD download failure ({type(exc).__name__})."
            )
            logger.error(
                "pod_download_failed shipment_id=%s error_type=%s",
                shipment_id,
                type(exc).__name__,
            )
            return

        try:
            ocr_result = await self._document_extractor(str(file_path))
        except Exception as exc:
            self._mark_needs_review(
                shipment_id, f"Unexpected POD digitisation failure ({type(exc).__name__})."
            )
            logger.error(
                "pod_digitisation_failed shipment_id=%s error_type=%s",
                shipment_id,
                type(exc).__name__,
            )
            return
        finally:
            Path(file_path).unlink(missing_ok=True)

        if not ocr_result.success or ocr_result.metadata.get("quality") == "FAILED":
            reason = ocr_result.metadata.get("error") or "POD document could not be read"
            self._mark_needs_review(shipment_id, f"POD digitisation failed: {reason}")
            logger.warning("pod_digitisation_unreadable shipment_id=%s", shipment_id)
            return

        with self._session_factory() as session:
            shipment = session.get(Shipment, shipment_id)
            if shipment is None:
                logger.warning("pod_shipment_missing shipment_id=%s", shipment_id)
                return

            verification = verify_pod(ocr_result.text, shipment.extracted_data or {})
            if verification.outcome == "DELIVERED":
                shipment.status = ShipmentStatus.DELIVERED
                shipment.processing_error = None
            else:
                shipment.status = ShipmentStatus.PARSED
                shipment.processing_error = "; ".join(verification.reasons) or "POD needs review"

            try:
                session.commit()
            except Exception:
                session.rollback()
                raise

            logger.info(
                "pod_verified shipment_id=%s outcome=%s", shipment.id, verification.outcome
            )

    def _mark_needs_review(self, shipment_id: int, reason: str) -> None:
        with self._session_factory() as session:
            shipment = session.get(Shipment, shipment_id)
            if shipment is None:
                return
            shipment.status = ShipmentStatus.PARSED
            shipment.processing_error = reason
            try:
                session.commit()
            except Exception:
                session.rollback()
                raise

    def _download_from_meta(self, media_id: str, shipment_id: int) -> Path:
        with httpx.Client(timeout=self._settings.meta_request_timeout_seconds) as http_client:
            service = MetaMediaService(
                access_token=self._settings.meta_access_token,
                graph_api_base_url=self._settings.meta_graph_api_base_url,
                graph_api_version=self._settings.meta_api_version,
                output_dir=self._settings.media_download_dir,
                max_media_bytes=self._settings.media_max_bytes,
                http_client=http_client,
                phone_number_id=self._settings.meta_phone_number_id,
            )
            return service.download_pod_document(media_id, shipment_id)


def get_pod_task_runner(settings: AppSettings = Depends(get_settings)) -> PODTaskRunner:
    """Provide a runner whose resources outlive the request session safely."""

    return PODTaskRunner(settings=settings)
