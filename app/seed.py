"""Demo data seeding for local development and live demos.

Not a substitute for a real driver-onboarding flow -- this exists so
the driver-assignment demo (seller voice note -> truck match -> WhatsApp
confirmation) has something to match against without a manual setup
step. Phone numbers are read from configuration, never hardcoded, so a
demo operator can point a seeded driver at a real WhatsApp-capable
number they control without editing code.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.intelligence.validation import normalize_truck_number
from app.models import Driver

logger = logging.getLogger(__name__)

# (name, truck_number, AppSettings attribute holding that driver's demo phone)
_DEMO_DRIVERS: tuple[tuple[str, str, str], ...] = (
    ("Rajesh Kumar", "RJ14GB1122", "demo_driver_phone_rajesh"),
    ("Suresh Singh", "MH12AB1234", "demo_driver_phone_suresh"),
    ("Amit Sharma", "DL05CD5678", "demo_driver_phone_amit"),
)


def seed_demo_drivers(session: Session, settings: AppSettings) -> int:
    """Insert or update the configured demo drivers.

    A driver in ``_DEMO_DRIVERS`` is skipped (not an error) when its
    settings attribute has no configured phone number -- only the
    drivers you actually intend to demo with need a real number.

    Matches on ``truck_number`` (each demo driver's stable identity in
    ``_DEMO_DRIVERS``), not phone number: a demo operator changing a
    driver's phone in ``.env`` between restarts (e.g. swapping in a
    different teammate's number) must update the existing row, not
    attempt a second INSERT that collides with the truck_number's
    unique constraint. Safe to call on every startup either way.
    """
    created = 0
    updated = 0
    for name, truck_number, phone_setting in _DEMO_DRIVERS:
        phone = getattr(settings, phone_setting, None)
        if not phone:
            continue

        canonical_truck_number = normalize_truck_number(truck_number) or truck_number
        existing = session.scalar(
            select(Driver).where(Driver.truck_number == canonical_truck_number)
        )
        if existing is not None:
            if existing.phone != phone or existing.name != name:
                existing.phone = phone
                existing.name = name
                updated += 1
            continue

        session.add(Driver(name=name, phone=phone, truck_number=canonical_truck_number))
        created += 1

    if created or updated:
        session.commit()
        logger.info("demo_drivers_seeded created=%s updated=%s", created, updated)
    return created
