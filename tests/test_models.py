from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, upgrade_local_sqlite_schema
from app.models import Shipment, ShipmentStatus, User, UserRole


@pytest.fixture
def db_session(tmp_path: Path) -> Generator[Session, None, None]:
    database_path = tmp_path / "test.db"
    test_engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(test_engine)

    with Session(test_engine) as session:
        yield session

    test_engine.dispose()


def test_create_and_query_user_with_shipment(db_session: Session) -> None:
    raw_event = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "example-entry"}],
    }
    user = User(whatsapp_number="+919876543210", role=UserRole.OWNER)
    shipment = Shipment(
        user=user,
        media_id="example-media-id",
        raw_event=raw_event,
    )
    db_session.add(shipment)
    db_session.commit()
    db_session.expire_all()

    stored_user = db_session.scalar(
        select(User).where(User.whatsapp_number == "+919876543210")
    )
    stored_shipment = db_session.scalar(select(Shipment))

    assert stored_user is not None
    assert stored_shipment is not None
    assert stored_user.shipments == [stored_shipment]
    assert stored_shipment.user == stored_user
    assert stored_shipment.status is ShipmentStatus.RECEIVED
    assert stored_shipment.raw_event == raw_event
    assert stored_shipment.media_path is None
    assert stored_shipment.transcript is None
    assert stored_shipment.extracted_data is None
    assert stored_shipment.processing_error is None
    assert stored_shipment.created_at is not None
    assert stored_shipment.updated_at is not None


def test_whatsapp_number_must_be_unique(db_session: Session) -> None:
    db_session.add_all(
        [
            User(whatsapp_number="+919876543210", role=UserRole.OWNER),
            User(whatsapp_number="+919876543210", role=UserRole.TRANSPORTER),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_meta_message_id_must_be_unique_when_present(db_session: Session) -> None:
    user = User(whatsapp_number="+919999999999", role=UserRole.TRANSPORTER)
    db_session.add_all(
        [
            Shipment(user=user, message_id="wamid.duplicate", raw_event={"event": 1}),
            Shipment(user=user, message_id="wamid.duplicate", raw_event={"event": 2}),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_sqlite_upgrade_adds_intelligence_columns_without_losing_rows(tmp_path: Path) -> None:
    old_engine = create_engine(f"sqlite:///{tmp_path / 'old-phase1.db'}")
    with old_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE shipments (id INTEGER PRIMARY KEY, raw_event JSON NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO shipments (id, raw_event) VALUES (1, '{\"kept\": true}')"
        )

    upgrade_local_sqlite_schema(old_engine)

    columns = {item["name"] for item in inspect(old_engine).get_columns("shipments")}
    assert {
        "transcript",
        "extracted_data",
        "processing_error",
        "processing_started_at",
        "processing_completed_at",
    } <= columns
    with old_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM shipments").scalar() == 1

    old_engine.dispose()
