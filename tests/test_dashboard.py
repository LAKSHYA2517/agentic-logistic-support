from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Driver, DriverConfirmationStatus, Shipment, ShipmentStatus, User, UserRole


@pytest.fixture
def client(tmp_path: Path) -> Generator[tuple[TestClient, sessionmaker], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dashboard-test.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, session_factory
    app.dependency_overrides.clear()
    engine.dispose()


def _make_shipment(session: Session, **kwargs) -> Shipment:
    user = session.query(User).first()
    if user is None:
        user = User(whatsapp_number="919876500000", role=UserRole.TRANSPORTER)
        session.add(user)
        session.commit()

    shipment = Shipment(
        user=user,
        raw_event={"object": "whatsapp_business_account"},
        **kwargs,
    )
    session.add(shipment)
    session.commit()
    session.refresh(shipment)
    return shipment


def test_no_shipments_returns_empty_list(client):
    test_client, _ = client

    response = test_client.get("/api/shipments")

    assert response.status_code == 200
    assert response.json() == []


def test_shipment_without_extraction_yet_is_processing(client):
    test_client, session_factory = client
    with session_factory() as session:
        shipment = _make_shipment(session, status=ShipmentStatus.RECEIVED)
        shipment_id = shipment.id

    body = test_client.get("/api/shipments").json()

    assert len(body) == 1
    entry = body[0]
    assert entry["id"] == f"SHP-{shipment_id}"
    assert entry["status"] == "PROCESSING"
    assert entry["party_name"] is None
    assert entry["advance_paid"] == 0
    assert entry["balance_due"] == 0


def test_accepted_shipment_with_no_driver_assigned_needs_review(client):
    test_client, session_factory = client
    with session_factory() as session:
        _make_shipment(
            session,
            status=ShipmentStatus.COMPLETED,
            extracted_data={
                "party_name": "Ramesh Traders",
                "truck_number": "RJ14GB1122",
                "destination": "Delhi",
                "advance_paid": 10000,
                "balance_due": 25000,
            },
        )

    entry = test_client.get("/api/shipments").json()[0]

    assert entry["status"] == "NEEDS_REVIEW"
    assert entry["party_name"] == "Ramesh Traders"
    assert entry["truck_number"] == "RJ14GB1122"
    assert entry["destination"] == "Delhi"
    assert entry["advance_paid"] == 10000
    assert entry["balance_due"] == 25000


def test_accepted_shipment_with_driver_pending_reply_is_assigned(client):
    test_client, session_factory = client
    with session_factory() as session:
        driver = Driver(name="Rajesh Kumar", phone="919317708038", truck_number="RJ14GB1122")
        session.add(driver)
        session.commit()
        _make_shipment(
            session,
            status=ShipmentStatus.COMPLETED,
            extracted_data={"truck_number": "RJ14GB1122"},
            driver=driver,
            driver_confirmation_status=DriverConfirmationStatus.PENDING,
        )

    entry = test_client.get("/api/shipments").json()[0]

    assert entry["status"] == "ASSIGNED"
    assert entry["driver_name"] == "Rajesh Kumar"
    assert entry["driver_confirmation_status"] == "PENDING"


def test_accepted_shipment_with_driver_confirmed_is_in_transit(client):
    test_client, session_factory = client
    with session_factory() as session:
        driver = Driver(name="Rajesh Kumar", phone="919317708038", truck_number="RJ14GB1122")
        session.add(driver)
        session.commit()
        _make_shipment(
            session,
            status=ShipmentStatus.COMPLETED,
            extracted_data={"truck_number": "RJ14GB1122"},
            driver=driver,
            driver_confirmation_status=DriverConfirmationStatus.CONFIRMED,
        )

    entry = test_client.get("/api/shipments").json()[0]

    assert entry["status"] == "IN_TRANSIT"


def test_explicit_in_transit_and_delivered_statuses_reach_dashboard(client):
    test_client, session_factory = client
    with session_factory() as session:
        in_transit = _make_shipment(session, status=ShipmentStatus.IN_TRANSIT)
        delivered = _make_shipment(session, status=ShipmentStatus.DELIVERED)

    entries = {item["id"]: item for item in test_client.get("/api/shipments").json()}

    assert entries[f"SHP-{in_transit.id}"]["status"] == "IN_TRANSIT"
    assert entries[f"SHP-{delivered.id}"]["status"] == "DELIVERED"


def test_accepted_shipment_with_driver_rejected_needs_review(client):
    test_client, session_factory = client
    with session_factory() as session:
        driver = Driver(name="Rajesh Kumar", phone="919317708038", truck_number="RJ14GB1122")
        session.add(driver)
        session.commit()
        _make_shipment(
            session,
            status=ShipmentStatus.COMPLETED,
            extracted_data={"truck_number": "RJ14GB1122"},
            driver=driver,
            driver_confirmation_status=DriverConfirmationStatus.REJECTED,
        )

    entry = test_client.get("/api/shipments").json()[0]

    assert entry["status"] == "NEEDS_REVIEW"


def test_parsed_shipment_needs_review(client):
    test_client, session_factory = client
    with session_factory() as session:
        _make_shipment(session, status=ShipmentStatus.PARSED)

    entry = test_client.get("/api/shipments").json()[0]

    assert entry["status"] == "NEEDS_REVIEW"


def test_failed_shipment_needs_review(client):
    test_client, session_factory = client
    with session_factory() as session:
        _make_shipment(session, status=ShipmentStatus.FAILED)

    entry = test_client.get("/api/shipments").json()[0]

    assert entry["status"] == "NEEDS_REVIEW"


def test_response_shape_matches_dashboard_expectations(client):
    test_client, session_factory = client
    with session_factory() as session:
        _make_shipment(
            session,
            status=ShipmentStatus.COMPLETED,
            transcript="Ramesh ko truck RJ14GB1122 se advance das hazaar diya",
            extracted_data={
                "party_name": "Ramesh Traders",
                "truck_number": "RJ14GB1122",
                "destination": "Delhi",
                "advance_paid": 10000,
                "balance_due": 25000,
            },
        )

    entry = test_client.get("/api/shipments").json()[0]

    assert set(entry) == {
        "id",
        "party_name",
        "truck_number",
        "origin",
        "destination",
        "advance_paid",
        "balance_due",
        "status",
        "updated_at",
        "source_voice_note",
        "driver_name",
        "driver_phone",
        "driver_confirmation_status",
    }
    assert isinstance(entry["id"], str)
    assert entry["source_voice_note"] == "Ramesh ko truck RJ14GB1122 se advance das hazaar diya"


def test_drivers_endpoint_reports_free_and_occupied_drivers(client):
    test_client, session_factory = client
    with session_factory() as session:
        rajesh = Driver(
            name="Rajesh Kumar",
            phone="919317708038",
            truck_number="RJ14GB1122",
        )
        suresh = Driver(
            name="Suresh Singh",
            phone="919638412941",
            truck_number="MH12AB1234",
        )
        session.add_all([rajesh, suresh])
        session.commit()
        shipment = _make_shipment(
            session,
            status=ShipmentStatus.IN_TRANSIT,
            extracted_data={
                "party_name": "Ramesh Traders",
                "destination": "Delhi",
            },
            driver=rajesh,
            driver_confirmation_status=DriverConfirmationStatus.CONFIRMED,
        )
        shipment_id = shipment.id

    body = test_client.get("/api/drivers").json()

    assert body == [
        {
            "id": rajesh.id,
            "name": "Rajesh Kumar",
            "phone": "919317708038",
            "truck_number": "RJ14GB1122",
            "availability": "OCCUPIED",
            "current_shipment_id": f"SHP-{shipment_id}",
            "current_status": "IN_TRANSIT",
            "destination": "Delhi",
            "party_name": "Ramesh Traders",
        },
        {
            "id": suresh.id,
            "name": "Suresh Singh",
            "phone": "919638412941",
            "truck_number": "MH12AB1234",
            "availability": "FREE",
            "current_shipment_id": None,
            "current_status": None,
            "destination": None,
            "party_name": None,
        },
    ]


def test_delivered_shipment_releases_driver(client):
    test_client, session_factory = client
    with session_factory() as session:
        driver = Driver(
            name="Rajesh Kumar",
            phone="919317708038",
            truck_number="RJ14GB1122",
        )
        session.add(driver)
        session.commit()
        _make_shipment(
            session,
            status=ShipmentStatus.DELIVERED,
            extracted_data={"destination": "Delhi"},
            driver=driver,
            driver_confirmation_status=DriverConfirmationStatus.CONFIRMED,
        )

    entry = test_client.get("/api/drivers").json()[0]

    assert entry["availability"] == "FREE"
    assert entry["destination"] is None
