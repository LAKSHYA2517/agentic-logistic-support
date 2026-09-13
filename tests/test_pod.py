from collections.abc import Generator
from pathlib import Path

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppSettings
from app.database import Base, get_db
from app.intelligence.models import LogisticsExtraction, OCRResult
from app.main import app
from app.models import (
    Driver,
    DriverConfirmationStatus,
    Shipment,
    ShipmentStatus,
    User,
    UserRole,
)
from app.services.pod import extract_pod_fields, process_pod
from app.services.meta import MetaMediaService
from app.services.processing import ShipmentTaskRunner, get_shipment_task_runner
from app.services.webhook import extract_pod_messages


def _pod_payload(*, message_id="wamid.pod-1", media_id="pod-media-1") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "contacts": [{"wa_id": "919317708038"}],
                            "messages": [
                                {
                                    "from": "919317708038",
                                    "id": message_id,
                                    "type": "image",
                                    "image": {
                                        "id": media_id,
                                        "mime_type": "image/jpeg",
                                    },
                                }
                            ],
                        },
                    }
                ]
            }
        ],
    }


@pytest.fixture
def pod_flow(tmp_path: Path) -> Generator[tuple[TestClient, sessionmaker, Path], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pod-flow.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with session_factory() as session:
        driver = Driver(
            name="Rajesh Kumar",
            phone="919317708038",
            truck_number="RJ14GB1122",
        )
        user = User(whatsapp_number="919054256282", role=UserRole.OWNER)
        shipment = Shipment(
            user=user,
            driver=driver,
            status=ShipmentStatus.IN_TRANSIT,
            raw_event={"source": "seller voice"},
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

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), session_factory, tmp_path
    app.dependency_overrides.clear()
    engine.dispose()


def _install_pod_processor(
    session_factory: sessionmaker,
    tmp_path: Path,
    *,
    text: str,
    extraction: LogisticsExtraction,
    calls: list[int] | None = None,
    messages: list[tuple[str, str]] | None = None,
) -> None:
    def downloader(media_id: str, shipment_id: int, mime_type: str | None) -> Path:
        path = tmp_path / f"shipment-{shipment_id}-pod.jpg"
        path.write_bytes(b"\xff\xd8\xff mock pod")
        return path

    async def reader(file_path: str) -> OCRResult:
        if calls is not None:
            calls[0] += 1
        return OCRResult(text=text, provider="sarvam_vision", success=True)

    async def extractor(_: str) -> LogisticsExtraction:
        return extraction

    def message_sender(to: str, body: str) -> None:
        if messages is not None:
            messages.append((to, body))

    async def pod_processor(shipment_id: int) -> None:
        await process_pod(
            shipment_id,
            settings=AppSettings(),
            session_factory=session_factory,
            media_downloader=downloader,
            document_reader=reader,
            extractor=extractor,
            message_sender=message_sender,
        )

    runner = ShipmentTaskRunner(
        settings=AppSettings(),
        session_factory=session_factory,
        pod_processor=pod_processor,
    )
    app.dependency_overrides[get_shipment_task_runner] = lambda: runner


def _latest_shipment(session_factory: sessionmaker) -> Shipment:
    with session_factory() as session:
        shipment = session.scalar(select(Shipment).order_by(Shipment.id.desc()))
        assert shipment is not None
        session.expunge(shipment)
        return shipment


async def test_local_pod_field_extraction_handles_paddle_table_lines():
    text = """PROOF OF DELIVERY (POD)
Destination
Delhi, Chandni Chowk
Vehicle No.
RJ14GB1122
Driver
Rajesh Kumar
PAYMENT DETAILS
Advanced
₹10,000
Balance
₹25,000
DELIVERY CONFIRMATION
Delivered in good condition."""

    result = await extract_pod_fields(text)

    assert result == LogisticsExtraction(
        party_name=None,
        truck_number="RJ14GB1122",
        destination="Delhi, Chandni Chowk",
        advance_paid=10000,
        balance_due=25000,
    )


def test_valid_pod_marks_shipment_delivered(pod_flow):
    client, session_factory, tmp_path = pod_flow
    messages: list[tuple[str, str]] = []
    _install_pod_processor(
        session_factory,
        tmp_path,
        text="POD Ramesh Traders Truck RJ14GB1122 Destination Delhi Delivered",
        extraction=LogisticsExtraction(
            party_name="Ramesh Traders",
            truck_number="RJ14GB1122",
            destination="Delhi",
        ),
        messages=messages,
    )

    payload = _pod_payload()
    parsed = extract_pod_messages(payload)
    response = client.post("/meta-webhook", json=payload)

    assert parsed[0].sender_number == "919317708038"
    assert parsed[0].media_id == "pod-media-1"
    assert response.status_code == 200
    shipment = _latest_shipment(session_factory)
    assert shipment.status is ShipmentStatus.DELIVERED
    assert shipment.pod_message_id == "wamid.pod-1"
    assert shipment.pod_media_id == "pod-media-1"
    assert shipment.pod_media_path is not None
    assert Path(shipment.pod_media_path).is_file()
    assert shipment.pod_text is not None
    assert shipment.pod_error is None
    assert [recipient for recipient, _ in messages] == [
        "919317708038",
        "919054256282",
    ]
    assert "POD verify ho gaya Rajesh Kumar ji" in messages[0][1]
    assert "Delivery successfully complete ho gayi hai" in messages[1][1]
    assert "Shipment: SHP-1" in messages[1][1]
    assert "Party: Ramesh Traders" in messages[1][1]
    assert "Driver: Rajesh Kumar" in messages[1][1]
    assert "Truck: RJ14GB1122" in messages[1][1]
    assert "Destination: Delhi" in messages[1][1]


def test_wrong_truck_number_marks_pod_needs_review(pod_flow):
    client, session_factory, tmp_path = pod_flow
    messages: list[tuple[str, str]] = []
    _install_pod_processor(
        session_factory,
        tmp_path,
        text="POD Ramesh Traders Truck MH12AB1234 Destination Delhi Delivered",
        extraction=LogisticsExtraction(
            party_name="Ramesh Traders",
            truck_number="MH12AB1234",
            destination="Delhi",
        ),
        messages=messages,
    )

    response = client.post("/meta-webhook", json=_pod_payload())

    assert response.status_code == 200
    shipment = _latest_shipment(session_factory)
    assert shipment.status is ShipmentStatus.PARSED
    assert "truck number" in (shipment.pod_error or "")
    assert "MH12AB1234" in (shipment.pod_error or "")
    assert len(messages) == 1
    assert messages[0][0] == "919317708038"
    assert "Truck number match nahi kar raha hai" in messages[0][1]


def test_conflicting_destination_marks_pod_needs_review(pod_flow):
    client, session_factory, tmp_path = pod_flow
    _install_pod_processor(
        session_factory,
        tmp_path,
        text="POD Ramesh Traders Truck RJ14GB1122 Destination Mumbai Delivered",
        extraction=LogisticsExtraction(
            party_name="Ramesh Traders",
            truck_number="RJ14GB1122",
            destination="Mumbai",
        ),
    )

    client.post("/meta-webhook", json=_pod_payload())

    shipment = _latest_shipment(session_factory)
    assert shipment.status is ShipmentStatus.PARSED
    assert "destination" in (shipment.pod_error or "")
    assert "Mumbai" in (shipment.pod_error or "")


def test_corrected_pod_after_review_marks_same_shipment_delivered(pod_flow):
    client, session_factory, tmp_path = pod_flow
    messages: list[tuple[str, str]] = []
    calls = [0]
    _install_pod_processor(
        session_factory,
        tmp_path,
        text="POD Ramesh Traders Truck MH12AB1234 Destination Delhi Delivered",
        extraction=LogisticsExtraction(
            party_name="Ramesh Traders",
            truck_number="MH12AB1234",
            destination="Delhi",
        ),
        calls=calls,
        messages=messages,
    )

    first = client.post("/meta-webhook", json=_pod_payload())
    assert first.status_code == 200
    reviewed = _latest_shipment(session_factory)
    assert reviewed.status is ShipmentStatus.PARSED
    assert reviewed.pod_message_id == "wamid.pod-1"

    _install_pod_processor(
        session_factory,
        tmp_path,
        text="POD Ramesh Traders Truck RJ14GB1122 Destination Delhi Delivered",
        extraction=LogisticsExtraction(
            party_name="Ramesh Traders",
            truck_number="RJ14GB1122",
            destination="Delhi",
        ),
        calls=calls,
        messages=messages,
    )
    corrected_payload = _pod_payload(
        message_id="wamid.pod-2",
        media_id="pod-media-2",
    )
    corrected = client.post("/meta-webhook", json=corrected_payload)
    duplicate = client.post("/meta-webhook", json=corrected_payload)

    assert corrected.status_code == 200
    assert duplicate.status_code == 200
    delivered = _latest_shipment(session_factory)
    assert delivered.id == reviewed.id
    assert delivered.status is ShipmentStatus.DELIVERED
    assert delivered.pod_message_id == "wamid.pod-2"
    assert delivered.pod_media_id == "pod-media-2"
    assert delivered.pod_error is None
    assert calls == [2]
    assert [recipient for recipient, _ in messages] == [
        "919317708038",
        "919317708038",
        "919054256282",
    ]
    assert "DELIVERED mark" in messages[1][1]
    assert "Shipment: SHP-1" in messages[2][1]


def test_duplicate_pod_message_is_processed_once(pod_flow):
    client, session_factory, tmp_path = pod_flow
    calls = [0]
    _install_pod_processor(
        session_factory,
        tmp_path,
        text="POD Truck RJ14GB1122 Delivered",
        extraction=LogisticsExtraction(truck_number="RJ14GB1122"),
        calls=calls,
    )
    payload = _pod_payload()

    first = client.post("/meta-webhook", json=payload)
    duplicate = client.post("/meta-webhook", json=payload)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert calls == [1]
    shipment = _latest_shipment(session_factory)
    assert shipment.status is ShipmentStatus.DELIVERED
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Shipment)) == 1


