from collections.abc import Generator
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import BackgroundTasks, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppSettings, get_settings
from app.database import Base, get_db
from app.intelligence.models import LogisticsExtraction, STTResult
from app.intelligence.service import process_audio
from app.main import app
from app.models import Driver, DriverConfirmationStatus, Shipment, ShipmentStatus, User, UserRole
from app.routes.webhook import receive_meta_webhook
from app.services.drivers import assign_driver_for_shipment
from app.services.messaging import MetaMessagingService
from app.services.meta import MetaMediaService
from app.services.processing import ShipmentTaskRunner, get_shipment_task_runner
from app.services.webhook import extract_audio_messages, extract_message_statuses


@pytest.fixture
def webhook_client(
    tmp_path: Path,
) -> Generator[tuple[TestClient, sessionmaker, list[httpx.Request]], None, None]:
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'webhook-test.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session_factory = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(test_engine)
    meta_requests: list[httpx.Request] = []

    def meta_handler(request: httpx.Request) -> httpx.Response:
        meta_requests.append(request)
        assert request.headers["authorization"] == "Bearer test-access-token"

        if request.url.host == "graph.test":
            assert request.url.params["phone_number_id"] == "test-phone-number-id"
            media_id = request.url.path.rsplit("/", maxsplit=1)[-1]
            assert request.url.path == f"/v25.0/{media_id}"
            if media_id == "media-fail":
                return httpx.Response(
                    503,
                    json={
                        "error": {
                            "message": (
                                "Temporary failure for test-access-token. "
                                "See https://example.test/error?token=secret"
                            ),
                            "type": "GraphMethodException",
                            "code": 100,
                            "error_subcode": 33,
                        }
                    },
                )
            if media_id == "network-error":
                raise httpx.ConnectError("mock connection failed", request=request)
            if media_id == "invalid-json":
                return httpx.Response(200, content=b"not-json")
            if media_id == "missing-url":
                return httpx.Response(200, json={"id": media_id})
            return httpx.Response(
                200,
                json={"url": f"https://media.test/download/{media_id}"},
            )

        if request.url.host == "media.test":
            media_id = request.url.path.rsplit("/", maxsplit=1)[-1]
            if media_id == "download-fail":
                return httpx.Response(502)
            if media_id == "empty-file":
                return httpx.Response(
                    200,
                    content=b"",
                    headers={"content-type": "audio/ogg"},
                )
            if media_id == "wrong-type":
                return httpx.Response(
                    200,
                    content=b"not audio",
                    headers={"content-type": "text/plain"},
                )
            if media_id == "invalid-ogg":
                return httpx.Response(
                    200,
                    content=b"this-is-not-an-ogg-file",
                    headers={"content-type": "audio/ogg"},
                )
            if media_id == "too-large":
                return httpx.Response(
                    200,
                    content=b"OggS" + (b"x" * 100),
                    headers={"content-type": "audio/ogg"},
                )
            return httpx.Response(
                200,
                content=b"OggS\x00mock-opus-audio",
                headers={"content-type": "audio/ogg"},
            )

        return httpx.Response(404)

    meta_http_client = httpx.Client(
        transport=httpx.MockTransport(meta_handler),
        follow_redirects=True,
    )
    media_service = MetaMediaService(
        access_token="test-access-token",
        graph_api_base_url="https://graph.test",
        graph_api_version="v25.0",
        output_dir=tmp_path / "media",
        max_media_bytes=64,
        http_client=meta_http_client,
        phone_number_id="test-phone-number-id",
    )

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    test_settings = AppSettings(
        meta_webhook_verify_token="demo-verify-token",
        intelligence_enabled=False,
    )

    async def ignore_confirmation_notifications(_: int) -> None:
        return None

    app.dependency_overrides[get_shipment_task_runner] = lambda: ShipmentTaskRunner(
        settings=test_settings,
        session_factory=testing_session_factory,
        media_downloader=media_service.download_audio,
        confirmation_notifier=ignore_confirmation_notifications,
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    with TestClient(app) as client:
        yield client, testing_session_factory, meta_requests
    app.dependency_overrides.clear()
    meta_http_client.close()
    test_engine.dispose()


def _audio_payload(
    sender: str = "919876543210",
    message_id: str = "wamid.example",
    media_id: str = "media-123",
) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "business-account-id",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [{"wa_id": sender, "profile": {"name": "Driver"}}],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": message_id,
                                    "timestamp": "1720000000",
                                    "type": "audio",
                                    "audio": {
                                        "id": media_id,
                                        "mime_type": "audio/ogg; codecs=opus",
                                        "voice": True,
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _text_payload(
    sender: str,
    body: str,
    message_id: str = "wamid.reply",
) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "business-account-id",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [{"wa_id": sender, "profile": {"name": "Driver"}}],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": message_id,
                                    "timestamp": "1720000000",
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def test_valid_audio_webhook_is_parsed_and_persisted(
    webhook_client: tuple, caplog: pytest.LogCaptureFixture
) -> None:
    client, session_factory, meta_requests = webhook_client
    payload = _audio_payload()
    caplog.set_level("INFO", logger="app")

    parsed = extract_audio_messages(payload)
    response = client.post("/meta-webhook", json=payload)

    assert parsed[0].sender_number == "919876543210"
    assert parsed[0].message_id == "wamid.example"
    assert parsed[0].media_id == "media-123"
    assert parsed[0].message_type == "audio"
    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "shipments_created": 1,
        "duplicates": 0,
        "processing_queued": 1,
        "media_downloaded": 0,
        "failed": 0,
        "driver_confirmed": 0,
        "driver_rejected": 0,
    }
    assert len(meta_requests) == 2
    assert "webhook_received" in caplog.text
    assert "shipment_created" in caplog.text
    assert "media_download_started" in caplog.text
    assert "media_download_completed" in caplog.text
    assert "test-access-token" not in caplog.text

    with session_factory() as session:
        user = session.scalar(select(User))
        shipment = session.scalar(select(Shipment))

        assert user is not None
        assert user.whatsapp_number == "919876543210"
        assert user.role is UserRole.TRANSPORTER
        assert shipment is not None
        assert shipment.user_id == user.id
        assert shipment.status is ShipmentStatus.RECEIVED
        assert shipment.media_id == "media-123"
        assert shipment.message_id == "wamid.example"
        assert shipment.message_type == "audio"
        assert shipment.media_path is not None
        assert Path(shipment.media_path).suffix == ".ogg"
        assert Path(shipment.media_path).read_bytes() == b"OggS\x00mock-opus-audio"
        assert shipment.media_error is None
        assert shipment.raw_event == payload


def test_missing_optional_message_fields_are_safe(webhook_client: tuple) -> None:
    client, session_factory, meta_requests = webhook_client
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": "441234567890"}],
                            "messages": [{"audio": {}}],
                        }
                    }
                ]
            }
        ]
    }

    parsed = extract_audio_messages(payload)
    response = client.post("/meta-webhook", json=payload)

    assert parsed[0].sender_number == "441234567890"
    assert parsed[0].message_id is None
    assert parsed[0].media_id is None
    assert parsed[0].message_type == "audio"
    assert response.json() == {
        "status": "accepted",
        "shipments_created": 1,
        "duplicates": 0,
        "processing_queued": 0,
        "media_downloaded": 0,
        "failed": 1,
        "driver_confirmed": 0,
        "driver_rejected": 0,
    }
    assert meta_requests == []

    with session_factory() as session:
        shipment = session.scalar(select(Shipment))
        assert shipment is not None
        assert shipment.media_id is None
        assert shipment.media_path is None
        assert shipment.status is ShipmentStatus.FAILED
        assert shipment.media_error == "Audio message did not include a media ID."


