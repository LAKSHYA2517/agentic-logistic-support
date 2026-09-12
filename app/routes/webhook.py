"""Routes for receiving Meta WhatsApp webhook events."""

import logging
from secrets import compare_digest
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import AppSettings, get_settings
from app.database import get_db
from app.schemas import WebhookResponse
from app.services.driver_replies import process_driver_replies
from app.services.processing import ShipmentTaskRunner, get_shipment_task_runner
from app.services.shipments import persist_audio_messages
from app.services.webhook import extract_audio_messages, extract_text_messages


router = APIRouter(tags=["meta-webhook"])
logger = logging.getLogger(__name__)


@router.get("/meta-webhook", response_class=PlainTextResponse)
def verify_meta_webhook(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
    settings: AppSettings = Depends(get_settings),
) -> PlainTextResponse:
    """Complete Meta's webhook callback verification challenge."""

    configured_token = settings.meta_webhook_verify_token
    if configured_token is None:
        logger.error("webhook_verification_unavailable reason=token_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook verification is not configured.",
        )

    token_matches = hub_verify_token is not None and compare_digest(
        hub_verify_token, configured_token
    )
    if hub_mode != "subscribe" or not token_matches or hub_challenge is None:
        logger.warning("webhook_verification_failed")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Webhook verification failed.",
        )

    logger.info("webhook_verification_succeeded")
    return PlainTextResponse(content=hub_challenge)


@router.post("/meta-webhook", response_model=WebhookResponse)
async def receive_meta_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    task_runner: ShipmentTaskRunner = Depends(get_shipment_task_runner),
) -> WebhookResponse:
    """Acknowledge a webhook after persisting any audio messages it contains."""

    logger.info("webhook_received")
    try:
        payload: Any = await request.json()
    except ValueError:
        logger.warning("webhook_ignored reason=invalid_json")
        return WebhookResponse(status="ignored")

    if not isinstance(payload, dict):
        logger.warning("webhook_ignored reason=non_object_payload")
        return WebhookResponse(status="ignored")

    audio_messages = extract_audio_messages(payload)
    text_messages = extract_text_messages(payload)

    if not audio_messages and not text_messages:
        logger.info("webhook_ignored reason=no_recognized_messages")
        return WebhookResponse(status="ignored")

    driver_confirmed = 0
    driver_rejected = 0
    if text_messages:
        try:
            reply_result = process_driver_replies(db, text_messages)
        except SQLAlchemyError as exc:
            db.rollback()
            logger.error("webhook_database_error error_type=%s", type(exc).__name__)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Webhook persistence failed.",
            ) from exc
        driver_confirmed = reply_result.confirmed
        driver_rejected = reply_result.rejected

    if not audio_messages:
        return WebhookResponse(
            status="accepted",
            driver_confirmed=driver_confirmed,
            driver_rejected=driver_rejected,
        )

    for message in audio_messages:
        logger.info(
            "webhook_message_identified message_id=%s media_id=%s",
            message.message_id,
            message.media_id,
        )

    try:
        result = persist_audio_messages(db, payload, audio_messages)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("webhook_database_error error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook persistence failed.",
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.error("webhook_processing_error error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed.",
        ) from exc

    for shipment_id in result.shipment_ids:
        background_tasks.add_task(task_runner, shipment_id)

    return WebhookResponse(
        status="accepted",
        shipments_created=result.shipments_created,
        duplicates=result.duplicates,
        processing_queued=result.processing_queued,
        failed=result.failed,
        driver_confirmed=driver_confirmed,
        driver_rejected=driver_rejected,
    )