def test_missing_optional_pod_fields_do_not_prevent_delivery(pod_flow):
    client, session_factory, tmp_path = pod_flow
    _install_pod_processor(
        session_factory,
        tmp_path,
        text="Proof of delivery Truck RJ14GB1122",
        extraction=LogisticsExtraction(truck_number="RJ14GB1122"),
    )

    client.post("/meta-webhook", json=_pod_payload())

    assert _latest_shipment(session_factory).status is ShipmentStatus.DELIVERED


def test_english_pod_with_minor_ocr_typo_matches_hindi_delhi_destination(pod_flow):
    client, session_factory, tmp_path = pod_flow
    with session_factory() as session:
        shipment = session.scalar(select(Shipment))
        assert shipment is not None
        assert shipment.extracted_data is not None
        shipment.extracted_data = {
            **shipment.extracted_data,
            "destination": "दिल्ली",
        }
        session.commit()

    _install_pod_processor(
        session_factory,
        tmp_path,
        text=(
            "PROOF OF DELIVERY Vehicle No. RJ14GB1122 "
            "Destination Deihi, Chandni Chowk Delivered"
        ),
        extraction=LogisticsExtraction(
            truck_number="RJ14GB1122",
            destination="Deihi, Chandni Chowk",
        ),
    )

    response = client.post("/meta-webhook", json=_pod_payload())

    assert response.status_code == 200
    shipment = _latest_shipment(session_factory)
    assert shipment.status is ShipmentStatus.DELIVERED
    assert shipment.pod_error is None


def test_meta_service_downloads_pod_under_safe_generated_name(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.pod.test":
            return httpx.Response(200, json={"url": "https://media.pod.test/file"})
        return httpx.Response(
            200,
            content=b"\xff\xd8\xff valid jpeg",
            headers={"content-type": "image/jpeg"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = MetaMediaService(
            access_token="test-token",
            graph_api_base_url="https://graph.pod.test",
            graph_api_version="v25.0",
            output_dir=tmp_path,
            max_media_bytes=1024,
            http_client=client,
            phone_number_id="phone-id",
        )
        path = service.download_document("pod-media", 42, "image/jpeg")

    assert path.parent == tmp_path
    assert path.name.startswith("shipment-42-pod-")
    assert path.suffix == ".jpg"
    assert path.read_bytes() == b"\xff\xd8\xff valid jpeg"
