from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.database import Base
from app.models import Driver
from app.seed import seed_demo_drivers


@pytest.fixture
def db_session(tmp_path: Path) -> Generator[Session, None, None]:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'test-seed.db'}")
    Base.metadata.create_all(test_engine)

    with Session(test_engine) as session:
        yield session

    test_engine.dispose()


@pytest.fixture(autouse=True)
def _isolate_demo_phone_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # AppSettings() falls back to the real .env for any field not passed
    # explicitly -- without this, these tests would pick up whatever
    # demo driver phones happen to be configured on this machine.
    for var in ("DEMO_DRIVER_PHONE_RAJESH", "DEMO_DRIVER_PHONE_SURESH", "DEMO_DRIVER_PHONE_AMIT"):
        monkeypatch.delenv(var, raising=False)


def test_no_demo_phones_configured_seeds_nothing(db_session: Session):
    settings = AppSettings()

    created = seed_demo_drivers(db_session, settings)

    assert created == 0
    assert db_session.scalar(select(Driver)) is None


def test_seeds_only_drivers_with_a_configured_phone(db_session: Session):
    settings = AppSettings(demo_driver_phone_rajesh="919317708038")

    created = seed_demo_drivers(db_session, settings)

    assert created == 1
    driver = db_session.scalar(select(Driver))
    assert driver.name == "Rajesh Kumar"
    assert driver.phone == "919317708038"
    assert driver.truck_number == "RJ14GB1122"


def test_rerunning_with_same_config_does_not_duplicate(db_session: Session):
    settings = AppSettings(demo_driver_phone_rajesh="919317708038")

    seed_demo_drivers(db_session, settings)
    created_again = seed_demo_drivers(db_session, settings)

    assert created_again == 0
    assert db_session.query(Driver).count() == 1


def test_changing_configured_phone_updates_existing_row_without_crashing(db_session: Session):
    # Regression test: this is the exact scenario that used to crash the
    # app on startup with a UNIQUE constraint violation on truck_number
    # -- seeding first with one phone, then restarting with a different
    # phone for the same demo driver (same truck_number).
    seed_demo_drivers(db_session, AppSettings(demo_driver_phone_rajesh="9317708038"))

    created = seed_demo_drivers(db_session, AppSettings(demo_driver_phone_rajesh="919317708038"))

    assert created == 0
    assert db_session.query(Driver).count() == 1
    driver = db_session.scalar(select(Driver).where(Driver.truck_number == "RJ14GB1122"))
    assert driver is not None
    assert driver.phone == "919317708038"
