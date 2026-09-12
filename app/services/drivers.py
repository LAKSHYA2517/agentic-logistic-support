"""Driver lookup and assignment for an ACCEPTED shipment.

Runs after ``app.intelligence.service.process_audio`` has produced an
ACCEPTED ``ProcessingResult`` and Phase 2's repository has already
persisted it onto the ``Shipment`` row. This module owns the
Phase-1-side continuation: match the extracted ``truck_number`` to a
known ``Driver`` and assign them to the shipment. Deliberately kept
free of any Meta API call so it stays trivially unit-testable with a
plain database session -- sending the actual WhatsApp message is a
separate step (see ``app.services.messaging``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intelligence.validation import normalize_truck_number
from app.models import Driver, DriverConfirmationStatus, Shipment

logger = logging.getLogger(__name__)


@dataclass
class DriverAssignment:
    """A driver newly assigned to a shipment, with the message to send them."""

    driver: Driver
    message: str
    template_parameters: tuple[str, ...]


def find_driver_by_truck_number(db: Session, truck_number: str) -> Optional[Driver]:
    """Look up a driver by truck number, tolerant of separator formatting.

    Reuses Phase 2's own vehicle-number canonicalizer
    (``app.intelligence.validation.normalize_truck_number``) rather
    than a second copy of the same normalization rule, so a lookup
    here always agrees with how Phase 2 already normalized the
    extracted value.
    """

    canonical = normalize_truck_number(truck_number) or truck_number.strip().upper()
    return db.scalar(select(Driver).where(Driver.truck_number == canonical))


def build_assignment_message(shipment: Shipment) -> str:
    """Compose the outbound confirmation-request message for a driver."""

    data = shipment.extracted_data or {}
    party = data.get("party_name") or "Unknown party"
    truck = data.get("truck_number") or "Unknown"
    destination = data.get("destination") or "Unknown"

    return (
        f"New shipment assigned. Party: {party}, Truck: {truck}, "
        f"Destination: {destination}, Advance: {_format_currency(data.get('advance_paid'))}, "
        f"Balance: {_format_currency(data.get('balance_due'))}. Please confirm YES or NO."
    )


def build_assignment_template_parameters(shipment: Shipment) -> tuple[str, ...]:
    """Return values in the order required by the driver utility template."""

    data = shipment.extracted_data or {}
    return (
        str(data.get("party_name") or "Unknown party"),
        str(data.get("truck_number") or "Unknown"),
        str(data.get("destination") or "Unknown"),
        _format_currency(data.get("advance_paid")),
        _format_currency(data.get("balance_due")),
    )


def _format_currency(amount: object) -> str:
    if not isinstance(amount, int):
        return "not stated"
    return f"₹{amount:,}"


def assign_driver_for_shipment(db: Session, shipment_id: int) -> Optional[DriverAssignment]:
    """Match, assign, and prepare a confirmation message for one ACCEPTED shipment.

    Idempotent: returns ``None`` without doing anything if a driver has
    already been assigned/notified for this shipment (the dedup guard
    against a duplicate webhook re-triggering this same step), or if no
    driver matches the extracted truck number -- a missing match is
    logged and handled gracefully, never raised, since it is an
    expected real-world outcome (unregistered truck), not a system
    failure.

    ``driver_message_sent_at`` is set here, in the same commit as the
    assignment -- *before* the caller actually sends the WhatsApp
    message -- so a duplicate invocation (e.g. a redelivered webhook)
    can never re-assign or re-send even if the actual send that
    follows this call fails or is slow. The trade-off is deliberate:
    an occasional missed send on a transient failure is preferable to
    ever double-messaging a driver.
    """

    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        logger.warning("driver_assignment_shipment_missing shipment_id=%s", shipment_id)
        return None

    if shipment.driver_message_sent_at is not None:
        logger.info(
            "driver_assignment_skipped shipment_id=%s reason=already_notified",
            shipment_id,
        )
        return None

    truck_number = (shipment.extracted_data or {}).get("truck_number")
    if not truck_number:
        logger.info(
            "driver_assignment_skipped shipment_id=%s reason=no_truck_number",
            shipment_id,
        )
        return None

    driver = find_driver_by_truck_number(db, truck_number)
    if driver is None:
        logger.warning(
            "driver_not_found shipment_id=%s truck_number=%s",
            shipment_id,
            truck_number,
        )
        return None

    message = build_assignment_message(shipment)

    shipment.driver_id = driver.id
    shipment.driver_confirmation_status = DriverConfirmationStatus.PENDING
    shipment.driver_message_sent_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(
        "driver_assigned shipment_id=%s driver_id=%s truck_number=%s",
        shipment_id,
        driver.id,
        truck_number,
    )
    return DriverAssignment(
        driver=driver,
        message=message,
        template_parameters=build_assignment_template_parameters(shipment),
    )
