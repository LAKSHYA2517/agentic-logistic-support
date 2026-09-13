from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import AppSettings
from app.database import Base
from app.intelligence.models import LogisticsExtraction, ProcessingResult, ProcessingStatus
from app.models import (
    Driver,
    DriverConfirmationStatus,
    Shipment,
    ShipmentStatus,
    User,
    UserRole,
)
from app.services.processing import ShipmentTaskRunner
from app.services.workflow_messages import (
    driver_assignment_message,
    driver_pod_verified_message,
    missing_assignment_fields,
    owner_assignment_success_message,
    owner_details_correction_message,
    owner_delivery_complete_message,
    owner_missing_details_message,
    pod_review_message,
)


@pytest.fixture
def workflow_store(tmp_path: Path) -> Generator[tuple[sessionmaker, int], None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'workflow-messages.db'}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with factory() as session:
        owner = User(whatsapp_number="919054256282", role=UserRole.OWNER)
        driver = Driver(
            name="Rajesh Kumar",
            phone="919317708038",
            truck_number="RJ14GB1122",
        )
        shipment = Shipment(
            user=owner,
            driver=driver,
            status=ShipmentStatus.IN_TRANSIT,
            raw_event={"source": "test"},
            extracted_data={
                "party_name": "Ramesh Traders",
                "truck_number": "RJ14GB1122",
                "destination": "Delhi",
                "advance_paid": 10000,
                "balance_due": 25000,
            },
            driver_confirmation_status=DriverConfirmationStatus.CONFIRMED,
        )
        session.add(shipment)
        session.commit()
        shipment_id = shipment.id
    yield factory, shipment_id
    engine.dispose()


def test_assignment_and_owner_messages_use_natural_hinglish() -> None:
    assignment = driver_assignment_message(
        driver_name="Rajesh Kumar",
        party="Ramesh Traders",
        truck="RJ14GB1122",
        destination="Delhi",
        advance=10000,
        balance=25000,
    )

    assert assignment.startswith("Namaste Rajesh Kumar ji 👋")
    assert "Aapko ek nayi delivery assign hui hai" in assignment
    assert "Remaining: ₹25,000" in assignment
    assert "YES reply karein" in assignment
    assert "New shipment assigned" not in assignment
    assert owner_assignment_success_message("Rajesh Kumar") == (
        "Delivery assign ho gayi hai ✅\n"
        "Rajesh Kumar ko shipment ki saari details bhej di hain.\n"
        "Ab driver ke confirmation ka wait kar rahe hain."
    )


def test_missing_fields_are_named_without_inventing_values() -> None:
    missing = missing_assignment_fields(
        LogisticsExtraction(
            party_name="Ramesh Traders",
            truck_number="RJ14GB1122",
            advance_paid=10000,
        )
    )

    assert missing == ["destination", "remaining balance"]
    assert owner_missing_details_message(missing) == (
        "Sir, kuch details miss ho gayi hain — destination aur remaining balance "
        "nahi mila. Please ek baar voice note dobara bhej dijiye, saari details ke saath."
    )


def test_invalid_and_missing_voice_fields_are_explained_without_values() -> None:
    message = owner_details_correction_message(
        missing_fields=["destination", "advance", "remaining balance"],
        invalid_fields=["party/consignee", "truck number"],
    )

    assert "destination, advance aur remaining balance nahi mila" in message
    assert "party/consignee aur truck number clear ya valid nahi tha" in message
    assert "voice note dobara bhej dijiye" in message


async def test_confirmation_messages_and_one_minute_pod_reminder(workflow_store) -> None:
    factory, shipment_id = workflow_store
    sent: list[tuple[str, str]] = []
    delays: list[float] = []

    def sender(to: str, body: str) -> None:
        sent.append((to, body))

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    runner = ShipmentTaskRunner(
        settings=AppSettings(),
        session_factory=factory,
        message_sender=sender,
        sleeper=sleeper,
    )

    await runner.notify_driver_confirmation(shipment_id)

    assert delays == [60.0]
    assert [recipient for recipient, _ in sent] == [
        "919317708038",
        "919054256282",
        "919317708038",
    ]
    assert "Shipment ab IN TRANSIT hai" in sent[0][1]
    assert "Rajesh Kumar ne delivery confirm kar di hai" in sent[1][1]
    assert "POD/proof of delivery ka photo bhej dijiye" in sent[2][1]


