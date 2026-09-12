"""Read-only shipment feed for the operations dashboard.

The dashboard (``ansh`` branch, copied into ``dashboard/``) was built
against a mocked WebSocket payload shape:
``{id, party_name, truck_number, origin, destination, advance_paid,
balance_due, status, updated_at, source_voice_note}`` with ``status``
one of ``PENDING_LOADING | IN_TRANSIT | DELAYED | DELIVERED |
PAYMENT_PENDING`` (see ``dashboard/src/utils/constants.js``).

This module is the one place that bridges that shape to the real
``Shipment``/``Driver`` rows: it never mutates anything, and it does
not change what the seller/driver WhatsApp workflow does -- it only
reads and reshapes state that workflow already produces.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DriverConfirmationStatus, Shipment, ShipmentStatus

router = APIRouter(prefix="/api", tags=["dashboard"])

# Shipments are returned newest-updated-first; a hackathon dashboard has
# no pagination UI, so a generous fixed cap stands in for real paging.
_MAX_SHIPMENTS_RETURNED = 500


@router.get("/shipments")
def list_shipments(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Return every shipment in the shape the dashboard expects."""

    shipments = db.scalars(
        select(Shipment).order_by(Shipment.updated_at.desc()).limit(_MAX_SHIPMENTS_RETURNED)
    ).all()
    return [_serialize(shipment) for shipment in shipments]


def _serialize(shipment: Shipment) -> dict[str, Any]:
    extracted = shipment.extracted_data or {}
    driver = shipment.driver

    return {
        "id": f"SHP-{shipment.id}",
        "party_name": extracted.get("party_name"),
        "truck_number": extracted.get("truck_number"),
        "origin": None,  # not captured by the voice extraction pipeline
        "destination": extracted.get("destination"),
        "advance_paid": extracted.get("advance_paid") or 0,
        "balance_due": extracted.get("balance_due") or 0,
        "status": _dashboard_status(shipment),
        "updated_at": (shipment.updated_at or shipment.created_at).isoformat(),
        "source_voice_note": shipment.transcript,
        # Extra fields the current dashboard UI doesn't render yet, kept
        # available for future components without another backend change.
        "driver_name": driver.name if driver else None,
        "driver_phone": driver.phone if driver else None,
        "driver_confirmation_status": (
            shipment.driver_confirmation_status.value
            if shipment.driver_confirmation_status
            else None
        ),
    }


def _dashboard_status(shipment: Shipment) -> str:
    """Map the real (Shipment status, driver confirmation) pair to one dashboard status.

    The dashboard's lifecycle has no separate "driver acceptance" axis --
    it folds everything into a single status badge -- so a driver's
    WhatsApp YES/NO reply has to show up as a *status change*, not a new
    field: CONFIRMED promotes an accepted shipment to "in transit";
    REJECTED (or an intelligence failure) surfaces as "delayed" so it's
    visibly flagged for attention.
    """

    if shipment.status in (ShipmentStatus.FAILED, ShipmentStatus.PARSED):
        # PARSED means Phase 2 flagged the extraction for human review
        # (NEEDS_REVIEW) -- that is an exception state, not a routine
        # "still loading" one.
        return "DELAYED"

    if shipment.status is ShipmentStatus.COMPLETED:
        confirmation: Optional[DriverConfirmationStatus] = shipment.driver_confirmation_status
        if confirmation is DriverConfirmationStatus.CONFIRMED:
            return "IN_TRANSIT"
        if confirmation is DriverConfirmationStatus.REJECTED:
            return "DELAYED"
        # ACCEPTED by intelligence, but no driver confirmation yet
        # (still PENDING, or no driver could be matched at all).
        return "PENDING_LOADING"

    # RECEIVED / TRANSCRIBING / PROCESSING / CONFIRMED: still on the way
    # to a first result.
    return "PENDING_LOADING"
