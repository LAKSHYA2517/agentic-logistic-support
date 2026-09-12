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
    """Insert any configured demo drivers that are not already present.

    A driver in ``_DEMO_DRIVERS`` is skipped (not an error) when its
    settings attribute has no configured phone number -- only the
    drivers you actually intend to demo with need a real number. Safe
    to call on every startup: matches on phone number, so re-running
    never creates duplicates.
    """
    created = 0
    for name, truck_number, phone_setting in _DEMO_DRIVERS:
        phone = getattr(settings, phone_setting, None)
        if not phone:
            continue

        existing = session.scalar(select(Driver).where(Driver.phone == phone))
        if existing is not None:
            continue

        canonical_truck_number = normalize_truck_number(truck_number) or truck_number
        session.add(Driver(name=name, phone=phone, truck_number=canonical_truck_number))
        created += 1

    if created:
        session.commit()
        logger.info("demo_drivers_seeded count=%s", created)
    return created
