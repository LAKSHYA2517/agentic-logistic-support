from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Driver, DriverConfirmationStatus, Shipment, ShipmentStatus, User, UserRole
from app.services.pod import register_pod_message, verify_pod
from app.services.webhook import ParsedMetaMessage


# ---------------------------------------------------------------------------
# verify_pod: pure, deterministic -- no DB needed
# ---------------------------------------------------------------------------


def _extraction(**overrides):
    data = {
        "party_name": "Ramesh Traders",
        "truck_number": "RJ14GB1122",
        "destination": "Delhi",
        "advance_paid": 10000,
        "balance_due": 25000,
    }
    data.update(overrides)
    return data


def test_valid_pod_is_delivered():
    pod_text = "Proof of Delivery\nVehicle: RJ14GB1122\nDelivered at Delhi\nReceived in good condition"

    result = verify_pod(pod_text, _extraction())

    assert result.outcome == "DELIVERED"


def test_valid_pod_with_hyphenated_truck_number_is_delivered():
    # The POD is a written document, not a spoken transcript, so the
    # truck number may appear with the usual separator variants.
    pod_text = "Delivery challan. Truck RJ14-GB-1122 arrived Delhi. Signed."

    result = verify_pod(pod_text, _extraction())

    assert result.outcome == "DELIVERED"


def test_wrong_truck_number_needs_review():
    pod_text = "Proof of Delivery\nVehicle: MH12AB1234\nDelivered at Delhi"

    result = verify_pod(pod_text, _extraction())

    assert result.outcome == "NEEDS_REVIEW"
    assert any("MH12AB1234" in reason for reason in result.reasons)


def test_truck_number_absent_from_pod_needs_review():
    # Identity can never be confirmed from a POD that doesn't mention
    # any vehicle number at all -- this must not be auto-delivered.
    pod_text = "Signed and received. Thank you."

    result = verify_pod(pod_text, _extraction())

    assert result.outcome == "NEEDS_REVIEW"


def test_conflicting_destination_needs_review():
    pod_text = "Proof of Delivery\nVehicle: RJ14GB1122\nDelivered at Mumbai"

    result = verify_pod(pod_text, _extraction(destination="Delhi"))

    assert result.outcome == "NEEDS_REVIEW"
    assert any("mumbai" in reason.lower() for reason in result.reasons)


def test_missing_destination_in_pod_does_not_block_delivery():
    # Missing optional information must not automatically fail --
    # truck number matches and the POD simply doesn't mention any city.
    pod_text = "Vehicle RJ14GB1122. Goods received in good condition. Signed by consignee."

    result = verify_pod(pod_text, _extraction(destination="Delhi"))

    assert result.outcome == "DELIVERED"


def test_shipment_with_no_destination_stated_is_not_penalized():
    pod_text = "Vehicle RJ14GB1122 delivered."

    result = verify_pod(pod_text, _extraction(destination=None))

    assert result.outcome == "DELIVERED"


def test_hindi_pod_text_matches_truck_and_destination():
    pod_text = "प्राप्ति रसीद वाहन RJ14GB1122 दिल्ली में डिलीवर किया गया"

    result = verify_pod(pod_text, _extraction())

    assert result.outcome == "DELIVERED"


# ---------------------------------------------------------------------------
# register_pod_message: DB-backed matching + dedup
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session(tmp_path: Path) -> Generator[Session, None, None]:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'test-pod.db'}")
    Base.metadata.create_all(test_engine)

    with Session(test_engine) as session:
        yield session

    test_engine.dispose()


def _in_transit_shipment(db: Session, driver: Driver) -> Shipment:
    user = User(whatsapp_number="919876500099", role=UserRole.TRANSPORTER)
    shipment = Shipment(
        user=user,
        driver=driver,
        status=ShipmentStatus.COMPLETED,
        driver_confirmation_status=DriverConfirmationStatus.CONFIRMED,
        raw_event={"object": "whatsapp_business_account"},
        extracted_data=_extraction(),
    )
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment


def test_register_pod_message_matches_active_shipment(db_session: Session):
    driver = Driver(name="Rajesh Kumar", phone="919317708038", truck_number="RJ14GB1122")
    db_session.add(driver)
    db_session.commit()
    shipment = _in_transit_shipment(db_session, driver)

    message = ParsedMetaMessage(
        sender_number="919317708038",
        message_id="wamid.pod-1",
        media_id="media-pod-1",
        message_type="image",
    )

    result = register_pod_message(db_session, message)

    assert result is not None
    assert result.id == shipment.id
    db_session.refresh(shipment)
    assert shipment.driver_reply_message_id == "wamid.pod-1"


def test_register_pod_message_unknown_sender_is_graceful(db_session: Session):
    message = ParsedMetaMessage(
        sender_number="919999999999",
        message_id="wamid.pod-2",
        media_id="media-pod-2",
        message_type="image",
    )

    assert register_pod_message(db_session, message) is None


def test_register_pod_message_no_active_shipment_is_graceful(db_session: Session):
    driver = Driver(name="Idle Driver", phone="919317708038", truck_number="RJ14GB1122")
    db_session.add(driver)
    db_session.commit()
    # No shipment assigned to this driver at all.

    message = ParsedMetaMessage(
        sender_number="919317708038",
        message_id="wamid.pod-3",
        media_id="media-pod-3",
        message_type="image",
    )

    assert register_pod_message(db_session, message) is None


def test_register_pod_message_only_matches_confirmed_in_transit_shipments(db_session: Session):
    driver = Driver(name="Rajesh Kumar", phone="919317708038", truck_number="RJ14GB1122")
    db_session.add(driver)
    db_session.commit()
    user = User(whatsapp_number="919876500098", role=UserRole.TRANSPORTER)
    # Assigned but not yet confirmed -- not "in transit" yet.
    pending_shipment = Shipment(
        user=user,
        driver=driver,
        status=ShipmentStatus.COMPLETED,
        driver_confirmation_status=DriverConfirmationStatus.PENDING,
        raw_event={"object": "whatsapp_business_account"},
        extracted_data=_extraction(),
    )
    db_session.add(pending_shipment)
    db_session.commit()

    message = ParsedMetaMessage(
        sender_number="919317708038",
        message_id="wamid.pod-4",
        media_id="media-pod-4",
        message_type="image",
    )

    assert register_pod_message(db_session, message) is None


def test_register_pod_message_duplicate_is_ignored(db_session: Session):
    driver = Driver(name="Rajesh Kumar", phone="919317708038", truck_number="RJ14GB1122")
    db_session.add(driver)
    db_session.commit()
    _in_transit_shipment(db_session, driver)

    message = ParsedMetaMessage(
        sender_number="919317708038",
        message_id="wamid.pod-dup",
        media_id="media-pod-dup",
        message_type="image",
    )

    first = register_pod_message(db_session, message)
    second = register_pod_message(db_session, message)

    assert first is not None
    assert second is None


def test_register_pod_message_without_media_is_graceful(db_session: Session):
    driver = Driver(name="Rajesh Kumar", phone="919317708038", truck_number="RJ14GB1122")
    db_session.add(driver)
    db_session.commit()
    _in_transit_shipment(db_session, driver)

    message = ParsedMetaMessage(
        sender_number="919317708038",
        message_id="wamid.pod-5",
        media_id=None,
        message_type="image",
    )

    assert register_pod_message(db_session, message) is None