def test_irrelevant_and_malformed_payloads_are_ignored(webhook_client: tuple) -> None:
    client, session_factory, meta_requests = webhook_client
    status_payload = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"statuses": [{"status": "read"}]}}]}],
    }

    responses = [
        client.post("/meta-webhook", json={}),
        client.post("/meta-webhook", json=status_payload),
        client.post(
            "/meta-webhook",
            content="not-json",
            headers={"content-type": "application/json"},
        ),
    ]

    assert all(response.status_code == 200 for response in responses)
    assert all(
        response.json()
        == {
            "status": "ignored",
            "shipments_created": 0,
            "duplicates": 0,
            "processing_queued": 0,
            "media_downloaded": 0,
            "failed": 0,
            "driver_confirmed": 0,
            "driver_rejected": 0,
        }
        for response in responses
    )
    assert meta_requests == []
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0
        assert session.scalar(select(func.count()).select_from(Shipment)) == 0


def test_outbound_failed_status_is_parsed_logged_and_acknowledged(
    webhook_client: tuple, caplog: pytest.LogCaptureFixture
) -> None:
    client, session_factory, meta_requests = webhook_client
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "statuses": [
                                {
                                    "id": "wamid.outbound",
                                    "status": "failed",
                                    "recipient_id": "919317708038",
                                    "errors": [
                                        {
                                            "code": 131047,
                                            "title": "Re-engagement message",
                                            "message": "Re-engagement message",
                                            "error_data": {
                                                "details": (
                                                    "More than 24 hours have passed; "
                                                    "use a template. See https://example.test"
                                                )
                                            },
                                        }
                                    ],
                                }
                            ]
                        },
                    }
                ]
            }
        ],
    }
    caplog.set_level("INFO", logger="app")

    parsed = extract_message_statuses(payload)
    response = client.post("/meta-webhook", json=payload)

    assert parsed[0].message_id == "wamid.outbound"
    assert parsed[0].status == "failed"
    assert parsed[0].errors[0].code == 131047
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert "meta_outbound_delivery_failed" in caplog.text
    assert "code=131047" in caplog.text
    assert "use a template" in caplog.text
    assert "https://example.test" not in caplog.text
    assert meta_requests == []
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Shipment)) == 0


