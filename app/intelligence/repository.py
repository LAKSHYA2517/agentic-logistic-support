"""Integration boundary between Phase 2 (this package) and Phase 1.

``Shipment`` retrieval, persistence, the actual DB schema, and status
transitions belong entirely to Phase 1. Phase 2 does not know the
Phase 1 schema and must not guess at it, so this file defines only the
*shape* of the contract Phase 1 is expected to implement after the two
branches are merged.

Importantly: ``app.intelligence.service.process_audio`` never imports
or calls anything in this file. ``shipment_id`` is treated as an
opaque identifier throughout the Phase 2 pipeline -- it is never used
to look anything up. ``ShipmentRepository`` exists purely so that:

1. There is a single, precise, reviewable definition of what Phase 1
   needs to implement post-merge.
2. The Phase 2 test suite has something concrete to exercise the
   intended round trip against: run ``process_audio`` to get a
   ``ProcessingResult``, then apply it through a repository exactly
   the way the real Phase 1 integration code will.

``InMemoryShipmentRepository`` is that concrete stand-in for tests. It
stores everything in plain dicts, so it cannot assume -- and cannot
drift out of sync with -- the real Phase 1 schema.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.intelligence.models import LogisticsExtraction


class ShipmentRepository(Protocol):
    """Contract Phase 1 implements against its own database schema."""

    async def get_shipment(self, shipment_id: int) -> Any:
        """Fetch whatever Phase 1 considers "the shipment". Opaque to Phase 2."""
        ...

    async def apply_extraction(self, shipment_id: int, extraction: LogisticsExtraction) -> None:
        """Persist a validated, ACCEPTED extraction's fields onto the shipment."""
        ...

    async def mark_in_transit(self, shipment_id: int) -> None:
        """Transition the shipment's status to IN_TRANSIT.

        Phase 2 never calls this. It is invoked by Phase 1's own
        integration code, and only after it has independently decided
        a ``ProcessingResult`` with ``status == ACCEPTED`` warrants it.
        """
        ...


class InMemoryShipmentRepository:
    """Minimal fake ``ShipmentRepository`` for tests.

    Not a preview of the real Phase 1 implementation -- just enough of
    the Protocol, backed by dicts/sets, to let Phase 2 integration
    tests simulate what Phase 1's integration code will eventually do
    with a ``ProcessingResult``.
    """

    def __init__(self) -> None:
        self.shipments: dict[int, Any] = {}
        self.applied_extractions: dict[int, LogisticsExtraction] = {}
        self.in_transit: set[int] = set()

    def seed(self, shipment_id: int, shipment: Any = None) -> None:
        """Test helper: register a shipment so ``get_shipment`` can find it."""
        self.shipments[shipment_id] = shipment if shipment is not None else {"id": shipment_id}

    async def get_shipment(self, shipment_id: int) -> Any:
        return self.shipments.get(shipment_id)

    async def apply_extraction(self, shipment_id: int, extraction: LogisticsExtraction) -> None:
        self.applied_extractions[shipment_id] = extraction

    async def mark_in_transit(self, shipment_id: int) -> None:
        self.in_transit.add(shipment_id)
