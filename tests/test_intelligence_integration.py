from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.intelligence.exceptions import SttProviderError
from app.intelligence.models import LogisticsExtraction, ProcessingStatus, STTResult
from app.intelligence.service import process_audio
from app.models import Shipment, ShipmentStatus, User, UserRole


@pytest.fixture
def shipment_store(
    tmp_path: Path,
) -> Generator[tuple[sessionmaker, int, Path], None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'intelligence.db'}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    media_path = tmp_path / "shipment.ogg"
    media_path.write_bytes(b"OggS fake audio")

    with factory() as session:
        user = User(whatsapp_number="919900000001", role=UserRole.TRANSPORTER)
        shipment = Shipment(
            user=user,
            status=ShipmentStatus.RECEIVED,
            media_id="media-1",
            message_id="wamid.integration",
            media_path=str(media_path),
            raw_event={"original": True},
        )
        session.add(shipment)
        session.commit()
        shipment_id = shipment.id

    yield factory, shipment_id, media_path
    engine.dispose()


async def test_process_audio_updates_the_same_shipment(shipment_store: tuple) -> None:
    factory, shipment_id, media_path = shipment_store

    async def fake_stt(file_path: str) -> STTResult:
        assert file_path == str(media_path)
        return STTResult(
            transcript="Ramesh truck RJ14GB1122 advance das hazaar",
            provider="fake",
            model="fake",
        )

    async def fake_extractor(_: str) -> LogisticsExtraction:
        return LogisticsExtraction(
            party_name="Ramesh",
            truck_number="RJ14GB1122",
            advance_paid=10000,
        )

    result = await process_audio(
        shipment_id,
        session_factory=factory,
        stt=fake_stt,
        extractor=fake_extractor,
    )

    assert result.status is ProcessingStatus.ACCEPTED
    with factory() as session:
        shipment = session.get(Shipment, shipment_id)
        assert shipment is not None
        assert shipment.status is ShipmentStatus.COMPLETED
        assert shipment.media_path == str(media_path)
        assert shipment.raw_event == {"original": True}
        assert shipment.transcript == result.transcript
        assert shipment.extracted_data == result.extraction.model_dump(mode="json")
        assert shipment.processing_error is None
        assert shipment.processing_started_at is not None
        assert shipment.processing_completed_at is not None
        assert session.query(Shipment).count() == 1


async def test_process_audio_failure_is_sanitized_and_preserves_media(
    shipment_store: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, shipment_id, media_path = shipment_store
    monkeypatch.setenv("SARVAM_API_KEY", "do-not-leak-this")

    async def failing_stt(_: str) -> STTResult:
        raise SttProviderError(
            "Bearer do-not-leak-this failed at https://provider.test/private"
        )

    result = await process_audio(
        shipment_id,
        session_factory=factory,
        stt=failing_stt,
    )

    assert result.status is ProcessingStatus.FAILED
    assert "do-not-leak-this" not in (result.reason or "")
    assert "provider.test" not in (result.reason or "")
    with factory() as session:
        shipment = session.get(Shipment, shipment_id)
        assert shipment is not None
        assert shipment.status is ShipmentStatus.FAILED
        assert shipment.media_path == str(media_path)
        assert shipment.raw_event == {"original": True}
        assert "do-not-leak-this" not in (shipment.processing_error or "")


async def test_process_audio_marks_missing_media_failed(shipment_store: tuple) -> None:
    factory, shipment_id, _ = shipment_store
    with factory() as session:
        shipment = session.get(Shipment, shipment_id)
        assert shipment is not None
        shipment.media_path = None
        session.commit()

    result = await process_audio(shipment_id, session_factory=factory)

    assert result.status is ProcessingStatus.FAILED
    with factory() as session:
        shipment = session.get(Shipment, shipment_id)
        assert shipment is not None
        assert shipment.status is ShipmentStatus.FAILED
        assert shipment.processing_error == "Shipment does not have downloaded media."