async def test_missing_voice_fields_notify_owner_and_skip_assignment(workflow_store) -> None:
    factory, shipment_id = workflow_store
    sent: list[tuple[str, str]] = []
    driver_notifications: list[int] = []
    with factory() as session:
        shipment = session.get(Shipment, shipment_id)
        assert shipment is not None
        shipment.status = ShipmentStatus.COMPLETED
        shipment.extracted_data = {
            "party_name": "Ramesh Traders",
            "truck_number": "RJ14GB1122",
            "destination": None,
            "advance_paid": 10000,
            "balance_due": None,
        }
        session.commit()

    def sender(to: str, body: str) -> None:
        sent.append((to, body))

    async def driver_notifier(target_id: int) -> None:
        driver_notifications.append(target_id)

    runner = ShipmentTaskRunner(
        settings=AppSettings(),
        session_factory=factory,
        driver_notifier=driver_notifier,
        message_sender=sender,
    )

    await runner._notify_driver_if_accepted(shipment_id)

    assert driver_notifications == []
    assert sent == [
        (
            "919054256282",
            "Sir, kuch details miss ho gayi hain — destination aur remaining balance "
            "nahi mila. Please ek baar voice note dobara bhej dijiye, saari details ke saath.",
        )
    ]


async def test_failed_validation_notifies_owner_with_safe_field_categories(
    workflow_store,
) -> None:
    factory, shipment_id = workflow_store
    sent: list[tuple[str, str]] = []
    driver_notifications: list[int] = []
    with factory() as session:
        shipment = session.get(Shipment, shipment_id)
        assert shipment is not None
        shipment.status = ShipmentStatus.FAILED
        shipment.extracted_data = None
        session.commit()

    def sender(to: str, body: str) -> None:
        sent.append((to, body))

    async def driver_notifier(target_id: int) -> None:
        driver_notifications.append(target_id)

    runner = ShipmentTaskRunner(
        settings=AppSettings(),
        session_factory=factory,
        driver_notifier=driver_notifier,
        message_sender=sender,
    )
    result = ProcessingResult(
        shipment_id=shipment_id,
        status=ProcessingStatus.FAILED,
        transcript="untrusted transcript",
        reason="No extracted values were trustworthy.",
        missing_fields=["destination", "advance_paid", "balance_due"],
        invalid_fields=["party_name", "truck_number"],
    )

    await runner._notify_driver_if_accepted(shipment_id, result)

    assert driver_notifications == []
    assert len(sent) == 1
    assert sent[0][0] == "919054256282"
    assert "destination, advance aur remaining balance nahi mila" in sent[0][1]
    assert "party/consignee aur truck number clear ya valid nahi tha" in sent[0][1]


def test_pod_messages_are_actionable_hinglish() -> None:
    wrong_truck = pod_review_message(
        "Rajesh Kumar",
        "POD truck number MH12AB1234 conflicts with shipment truck RJ14GB1122.",
    )

    assert "POD verify nahi ho paaya" in wrong_truck
    assert "Truck number match nahi kar raha hai" in wrong_truck
    assert "correct POD ka photo dobara bhej dijiye" in wrong_truck
    assert pod_review_message("Rajesh Kumar", "POD destination was missing") == (
        "POD mein destination clearly nahi mila.\n"
        "Please aisa POD/photo bhejiye jisme destination clearly visible ho."
    )
    assert "DELIVERED mark" in driver_pod_verified_message("Rajesh Kumar")
    assert owner_delivery_complete_message() == (
        "Delivery successfully complete ho gayi hai ✅\n"
        "POD verify ho gaya aur shipment DELIVERED mark kar diya gaya hai."
    )
    detailed_owner_message = owner_delivery_complete_message(
        shipment_id=7,
        party="Ramesh Traders",
        driver="Rajesh Kumar",
        truck="RJ14GB1122",
        destination="Delhi",
        advance=10000,
        balance=25000,
    )
    assert "Shipment: SHP-7" in detailed_owner_message
    assert "Party: Ramesh Traders" in detailed_owner_message
    assert "Driver: Rajesh Kumar" in detailed_owner_message
    assert "Advance: ₹10,000" in detailed_owner_message
    assert "Remaining: ₹25,000" in detailed_owner_message
