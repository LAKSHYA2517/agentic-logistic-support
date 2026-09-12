"""Background orchestration from downloaded WhatsApp media to intelligence."""

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
from app.intelligence.models import ProcessingResult
from app.intelligence.service import process_audio
from app.models import Shipment, ShipmentStatus
from app.services.meta import MetaMediaError, MetaMediaService


logger = logging.getLogger(__name__)
SessionFactory = Callable[[], Session]
MediaDownloader = Callable[[str, int], Path]
IntelligenceProcessor = Callable[[int], Awaitable[ProcessingResult]]


class ShipmentTaskRunner:
    """Run slow media and intelligence work after webhook acknowledgement."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        session_factory: SessionFactory = SessionLocal,
        media_downloader: MediaDownloader | None = None,
        intelligence_processor: IntelligenceProcessor | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._media_downloader = media_downloader or self._download_from_meta
        self._intelligence_processor = intelligence_processor

    async def __call__(self, shipment_id: int) -> None:
        """Download media, then process the same shipment when enabled."""

        if not await asyncio.to_thread(self._download_and_persist, shipment_id):
            return
        if not self._settings.intelligence_enabled:
            logger.info(
                "intelligence_processing_skipped shipment_id=%s reason=disabled",
                shipment_id,
            )
            return

        processor = self._intelligence_processor
        if processor is None:

            async def processor(target_id: int) -> ProcessingResult:
                return await process_audio(
                    target_id,
                    session_factory=self._session_factory,
                )

        try:
            await processor(shipment_id)
        except Exception as exc:
            reason = f"Unexpected intelligence task failure ({type(exc).__name__})."
            with self._session_factory() as session:
                shipment = session.get(Shipment, shipment_id)
                if shipment is not None:
                    shipment.processing_error = reason
                    shipment.status = ShipmentStatus.FAILED
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                        raise
            logger.error(
                "intelligence_processing_failed shipment_id=%s error_type=%s",
                shipment_id,
                type(exc).__name__,
            )

    def _download_and_persist(self, shipment_id: int) -> bool:
        with self._session_factory() as session:
            shipment = session.get(Shipment, shipment_id)
            if shipment is None:
                logger.warning("shipment_background_missing shipment_id=%s", shipment_id)
                return False
            if shipment.media_path:
                logger.info(
                    "media_download_skipped shipment_id=%s reason=already_downloaded",
                    shipment_id,
                )
                return True
            if not shipment.media_id:
                self._mark_media_failed(
                    session,
                    shipment,
                    "Audio message did not include a media ID.",
                )
                return False
            media_id = shipment.media_id

        logger.info(
            "media_download_started shipment_id=%s media_id=%s",
            shipment_id,
            media_id,
        )
        try:
            media_path = self._media_downloader(media_id, shipment_id)
        except MetaMediaError as exc:
            with self._session_factory() as session:
                shipment = session.get(Shipment, shipment_id)
                if shipment is not None:
                    self._mark_media_failed(session, shipment, str(exc))
            logger.warning(
                "media_download_failed shipment_id=%s media_id=%s reason=%s",
                shipment_id,
                media_id,
                exc,
            )
            return False
        except Exception as exc:
            reason = f"Unexpected media download failure ({type(exc).__name__})."
            with self._session_factory() as session:
                shipment = session.get(Shipment, shipment_id)
                if shipment is not None:
                    self._mark_media_failed(session, shipment, reason)
            logger.error(
                "media_download_failed shipment_id=%s media_id=%s error_type=%s",
                shipment_id,
                media_id,
                type(exc).__name__,
            )
            return False

        with self._session_factory() as session:
            shipment = session.get(Shipment, shipment_id)
            if shipment is None:
                media_path.unlink(missing_ok=True)
                logger.warning("shipment_background_missing shipment_id=%s", shipment_id)
                return False
            shipment.media_path = str(media_path)
            shipment.media_error = None
            shipment.status = ShipmentStatus.RECEIVED
            try:
                session.commit()
            except Exception:
                session.rollback()
                media_path.unlink(missing_ok=True)
                raise

        logger.info(
            "media_download_completed shipment_id=%s file_name=%s",
            shipment_id,
            media_path.name,
        )
        return True

    def _download_from_meta(self, media_id: str, shipment_id: int) -> Path:
        with httpx.Client(
            timeout=self._settings.meta_request_timeout_seconds,
            follow_redirects=True,
        ) as http_client:
            service = MetaMediaService(
                access_token=self._settings.meta_access_token,
                graph_api_base_url=self._settings.meta_graph_api_base_url,
                graph_api_version=self._settings.meta_api_version,
                output_dir=self._settings.media_download_dir,
                max_media_bytes=self._settings.media_max_bytes,
                http_client=http_client,
                phone_number_id=self._settings.meta_phone_number_id,
            )
            return service.download_audio(media_id, shipment_id)

    @staticmethod
    def _mark_media_failed(
        session: Session,
        shipment: Shipment,
        reason: str,
    ) -> None:
        shipment.media_path = None
        shipment.media_error = reason
        shipment.status = ShipmentStatus.FAILED
        try:
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_shipment_task_runner(
    settings: AppSettings = Depends(get_settings),
) -> ShipmentTaskRunner:
    """Provide a runner whose resources outlive the request session safely."""

    return ShipmentTaskRunner(settings=settings)