def test_existing_user_is_reused(webhook_client: tuple) -> None:
    client, session_factory, meta_requests = webhook_client

    first_response = client.post("/meta-webhook", json=_audio_payload())
    second_response = client.post(
        "/meta-webhook",
        json=_audio_payload(message_id="wamid.second", media_id="media-456"),
    )
    duplicate_response = client.post("/meta-webhook", json=_audio_payload())

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert duplicate_response.json() == {
        "status": "accepted",
        "shipments_created": 0,
        "duplicates": 1,
        "processing_queued": 0,
        "media_downloaded": 0,
        "failed": 0,
        "driver_confirmed": 0,
        "driver_rejected": 0,
    }
    assert len(meta_requests) == 4
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(Shipment)) == 2


def test_media_download_failure_marks_shipment_failed(
    webhook_client: tuple, caplog: pytest.LogCaptureFixture
) -> None:
    client, session_factory, meta_requests = webhook_client
    payload = _audio_payload(message_id="wamid.failure", media_id="media-fail")
    caplog.set_level("WARNING", logger="app")

    response = client.post("/meta-webhook", json=payload)

    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "shipments_created": 1,
        "duplicates": 0,
        "processing_queued": 1,
        "media_downloaded": 0,
        "failed": 0,
        "driver_confirmed": 0,
        "driver_rejected": 0,
    }
    assert len(meta_requests) == 1
    with session_factory() as session:
        shipment = session.scalar(select(Shipment))
        assert shipment is not None
        assert shipment.status is ShipmentStatus.FAILED
        assert shipment.media_path is None
        assert shipment.media_error == (
            "Meta media lookup failed with HTTP 503 (code=100, subcode=33): "
            "Temporary failure for <redacted>. See <url>"
        )
        assert shipment.raw_event == payload
    assert "Temporary failure for <redacted>. See <url>" in caplog.text
    assert "test-access-token" not in caplog.text
    assert "token=secret" not in caplog.text


