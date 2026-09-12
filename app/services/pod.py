"""Match an inbound POD (proof of delivery) message to its shipment, and
deterministically verify the digitised document against what the
shipment already knows.

Reuses two already-established patterns rather than inventing new ones:

- the dedup-before-slow-work guard already used for outbound driver
  messaging (``app.services.drivers.assign_driver_for_shipment``) and
  for driver text replies (``app.services.driver_replies``) -- this
  reuses the *same* ``driver_reply_message_id`` column rather than
  adding a new one. By the time a shipment reaches "in transit"
  (``COMPLETED`` + driver ``CONFIRMED``), that column's earlier value
  (from the assignment-confirmation reply) has already served its
  purpose and is safe to overwrite with the POD message's id.
- the deterministic, closed-set evidence checking already built for
  voice-note validation (``app.intelligence.validation``) -- OCR/Vision
  text is never trusted just because it came back; every claim is
  checked against the shipment's own ``extracted_data`` the same way a
  transcript is checked there. ``_contains_as_word``,
  ``_truck_numbers_mentioned_in``, and ``_CITY_EQUIVALENTS`` are
  imported directly (despite the leading underscore) rather than
  duplicated, since they are exactly the already-tested tools this
  needs -- a second copy of the Devanagari-safe word-boundary check or
  the vehicle-number scanner would be the kind of duplication this
  project has already had to fix once.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intelligence.validation import (
    _CITY_EQUIVALENTS,
    _contains_as_word,
    _truck_numbers_mentioned_in,
    normalize_truck_number,
)
from app.models import Driver, DriverConfirmationStatus, Shipment, ShipmentStatus
from app.services.webhook import ParsedMetaMessage

logger = logging.getLogger(__name__)

PODOutcome = Literal["DELIVERED", "NEEDS_REVIEW"]


@dataclass
class PODVerification:
    """Deterministic outcome of checking POD text against a shipment."""

    outcome: PODOutcome
    reasons: list[str] = field(default_factory=list)


def register_pod_message(db: Session, message: ParsedMetaMessage) -> Optional[Shipment]:
    """Match an inbound POD message to the driver's active in-transit shipment.

    "In transit" here means ``ShipmentStatus.COMPLETED`` (intelligence
    accepted the extraction) with ``DriverConfirmationStatus.CONFIRMED``
    (the driver already said YES to the assignment) -- there is no
    separate ``IN_TRANSIT`` status; that combination *is* the in-transit
    state, consistent with how the dashboard already derives it
    (``app.routes.dashboard._dashboard_status``).

    Returns the ``Shipment`` to process, with the dedup guard already
    committed, or ``None`` if the message should be ignored: no media,
    unknown sender, no matching in-transit shipment, or an exact
    duplicate of an already-registered message.
    """

    if message.media_id is None:
        logger.info("pod_ignored reason=no_media message_id=%s", message.message_id)
        return None

    driver = db.scalar(select(Driver).where(Driver.phone == message.sender_number))
    if driver is None:
        logger.info("pod_ignored reason=unknown_sender sender=%s", message.sender_number)
        return None

    shipment = db.scalar(
        select(Shipment)
        .where(
            Shipment.driver_id == driver.id,
            Shipment.status == ShipmentStatus.COMPLETED,
            Shipment.driver_confirmation_status == DriverConfirmationStatus.CONFIRMED,
        )
        .order_by(Shipment.driver_message_sent_at.desc(), Shipment.id.desc())
    )
    if shipment is None:
        logger.info("pod_ignored reason=no_active_shipment driver_id=%s", driver.id)
        return None

    if (
        message.message_id is not None
        and shipment.driver_reply_message_id == message.message_id
    ):
        logger.info(
            "pod_duplicate shipment_id=%s message_id=%s", shipment.id, message.message_id
        )
        return None

    shipment.driver_reply_message_id = message.message_id
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(
        "pod_registered shipment_id=%s driver_id=%s message_id=%s",
        shipment.id,
        driver.id,
        message.message_id,
    )
    return shipment


def verify_pod(pod_text: str, extracted_data: dict) -> PODVerification:
    """Compare a digitised POD document against the shipment's known fields.

    - Truck number must be confirmed (mentioned in the POD, and
      matching) before a shipment can ever be marked DELIVERED -- it is
      the one field that establishes the POD actually belongs to *this*
      shipment, so unlike destination it is never treated as optional.
    - Destination is optional: if the shipment has none, or the POD
      simply doesn't name any recognized place, that is missing
      information, not a conflict. Only a POD that names a *different*
      recognized city than the shipment's destination counts as a
      genuine conflict.
    """

    text = unicodedata.normalize("NFC", pod_text or "").lower()
    reasons: list[str] = []

    truck_confirmed = _check_truck_number(text, extracted_data.get("truck_number"), reasons)
    destination_conflict = _destination_conflicts(text, extracted_data.get("destination"), reasons)

    if truck_confirmed and not destination_conflict:
        return PODVerification(outcome="DELIVERED", reasons=reasons)
    return PODVerification(outcome="NEEDS_REVIEW", reasons=reasons)


def _check_truck_number(text: str, expected: object, reasons: list[str]) -> bool:
    if not isinstance(expected, str) or not expected.strip():
        reasons.append("shipment has no known truck number to verify against")
        return False

    canonical_expected = normalize_truck_number(expected) or expected.strip().upper()
    mentioned = _truck_numbers_mentioned_in(text)
    if not mentioned:
        reasons.append("POD does not mention any vehicle number")
        return False
    if canonical_expected in mentioned:
        return True
    reasons.append(
        f"POD mentions vehicle number(s) {sorted(mentioned)}, expected {canonical_expected}"
    )
    return False


def _destination_conflicts(text: str, expected: object, reasons: list[str]) -> bool:
    if not isinstance(expected, str) or not expected.strip():
        return False

    needle = unicodedata.normalize("NFC", expected).strip().lower()
    candidates = {needle}
    equivalent = _CITY_EQUIVALENTS.get(needle)
    if equivalent:
        candidates.add(equivalent)

    if any(candidate and _contains_as_word(text, candidate) for candidate in candidates):
        return False

    for city_word in _CITY_EQUIVALENTS:
        if city_word in candidates:
            continue
        if _contains_as_word(text, city_word):
            reasons.append(f"POD mentions destination '{city_word}', expected '{expected}'")
            return True

    reasons.append(f"POD does not confirm destination '{expected}'")
    return False
