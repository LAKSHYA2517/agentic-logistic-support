"""Read-only shipment and driver feeds for the operations dashboard.

This module only reshapes existing ``Shipment`` and ``Driver`` rows for
the UI. It never mutates the WhatsApp workflow or invents dashboard data.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Driver, DriverConfirmationStatus, Shipment, ShipmentStatus

router = APIRouter(prefix="/api", tags=["dashboard"])

# Shipments are returned newest-updated-first; a hackathon dashboard has
# no pagination UI, so a generous fixed cap stands in for real paging.
_MAX_SHIPMENTS_RETURNED = 500


@router.get("/shipments")
def list_shipments(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Return every shipment in the shape the dashboard expects."""

    shipments = db.scalars(
        select(Shipment)
        .options(selectinload(Shipment.driver))
        .order_by(Shipment.updated_at.desc())
        .limit(_MAX_SHIPMENTS_RETURNED)
    ).all()
    return [_serialize(shipment) for shipment in shipments]


@router.get("/drivers")
def list_drivers(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Return every registered driver and their current assignment, if any."""

    drivers = db.scalars(select(Driver).order_by(Driver.name, Driver.id)).all()
    active_shipments = db.scalars(
        select(Shipment)
        .where(
            Shipment.driver_id.is_not(None),
            or_(
                Shipment.status == ShipmentStatus.IN_TRANSIT,
                and_(
                    Shipment.status == ShipmentStatus.COMPLETED,
                    Shipment.driver_confirmation_status.in_(
                        (
                            DriverConfirmationStatus.PENDING,
                            DriverConfirmationStatus.CONFIRMED,
                        )
                    ),
                ),
            ),
        )
        .order_by(Shipment.updated_at.desc(), Shipment.id.desc())
    ).all()

    current_by_driver: dict[int, Shipment] = {}
    for shipment in active_shipments:
        if shipment.driver_id is not None:
            current_by_driver.setdefault(shipment.driver_id, shipment)

    return [
        _serialize_driver(driver, current_by_driver.get(driver.id))
        for driver in drivers
    ]


def _serialize(shipment: Shipment) -> dict[str, Any]:
    extracted = shipment.extracted_data or {}
    driver = shipment.driver

    return {
        "id": f"SHP-{shipment.id}",
        "party_name": extracted.get("party_name"),
        "truck_number": extracted.get("truck_number") or (driver.truck_number if driver else None),
        "origin": None,  # not captured by the voice extraction pipeline
        "destination": extracted.get("destination"),
        "advance_paid": extracted.get("advance_paid") or 0,
        "balance_due": extracted.get("balance_due") or 0,
        "status": _dashboard_status(shipment),
        "updated_at": (shipment.updated_at or shipment.created_at).isoformat(),
        "source_voice_note": shipment.transcript,
        "driver_name": driver.name if driver else None,
        "driver_phone": driver.phone if driver else None,
        "driver_confirmation_status": (
            shipment.driver_confirmation_status.value
            if shipment.driver_confirmation_status
            else None
        ),
    }


def _serialize_driver(driver: Driver, shipment: Optional[Shipment]) -> dict[str, Any]:
    extracted = shipment.extracted_data or {} if shipment else {}
    return {
        "id": driver.id,
        "name": driver.name,
        "phone": driver.phone,
        "truck_number": driver.truck_number,
        "availability": "OCCUPIED" if shipment else "FREE",
        "current_shipment_id": f"SHP-{shipment.id}" if shipment else None,
        "current_status": _dashboard_status(shipment) if shipment else None,
        "destination": extracted.get("destination"),
        "party_name": extracted.get("party_name"),
    }


def _dashboard_status(shipment: Shipment) -> str:
    """Map backend lifecycle fields to one clear operations status."""

    if shipment.status is ShipmentStatus.DELIVERED:
        return "DELIVERED"

    if shipment.status is ShipmentStatus.IN_TRANSIT:
        return "IN_TRANSIT"

    if shipment.status in (ShipmentStatus.FAILED, ShipmentStatus.PARSED):
        return "NEEDS_REVIEW"

    if shipment.status is ShipmentStatus.COMPLETED:
        confirmation: Optional[DriverConfirmationStatus] = shipment.driver_confirmation_status
        if confirmation is DriverConfirmationStatus.CONFIRMED:
            return "IN_TRANSIT"
        if confirmation is DriverConfirmationStatus.REJECTED:
            return "NEEDS_REVIEW"
        if confirmation is DriverConfirmationStatus.PENDING and shipment.driver_id is not None:
            return "ASSIGNED"
        return "NEEDS_REVIEW"

    # RECEIVED / TRANSCRIBING / PROCESSING / CONFIRMED are not yet assigned.
    return "PROCESSING"