def test_webhook_background_flow_updates_same_shipment(
    webhook_client: tuple,
    tmp_path: Path,
) -> None:
    client, session_factory, _ = webhook_client
    calls = {"stt": 0, "extract": 0}
    meta_calls: list[httpx.Request] = []

    def meta_handler(request: httpx.Request) -> httpx.Response:
        meta_calls.append(request)
        assert request.headers["authorization"] == "Bearer integration-token"
        if request.url.host == "graph.integration.test":
            assert request.url.path == "/v25.0/media-full-integration"
            return httpx.Response(
                200,
                json={
                    "url": (
                        "https://media.integration.test/"
                        "download/media-full-integration"
                    )
                },
            )
        return httpx.Response(
            200,
            content=b"OggS integrated voice note",
            headers={"content-type": "audio/ogg"},
        )

    meta_client = httpx.Client(transport=httpx.MockTransport(meta_handler))
    media_service = MetaMediaService(
        access_token="integration-token",
        graph_api_base_url="https://graph.integration.test",
        graph_api_version="v25.0",
        output_dir=tmp_path / "integrated-media",
        max_media_bytes=1024,
        http_client=meta_client,
        phone_number_id="integration-phone-id",
    )

    async def fake_stt(file_path: str) -> STTResult:
        calls["stt"] += 1
        assert Path(file_path).is_file()
        return STTResult(
            transcript="Ramesh truck RJ14GB1122 advance das hazaar",
            provider="fake",
            model="fake",
        )

    async def fake_extractor(_: str) -> LogisticsExtraction:
        calls["extract"] += 1
        return LogisticsExtraction(
            party_name="Ramesh",
            truck_number="RJ14GB1122",
            advance_paid=10000,
        )

    async def intelligence_processor(shipment_id: int):
        return await process_audio(
            shipment_id,
            session_factory=session_factory,
            stt=fake_stt,
            extractor=fake_extractor,
        )

    runner = ShipmentTaskRunner(
        settings=AppSettings(intelligence_enabled=True),
        session_factory=session_factory,
        media_downloader=media_service.download_audio,
        intelligence_processor=intelligence_processor,
    )
    app.dependency_overrides[get_shipment_task_runner] = lambda: runner
    payload = _audio_payload(
        message_id="wamid.full-integration",
        media_id="media-full-integration",
    )

    response = client.post("/meta-webhook", json=payload)
    duplicate = client.post("/meta-webhook", json=payload)

    assert response.status_code == 200
    assert response.json()["processing_queued"] == 1
    assert duplicate.json()["duplicates"] == 1
    assert calls == {"stt": 1, "extract": 1}
    assert len(meta_calls) == 2
    with session_factory() as session:
        shipment = session.scalar(select(Shipment))
        assert shipment is not None
        assert shipment.status is ShipmentStatus.COMPLETED
        assert shipment.media_path is not None
        assert Path(shipment.media_path).read_bytes() == b"OggS integrated voice note"
        assert shipment.transcript == "Ramesh truck RJ14GB1122 advance das hazaar"
        assert shipment.extracted_data == {
            "party_name": "Ramesh",
            "truck_number": "RJ14GB1122",
            "destination": None,
            "advance_paid": 10000,
            "balance_due": None,
        }
        assert shipment.raw_event == payload
        assert session.scalar(select(func.count()).select_from(Shipment)) == 1
    meta_client.close()


async def test_webhook_route_returns_before_background_work_starts(
    webhook_client: tuple,
) -> None:
    _, session_factory, _ = webhook_client
    payload = _audio_payload(
        message_id="wamid.ack-first",
        media_id="media-ack-first",
    )
    body = json.dumps(payload).encode()
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {"type": "http", "method": "POST", "path": "/meta-webhook", "headers": []},
        receive,
    )
    background_tasks = BackgroundTasks()
    processed: list[int] = []

    async def runner(shipment_id: int) -> None:
        processed.append(shipment_id)

    with session_factory() as session:
        response = await receive_meta_webhook(
            request,
            background_tasks,
            session,
            runner,  # type: ignore[arg-type]
        )

    assert response.status == "accepted"
    assert response.processing_queued == 1
    assert processed == []

    await background_tasks()

    assert len(processed) == 1


@pytest.mark.parametrize(
    ("media_id", "expected_error", "expected_requests"),
    [
        ("invalid-json", "Meta media lookup returned invalid JSON.", 1),
        ("missing-url", "Meta media lookup response did not include a URL.", 1),
        ("network-error", "Meta media lookup request failed.", 1),
        ("download-fail", "Meta media download failed with HTTP 502.", 2),
        ("empty-file", "Meta media download returned an empty file.", 2),
        ("wrong-type", "Meta media download was not audio/ogg.", 2),
        ("invalid-ogg", "Meta media download was not a valid Ogg file.", 2),
        (
            "too-large",
            "Meta media download exceeded the configured size limit.",
            2,
        ),
    ],
)
def test_media_failure_cases_are_recorded_safely(
    webhook_client: tuple,
    media_id: str,
    expected_error: str,
    expected_requests: int,
) -> None:
    client, session_factory, meta_requests = webhook_client

    response = client.post(
        "/meta-webhook",
        json=_audio_payload(message_id=f"wamid.{media_id}", media_id=media_id),
    )

    assert response.status_code == 200
    assert response.json()["processing_queued"] == 1
    assert response.json()["failed"] == 0
    assert len(meta_requests) == expected_requests
    with session_factory() as session:
        shipment = session.scalar(select(Shipment))
        assert shipment is not None
        assert shipment.status is ShipmentStatus.FAILED
        assert shipment.media_path is None
        assert shipment.media_error == expected_error


