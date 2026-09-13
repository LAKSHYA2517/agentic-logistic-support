"""Database-backed orchestration for incoming audio shipments."""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Shipment, ShipmentStatus, User, UserRole
from app.services.webhook import ParsedMetaMessage


logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    """Counts produced while handling one webhook envelope."""

    shipments_created: int = 0
    duplicates: int = 0
    processing_queued: int = 0
    failed: int = 0
    shipment_ids: list[int] = field(default_factory=list)


def persist_audio_messages(
    db: Session,
    payload: dict[str, Any],
    messages: list[ParsedMetaMessage],
    default_role: UserRole = UserRole.TRANSPORTER,
) -> IngestionResult:
    """Persist and deduplicate messages before any slow external processing."""

    result = IngestionResult()

    for message in messages:
        shipment, created = _create_shipment(
            db,
            payload,
            message,
            default_role=default_role,
        )
        if not created:
            logger.info(
                "duplicate_webhook_ignored shipment_id=%s message_id=%s media_id=%s",
                shipment.id,
                message.message_id,
                message.media_id,
            )
            result.duplicates += 1
            continue

        result.shipments_created += 1
        logger.info(
            "shipment_created shipment_id=%s message_id=%s media_id=%s",
            shipment.id,
            message.message_id,
            message.media_id,
        )
        if message.media_id is None:
            error_message = "Audio message did not include a media ID."
            _mark_failed(db, shipment, error_message)
            logger.warning(
                "media_download_failed shipment_id=%s message_id=%s reason=%s",
                shipment.id,
                message.message_id,
                error_message,
            )
            result.failed += 1
            continue
        result.shipment_ids.append(shipment.id)
        result.processing_queued += 1

    return result


def _create_shipment(
    db: Session,
    payload: dict[str, Any],
    message: ParsedMetaMessage,
    *,
    default_role: UserRole,
) -> tuple[Shipment, bool]:
    existing = _find_existing_shipment(db, message)
    if existing is not None:
        return existing, False

    user = db.scalar(select(User).where(User.whatsapp_number == message.sender_number))
    user_created = False
    if user is None:
        user = User(whatsapp_number=message.sender_number, role=default_role)
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            user = db.scalar(
                select(User).where(User.whatsapp_number == message.sender_number)
            )
            if user is None:
                raise
        except Exception:
            db.rollback()
            raise
        else:
            user_created = True

    logger.info("user_identified user_id=%s created=%s", user.id, user_created)

    shipment = Shipment(
        user=user,
        status=ShipmentStatus.RECEIVED,
        media_id=message.media_id,
        message_id=message.message_id,
        message_type=message.message_type,
        raw_event=payload,
        media_path=None,
        media_error=None,
    )
    db.add(shipment)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_existing_shipment(db, message)
        if existing is None:
            raise
        return existing, False
    except Exception:
        db.rollback()
        raise

    db.refresh(shipment)
    return shipment, True


def _find_existing_shipment(
    db: Session, message: ParsedMetaMessage
) -> Optional[Shipment]:
    if message.message_id is not None:
        return db.scalar(select(Shipment).where(Shipment.message_id == message.message_id))
    if message.media_id is not None:
        return db.scalar(
            select(Shipment).where(
                Shipment.message_id.is_(None),
                Shipment.media_id == message.media_id,
            )
        )
    return None


def _mark_failed(db: Session, shipment: Shipment, error_message: str) -> None:
    shipment.media_path = None
    shipment.media_error = error_message
    shipment.status = ShipmentStatus.FAILED
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
