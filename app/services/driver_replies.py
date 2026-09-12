"""Apply a driver's YES/CONFIRM or NO/REJECT reply to their shipment.

Handled synchronously within the webhook request (unlike the seller's
audio pipeline): a reply is just a database read/write with no slow
external I/O, so there's no need to background it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Driver, DriverConfirmationStatus, Shipment
from app.services.webhook import ParsedTextMessage

logger = logging.getLogger(__name__)

_CONFIRM_WORDS = {"yes", "confirm"}
_REJECT_WORDS = {"no", "reject"}


@dataclass
class DriverReplyResult:
    """Counts produced while handling driver replies in one webhook envelope."""

    confirmed: int = 0
    rejected: int = 0
    duplicates: int = 0
    ignored_no_driver: int = 0
    ignored_no_active_shipment: int = 0
    ignored_unrecognized: int = 0

    @property
    def processed(self) -> int:
        return self.confirmed + self.rejected


def process_driver_replies(db: Session, messages: list[ParsedTextMessage]) -> DriverReplyResult:
    """Apply each driver text reply to whichever shipment it is replying to."""

    result = DriverReplyResult()
    for message in messages:
        _process_one_reply(db, message, result)
    return result


def _process_one_reply(db: Session, message: ParsedTextMessage, result: DriverReplyResult) -> None:
    driver = db.scalar(select(Driver).where(Driver.phone == message.sender_number))
    if driver is None:
        logger.info("driver_reply_ignored reason=unknown_sender sender=%s", message.sender_number)
        result.ignored_no_driver += 1
        return

    shipment = db.scalar(
        select(Shipment)
        .where(
            Shipment.driver_id == driver.id,
            Shipment.driver_confirmation_status == DriverConfirmationStatus.PENDING,
        )
        .order_by(Shipment.driver_message_sent_at.desc(), Shipment.id.desc())
    )
    if shipment is None:
        logger.info("driver_reply_ignored reason=no_active_shipment driver_id=%s", driver.id)
        result.ignored_no_active_shipment += 1
        return

    if (
        message.message_id is not None
        and shipment.driver_reply_message_id == message.message_id
    ):
        logger.info(
            "driver_reply_duplicate shipment_id=%s message_id=%s",
            shipment.id,
            message.message_id,
        )
        result.duplicates += 1
        return

    reply = message.text_body.strip().lower()
    if reply in _CONFIRM_WORDS:
        new_status = DriverConfirmationStatus.CONFIRMED
    elif reply in _REJECT_WORDS:
        new_status = DriverConfirmationStatus.REJECTED
    else:
        logger.info(
            "driver_reply_ignored reason=unrecognized shipment_id=%s text=%r",
            shipment.id,
            message.text_body,
        )
        result.ignored_unrecognized += 1
        return

    shipment.driver_confirmation_status = new_status
    shipment.driver_reply_message_id = message.message_id
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(
        "driver_reply_processed shipment_id=%s driver_id=%s status=%s",
        shipment.id,
        driver.id,
        new_status.value,
    )
    if new_status is DriverConfirmationStatus.CONFIRMED:
        result.confirmed += 1
    else:
        result.rejected += 1