def test_meta_webhook_verification_succeeds(webhook_client: tuple) -> None:
    client, _, _ = webhook_client

    response = client.get(
        "/meta-webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "demo-verify-token",
            "hub.challenge": "challenge-value-123",
        },
    )

    assert response.status_code == 200
    assert response.text == "challenge-value-123"
    assert response.headers["content-type"].startswith("text/plain")


def test_meta_webhook_verification_rejects_wrong_token(webhook_client: tuple) -> None:
    client, _, _ = webhook_client

    response = client.get(
        "/meta-webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge-value-123",
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Webhook verification failed."}


def test_meta_webhook_verification_requires_configuration(
    webhook_client: tuple,
) -> None:
    client, _, _ = webhook_client
    app.dependency_overrides[get_settings] = lambda: AppSettings(
        meta_webhook_verify_token=None
    )

    response = client.get(
        "/meta-webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "anything",
            "hub.challenge": "challenge-value-123",
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Webhook verification is not configured."}


# ---------------------------------------------------------------------------
# Driver assignment and outbound WhatsApp confirmation
# ---------------------------------------------------------------------------


def _make_driver_notifier(session_factory, meta_send_calls: list[httpx.Request]):
    """Real DB assignment + a real MetaMessagingService, transport mocked."""

    def meta_send_handler(request: httpx.Request) -> httpx.Response:
        meta_send_calls.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.sent"}]})

    async def driver_notifier(shipment_id: int) -> None:
        with session_factory() as session:
            assignment = assign_driver_for_shipment(session, shipment_id)
        if assignment is None:
            return
        transport = httpx.MockTransport(meta_send_handler)
        with httpx.Client(transport=transport) as client:
            service = MetaMessagingService(
                access_token="driver-message-token",
                graph_api_base_url="https://graph.driver-flow.test",
                graph_api_version="v25.0",
                phone_number_id="driver-phone-number-id",
                http_client=client,
            )
            service.send_text_message(to=assignment.driver.phone, body=assignment.message)

    return driver_notifier


def test_full_flow_seller_voice_to_driver_assignment_and_whatsapp_message(
    webhook_client: tuple, tmp_path: Path
) -> None:
    client, session_factory, _ = webhook_client

    with session_factory() as session:
        driver = Driver(name="Rajesh Kumar", phone="15550009999", truck_number="RJ14GB1122")
        session.add(driver)
        session.commit()
        driver_id = driver.id

    def meta_media_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.driver-flow.test":
            return httpx.Response(
                200, json={"url": "https://media.driver-flow.test/download/voice-note"}
            )
        return httpx.Response(
            200,
            content=b"OggS driver-assignment voice note",
            headers={"content-type": "audio/ogg"},
        )

    meta_client = httpx.Client(transport=httpx.MockTransport(meta_media_handler))
    media_service = MetaMediaService(
        access_token="media-token",
        graph_api_base_url="https://graph.driver-flow.test",
        graph_api_version="v25.0",
        output_dir=tmp_path / "driver-flow-media",
        max_media_bytes=1024,
        http_client=meta_client,
        phone_number_id="media-phone-id",
    )

    async def fake_stt(file_path: str) -> STTResult:
        return STTResult(
            transcript=(
                "Ramesh Traders truck RJ14GB1122 Delhi advance das hazaar and "
                "balance pachees hazaar"
            ),
            provider="fake",
            model="fake",
        )

    async def fake_extractor(_: str) -> LogisticsExtraction:
        return LogisticsExtraction(
            party_name="Ramesh Traders",
            truck_number="RJ14GB1122",
            destination="Delhi",
            advance_paid=10000,
            balance_due=25000,
        )

    async def intelligence_processor(shipment_id: int):
        return await process_audio(
            shipment_id,
            session_factory=session_factory,
            stt=fake_stt,
            extractor=fake_extractor,
        )

    meta_send_calls: list[httpx.Request] = []
    runner = ShipmentTaskRunner(
        settings=AppSettings(intelligence_enabled=True),
        session_factory=session_factory,
        media_downloader=media_service.download_audio,
        intelligence_processor=intelligence_processor,
        driver_notifier=_make_driver_notifier(session_factory, meta_send_calls),
    )
    app.dependency_overrides[get_shipment_task_runner] = lambda: runner

    payload = _audio_payload(
        sender="919876500000",
        message_id="wamid.driver-flow",
        media_id="media-driver-flow",
    )
    response = client.post("/meta-webhook", json=payload)

    assert response.status_code == 200
    with session_factory() as session:
        shipment = session.scalar(
            select(Shipment).where(Shipment.message_id == "wamid.driver-flow")
        )
        assert shipment is not None
        assert shipment.status is ShipmentStatus.COMPLETED
        assert shipment.driver_id == driver_id
        assert shipment.driver_confirmation_status is DriverConfirmationStatus.PENDING
        assert shipment.driver_message_sent_at is not None

    assert len(meta_send_calls) == 1
    sent_body = json.loads(meta_send_calls[0].read())
    assert sent_body["to"] == "15550009999"
    assert sent_body["type"] == "text"
    assert sent_body["text"]["body"] == (
        "Namaste Rajesh Kumar ji 👋\n\n"
        "Aapko ek nayi delivery assign hui hai:\n\n"
        "Party: Ramesh Traders\n"
        "Truck: RJ14GB1122\n"
        "Destination: Delhi\n"
        "Advance: ₹10,000\n"
        "Remaining: ₹25,000\n\n"
        "Delivery confirm karne ke liye YES reply karein.\n"
        "Agar koi dikkat hai to bata dijiye."
    )


def test_truck_not_found_is_graceful_no_driver_assigned_no_message_sent(
    webhook_client: tuple, tmp_path: Path
) -> None:
    client, session_factory, _ = webhook_client
    # Deliberately no driver seeded for MH12AB1234.

    def meta_media_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.no-driver.test":
            return httpx.Response(
                200, json={"url": "https://media.no-driver.test/download/voice-note"}
            )
        return httpx.Response(
            200,
            content=b"OggS unmatched truck voice note",
            headers={"content-type": "audio/ogg"},
        )

    meta_client = httpx.Client(transport=httpx.MockTransport(meta_media_handler))
    media_service = MetaMediaService(
        access_token="media-token",
        graph_api_base_url="https://graph.no-driver.test",
        graph_api_version="v25.0",
        output_dir=tmp_path / "no-driver-media",
        max_media_bytes=1024,
        http_client=meta_client,
        phone_number_id="media-phone-id",
    )

    async def fake_stt(file_path: str) -> STTResult:
        return STTResult(
            transcript=(
                "Ramesh Traders truck MH12AB1234 Delhi advance das hazaar and "
                "balance pachees hazaar"
            ),
            provider="fake",
            model="fake",
        )

    async def fake_extractor(_: str) -> LogisticsExtraction:
        return LogisticsExtraction(
            party_name="Ramesh Traders",
            truck_number="MH12AB1234",
            destination="Delhi",
            advance_paid=10000,
            balance_due=25000,
        )

    async def intelligence_processor(shipment_id: int):
        return await process_audio(
            shipment_id,
            session_factory=session_factory,
            stt=fake_stt,
            extractor=fake_extractor,
        )

    notifier_calls = {"count": 0}

    async def spy_driver_notifier(shipment_id: int) -> None:
        notifier_calls["count"] += 1
        with session_factory() as session:
            assignment = assign_driver_for_shipment(session, shipment_id)
        assert assignment is None

    runner = ShipmentTaskRunner(
        settings=AppSettings(intelligence_enabled=True),
        session_factory=session_factory,
        media_downloader=media_service.download_audio,
        intelligence_processor=intelligence_processor,
        driver_notifier=spy_driver_notifier,
    )
    app.dependency_overrides[get_shipment_task_runner] = lambda: runner

    payload = _audio_payload(
        sender="919876500001",
        message_id="wamid.no-driver",
        media_id="media-no-driver",
    )
    response = client.post("/meta-webhook", json=payload)

    assert response.status_code == 200
    assert notifier_calls["count"] == 1
    with session_factory() as session:
        shipment = session.scalar(
            select(Shipment).where(Shipment.message_id == "wamid.no-driver")
        )
        assert shipment is not None
        assert shipment.status is ShipmentStatus.COMPLETED
        assert shipment.driver_id is None
        assert shipment.driver_confirmation_status is None


def test_duplicate_audio_webhook_sends_driver_message_only_once(
    webhook_client: tuple, tmp_path: Path
) -> None:
    client, session_factory, _ = webhook_client
    with session_factory() as session:
        session.add(Driver(name="Rajesh Kumar", phone="15550009999", truck_number="RJ14GB1122"))
        session.commit()

    def meta_media_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.dup-driver.test":
            return httpx.Response(
                200, json={"url": "https://media.dup-driver.test/download/voice-note"}
            )
        return httpx.Response(
            200,
            content=b"OggS dup driver voice note",
            headers={"content-type": "audio/ogg"},
        )

    meta_client = httpx.Client(transport=httpx.MockTransport(meta_media_handler))
    media_service = MetaMediaService(
        access_token="media-token",
        graph_api_base_url="https://graph.dup-driver.test",
        graph_api_version="v25.0",
        output_dir=tmp_path / "dup-driver-media",
        max_media_bytes=1024,
        http_client=meta_client,
        phone_number_id="media-phone-id",
    )

    async def fake_stt(file_path: str) -> STTResult:
        return STTResult(
            transcript=(
                "Ramesh Traders truck RJ14GB1122 Delhi advance das hazaar and "
                "balance pachees hazaar"
            ),
            provider="fake",
            model="fake",
        )

    async def fake_extractor(_: str) -> LogisticsExtraction:
        return LogisticsExtraction(
            party_name="Ramesh Traders",
            truck_number="RJ14GB1122",
            destination="Delhi",
            advance_paid=10000,
            balance_due=25000,
        )

    async def intelligence_processor(shipment_id: int):
        return await process_audio(
            shipment_id,
            session_factory=session_factory,
            stt=fake_stt,
            extractor=fake_extractor,
        )

    meta_send_calls: list[httpx.Request] = []
    runner = ShipmentTaskRunner(
        settings=AppSettings(intelligence_enabled=True),
        session_factory=session_factory,
        media_downloader=media_service.download_audio,
        intelligence_processor=intelligence_processor,
        driver_notifier=_make_driver_notifier(session_factory, meta_send_calls),
    )
    app.dependency_overrides[get_shipment_task_runner] = lambda: runner

    payload = _audio_payload(
        sender="919876500002",
        message_id="wamid.dup-driver",
        media_id="media-dup-driver",
    )
    first_response = client.post("/meta-webhook", json=payload)
    duplicate_response = client.post("/meta-webhook", json=payload)

    assert first_response.json()["processing_queued"] == 1
    assert duplicate_response.json()["duplicates"] == 1
    assert len(meta_send_calls) == 1


# ---------------------------------------------------------------------------
# Driver YES/NO replies
# ---------------------------------------------------------------------------


def _seed_pending_driver_shipment(
    session_factory,
    *,
    driver_phone: str = "15550009999",
    truck: str = "RJ14GB1122",
    seller_number: str = "919876500003",
) -> tuple[int, int]:
    from datetime import datetime, timezone

    with session_factory() as session:
        driver = Driver(name="Rajesh Kumar", phone=driver_phone, truck_number=truck)
        user = User(whatsapp_number=seller_number, role=UserRole.TRANSPORTER)
        shipment = Shipment(
            user=user,
            driver=driver,
            status=ShipmentStatus.COMPLETED,
            raw_event={"object": "whatsapp_business_account"},
            extracted_data={
                "party_name": "Ramesh Traders",
                "truck_number": truck,
                "destination": "Delhi",
                "advance_paid": 10000,
                "balance_due": 25000,
            },
            driver_confirmation_status=DriverConfirmationStatus.PENDING,
            driver_message_sent_at=datetime.now(timezone.utc),
        )
        session.add(shipment)
        session.commit()
        return driver.id, shipment.id


def test_driver_reply_yes_confirms_shipment(webhook_client: tuple) -> None:
    client, session_factory, _ = webhook_client
    _driver_id, shipment_id = _seed_pending_driver_shipment(
        session_factory, driver_phone="15550011111", seller_number="919876500010"
    )

    response = client.post(
        "/meta-webhook",
        json=_text_payload(sender="15550011111", body="YES", message_id="wamid.yes-reply"),
    )

    assert response.status_code == 200
    assert response.json()["driver_confirmed"] == 1
    assert response.json()["driver_rejected"] == 0
    with session_factory() as session:
        shipment = session.get(Shipment, shipment_id)
        assert shipment.driver_confirmation_status is DriverConfirmationStatus.CONFIRMED
        assert shipment.status is ShipmentStatus.IN_TRANSIT
        assert shipment.driver_reply_message_id == "wamid.yes-reply"


def test_driver_reply_confirm_lowercase_confirms_shipment(webhook_client: tuple) -> None:
    client, session_factory, _ = webhook_client
    _driver_id, shipment_id = _seed_pending_driver_shipment(
        session_factory, driver_phone="15550011112", seller_number="919876500011"
    )

    response = client.post(
        "/meta-webhook",
        json=_text_payload(sender="15550011112", body="confirm", message_id="wamid.confirm-reply"),
    )

    assert response.json()["driver_confirmed"] == 1
    with session_factory() as session:
        shipment = session.get(Shipment, shipment_id)
        assert shipment.driver_confirmation_status is DriverConfirmationStatus.CONFIRMED
        assert shipment.status is ShipmentStatus.IN_TRANSIT


def test_driver_reply_no_rejects_shipment(webhook_client: tuple) -> None:
    client, session_factory, _ = webhook_client
    _driver_id, shipment_id = _seed_pending_driver_shipment(
        session_factory, driver_phone="15550011113", seller_number="919876500012"
    )

    response = client.post(
        "/meta-webhook",
        json=_text_payload(sender="15550011113", body="NO", message_id="wamid.no-reply"),
    )

    assert response.status_code == 200
    assert response.json()["driver_confirmed"] == 0
    assert response.json()["driver_rejected"] == 1
    with session_factory() as session:
        shipment = session.get(Shipment, shipment_id)
        assert shipment.driver_confirmation_status is DriverConfirmationStatus.REJECTED
        assert shipment.driver_reply_message_id == "wamid.no-reply"


def test_driver_reply_reject_word_rejects_shipment(webhook_client: tuple) -> None:
    client, session_factory, _ = webhook_client
    _seed_pending_driver_shipment(
        session_factory, driver_phone="15550011114", seller_number="919876500013"
    )

    response = client.post(
        "/meta-webhook",
        json=_text_payload(sender="15550011114", body="Reject", message_id="wamid.reject-reply"),
    )

    assert response.json()["driver_rejected"] == 1


def test_driver_reply_with_no_active_shipment_is_graceful(webhook_client: tuple) -> None:
    client, session_factory, _ = webhook_client
    with session_factory() as session:
        session.add(
            Driver(name="Idle Driver", phone="15550011115", truck_number="DL05CD5678")
        )
        session.commit()

    response = client.post(
        "/meta-webhook",
        json=_text_payload(sender="15550011115", body="YES", message_id="wamid.idle-reply"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "shipments_created": 0,
        "duplicates": 0,
        "processing_queued": 0,
        "media_downloaded": 0,
        "failed": 0,
        "driver_confirmed": 0,
        "driver_rejected": 0,
    }


def test_driver_reply_from_unknown_sender_is_graceful(webhook_client: tuple) -> None:
    client, _session_factory, _ = webhook_client

    response = client.post(
        "/meta-webhook",
        json=_text_payload(sender="15559999999", body="YES", message_id="wamid.unknown-reply"),
    )

    assert response.status_code == 200
    assert response.json()["driver_confirmed"] == 0
    assert response.json()["driver_rejected"] == 0


def test_driver_reply_unrecognized_text_does_not_change_status(webhook_client: tuple) -> None:
    client, session_factory, _ = webhook_client
    _driver_id, shipment_id = _seed_pending_driver_shipment(
        session_factory, driver_phone="15550011116", seller_number="919876500014"
    )

    response = client.post(
        "/meta-webhook",
        json=_text_payload(
            sender="15550011116", body="what time?", message_id="wamid.unrecognized-reply"
        ),
    )

    assert response.status_code == 200
    assert response.json()["driver_confirmed"] == 0
    assert response.json()["driver_rejected"] == 0
    with session_factory() as session:
        shipment = session.get(Shipment, shipment_id)
        assert shipment.driver_confirmation_status is DriverConfirmationStatus.PENDING


def test_duplicate_driver_reply_webhook_does_not_double_process(webhook_client: tuple) -> None:
    client, session_factory, _ = webhook_client
    _driver_id, shipment_id = _seed_pending_driver_shipment(
        session_factory, driver_phone="15550011117", seller_number="919876500015"
    )
    payload = _text_payload(sender="15550011117", body="YES", message_id="wamid.dup-yes-reply")

    first = client.post("/meta-webhook", json=payload)
    second = client.post("/meta-webhook", json=payload)

    assert first.json()["driver_confirmed"] == 1
    # The redelivered webhook finds no PENDING shipment left for this
    # driver (it already moved to CONFIRMED), so it is gracefully
    # ignored rather than re-processed or erroring.
    assert second.json()["driver_confirmed"] == 0
    assert second.json()["driver_rejected"] == 0
    with session_factory() as session:
        shipment = session.get(Shipment, shipment_id)
        assert shipment.driver_confirmation_status is DriverConfirmationStatus.CONFIRMED
