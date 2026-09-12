from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Driver, DriverConfirmationStatus, Shipment, ShipmentStatus, User, UserRole
from app.services.drivers import (
    assign_driver_for_shipment,
    build_assignment_message,
    build_assignment_template_parameters,
    find_driver_by_truck_number,
)


@pytest.fixture
def db_session(tmp_path: Path) -> Generator[Session, None, None]:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'test-drivers.db'}")
    Base.metadata.create_all(test_engine)

    with Session(test_engine) as session:
        yield session

    test_engine.dispose()


def _seed_driver(db: Session, *, name="Rajesh Kumar", phone="15550001111", truck="RJ14GB1122") -> Driver:
    driver = Driver(name=name, phone=phone, truck_number=truck)
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


def _accepted_shipment(db: Session, extracted_data: dict) -> Shipment:
    user = User(whatsapp_number="15559998888", role=UserRole.TRANSPORTER)
    shipment = Shipment(
        user=user,
        status=ShipmentStatus.COMPLETED,
        raw_event={"object": "whatsapp_business_account"},
        extracted_data=extracted_data,
    )
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment


# ---------------------------------------------------------------------------
# Driver lookup
# ---------------------------------------------------------------------------


def test_find_driver_by_exact_canonical_truck_number(db_session: Session):
    driver = _seed_driver(db_session)

    found = find_driver_by_truck_number(db_session, "RJ14GB1122")

    assert found is not None
    assert found.id == driver.id


def test_find_driver_tolerates_separator_formatting(db_session: Session):
    _seed_driver(db_session, truck="RJ14GB1122")

    found = find_driver_by_truck_number(db_session, "RJ14-GB-1122")

    assert found is not None
    assert found.truck_number == "RJ14GB1122"


def test_find_driver_no_match_returns_none(db_session: Session):
    _seed_driver(db_session, truck="RJ14GB1122")

    found = find_driver_by_truck_number(db_session, "MH12AB1234")

    assert found is None


# ---------------------------------------------------------------------------
# Assignment message
# ---------------------------------------------------------------------------


def test_build_assignment_message_matches_expected_format(db_session: Session):
    shipment = _accepted_shipment(
        db_session,
        {
            "party_name": "Ramesh Traders",
            "truck_number": "RJ14GB1122",
            "destination": "Delhi",
            "advance_paid": 10000,
            "balance_due": 25000,
        },
    )

    message = build_assignment_message(shipment)

    assert message == (
        "New shipment assigned. Party: Ramesh Traders, Truck: RJ14GB1122, "
        "Destination: Delhi, Advance: ₹10,000, Balance: ₹25,000. "
        "Please confirm YES or NO."
    )


def test_build_assignment_message_handles_missing_amounts(db_session: Session):
    shipment = _accepted_shipment(
        db_session,
        {
            "party_name": "Ramesh Traders",
            "truck_number": "RJ14GB1122",
            "destination": None,
            "advance_paid": None,
            "balance_due": None,
        },
    )

    message = build_assignment_message(shipment)

    assert "Destination: Unknown" in message
    assert "Advance: not stated" in message
    assert "Balance: not stated" in message


def test_build_assignment_template_parameters_match_approved_template_order(
    db_session: Session,
):
    shipment = _accepted_shipment(
        db_session,
        {
            "party_name": "Ramesh Traders",
            "truck_number": "RJ14GB1122",
            "destination": "Delhi",
            "advance_paid": 10000,
            "balance_due": 25000,
        },
    )

    assert build_assignment_template_parameters(shipment) == (
        "Ramesh Traders",
        "RJ14GB1122",
        "Delhi",
        "₹10,000",
        "₹25,000",
    )


# ---------------------------------------------------------------------------
# Assignment: happy path, no-match, and duplicate protection
# ---------------------------------------------------------------------------


def test_assign_driver_for_shipment_happy_path(db_session: Session):
    driver = _seed_driver(db_session)
    shipment = _accepted_shipment(
        db_session,
        {
            "party_name": "Ramesh Traders",
            "truck_number": "RJ14GB1122",
            "destination": "Delhi",
            "advance_paid": 10000,
            "balance_due": 25000,
        },
    )

    assignment = assign_driver_for_shipment(db_session, shipment.id)

    assert assignment is not None
    assert assignment.driver.id == driver.id
    assert "Please confirm YES or NO." in assignment.message

    db_session.refresh(shipment)
    assert shipment.driver_id == driver.id
    assert shipment.driver_confirmation_status == DriverConfirmationStatus.PENDING
    assert shipment.driver_message_sent_at is not None


def test_assign_driver_for_shipment_no_truck_match_is_graceful(db_session: Session):
    _seed_driver(db_session, truck="MH12AB1234")
    shipment = _accepted_shipment(
        db_session,
        {
            "party_name": "Ramesh Traders",
            "truck_number": "RJ14GB1122",
            "destination": "Delhi",
            "advance_paid": 10000,
            "balance_due": 25000,
        },
    )

    assignment = assign_driver_for_shipment(db_session, shipment.id)

    assert assignment is None
    db_session.refresh(shipment)
    assert shipment.driver_id is None
    assert shipment.driver_confirmation_status is None
    assert shipment.driver_message_sent_at is None


def test_assign_driver_for_shipment_missing_truck_number_is_graceful(db_session: Session):
    _seed_driver(db_session)
    shipment = _accepted_shipment(
        db_session,
        {"party_name": "Ramesh Traders", "truck_number": None},
    )

    assignment = assign_driver_for_shipment(db_session, shipment.id)

    assert assignment is None


def test_assign_driver_for_shipment_unknown_shipment_id_is_graceful(db_session: Session):
    assignment = assign_driver_for_shipment(db_session, 999999)

    assert assignment is None


def test_assign_driver_for_shipment_is_idempotent_duplicate_protection(db_session: Session):
    # Regression coverage for "prevent duplicate driver messages when
    # duplicate webhooks arrive": calling this twice for the same
    # shipment (e.g. a retried background task) must only ever assign
    # and notify once.
    driver = _seed_driver(db_session)
    shipment = _accepted_shipment(
        db_session,
        {
            "party_name": "Ramesh Traders",
            "truck_number": "RJ14GB1122",
            "destination": "Delhi",
            "advance_paid": 10000,
            "balance_due": 25000,
        },
    )

    first = assign_driver_for_shipment(db_session, shipment.id)
    second = assign_driver_for_shipment(db_session, shipment.id)

    assert first is not None
    assert first.driver.id == driver.id
    assert second is None
