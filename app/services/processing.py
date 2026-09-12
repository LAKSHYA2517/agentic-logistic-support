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
from app.services.drivers import DriverAssignment, assign_driver_for_shipment
from app.services.messaging import MetaMessagingError, MetaMessagingService
from app.services.meta import MetaMediaError, MetaMediaService


logger = logging.getLogger(__name__)
SessionFactory = Callable[[], Session]
MediaDownloader = Callable[[str, int], Path]
IntelligenceProcessor = Callable[[int], Awaitable[ProcessingResult]]
DriverNotifier = Callable[[int], Awaitable[None]]


class ShipmentTaskRunner:
    """Run slow media and intelligence work after webhook acknowledgement."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        session_factory: SessionFactory = SessionLocal,
        media_downloader: MediaDownloader | None = None,
        intelligence_processor: IntelligenceProcessor | None = None,
        driver_notifier: DriverNotifier | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._media_downloader = media_downloader or self._download_from_meta
        self._intelligence_processor = intelligence_processor
        self._driver_notifier = driver_notifier or self._assign_driver_and_notify

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
            return

        await self._notify_driver_if_accepted(shipment_id)

    async def _notify_driver_if_accepted(self, shipment_id: int) -> None:
        """Assign + message a driver only once intelligence actually accepted the shipment.

        A failure here (no matching driver, or the outbound WhatsApp
        send failing) is logged and swallowed rather than propagated --
        the intelligence outcome for this shipment already succeeded
        and must not be retroactively marked FAILED because a
        downstream, best-effort step didn't complete.
        """
        with self._session_factory() as session:
            shipment = session.get(Shipment, shipment_id)
            accepted = shipment is not None and shipment.status is ShipmentStatus.COMPLETED
        if not accepted:
            return

        try:
            await self._driver_notifier(shipment_id)
        except Exception as exc:
            logger.error(
                "driver_notification_failed shipment_id=%s error_type=%s",
                shipment_id,
                type(exc).__name__,
            )

    async def _assign_driver_and_notify(self, shipment_id: int) -> None:
        """Default driver notifier: DB assignment, then a Meta WhatsApp send."""

        assignment = await asyncio.to_thread(self._assign_driver, shipment_id)
        if assignment is None:
            return
        await asyncio.to_thread(self._send_driver_message, assignment)

    def _assign_driver(self, shipment_id: int) -> DriverAssignment | None:
        with self._session_factory() as session:
            return assign_driver_for_shipment(session, shipment_id)

    def _send_driver_message(self, assignment: DriverAssignment) -> None:
        with httpx.Client(timeout=self._settings.meta_request_timeout_seconds) as http_client:
            service = MetaMessagingService(
                access_token=self._settings.meta_access_token,
                graph_api_base_url=self._settings.meta_graph_api_base_url,
                graph_api_version=self._settings.meta_api_version,
                phone_number_id=self._settings.meta_phone_number_id,
                http_client=http_client,
            )
            try:
                whatsapp_message_id = service.send_text_message(
                    to=assignment.driver.phone, body=assignment.message
                )
            except MetaMessagingError as exc:
                # send_text_message raises for anything that isn't a 2xx
                # response (or a request-level failure), so reaching this
                # branch means the message is NOT confirmed sent -- the
                # detailed status/body/error were already logged inside
                # MetaMessagingService itself.
                logger.warning(
                    "driver_message_send_failed driver_id=%s truck_number=%s reason=%s",
                    assignment.driver.id,
                    assignment.driver.truck_number,
                    exc,
                )
                return

        # Reached only when send_text_message returned normally, i.e. Meta
        # actually responded 2xx -- never log this on a failed/uncertain send.
        logger.info(
            "driver_message_sent driver_id=%s driver_phone=%s whatsapp_message_id=%s",
            assignment.driver.id,
            assignment.driver.phone,
            whatsapp_message_id,
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
