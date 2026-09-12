"""Persistence adapter for applying intelligence results to Phase 1 shipments."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.intelligence.models import ProcessingResult, ProcessingStatus
from app.models import Shipment, ShipmentStatus


class ShipmentRepository:
    """Update the canonical SQLAlchemy ``Shipment`` through one session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_shipment(self, shipment_id: int) -> Shipment | None:
        """Return a shipment by primary key without creating another DB layer."""

        return self._session.get(Shipment, shipment_id)

    def mark_processing_started(self, shipment: Shipment) -> None:
        """Record the transition from downloaded media to transcription."""

        shipment.status = ShipmentStatus.TRANSCRIBING
        shipment.processing_started_at = datetime.now(timezone.utc)
        shipment.processing_completed_at = None
        shipment.processing_error = None
        self._commit()

    def apply_result(self, shipment: Shipment, result: ProcessingResult) -> None:
        """Persist a completed pipeline result on the same shipment row."""

        shipment.transcript = result.transcript
        shipment.extracted_data = (
            result.extraction.model_dump(mode="json")
            if result.extraction is not None
            else None
        )
        shipment.processing_completed_at = datetime.now(timezone.utc)

        if result.status is ProcessingStatus.ACCEPTED:
            shipment.status = ShipmentStatus.COMPLETED
            shipment.processing_error = None
        elif result.status is ProcessingStatus.NEEDS_REVIEW:
            shipment.status = ShipmentStatus.PARSED
            shipment.processing_error = result.reason
        else:
            shipment.status = ShipmentStatus.FAILED
            shipment.processing_error = result.reason

        self._commit()

    def mark_failed(self, shipment: Shipment, reason: str) -> None:
        """Persist an integration-level failure without discarding Phase 1 data."""

        shipment.status = ShipmentStatus.FAILED
        shipment.processing_error = reason
        shipment.processing_completed_at = datetime.now(timezone.utc)
        self._commit()

    def _commit(self) -> None:
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
