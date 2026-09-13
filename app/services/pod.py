"""POD intake and verification for a driver's active shipment."""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.database import SessionLocal
from app.intelligence.http_support import sanitize_provider_message
from app.intelligence.models import (
    LogisticsExtraction,
    OCRQuality,
    OCRResult,
    ValidationStatus,
)
from app.intelligence.ocr import evaluate_ocr_quality
from app.intelligence.perception import extract_document_text
from app.intelligence.validation import normalize_truck_number, validate_extraction
from app.models import Driver, DriverConfirmationStatus, Shipment, ShipmentStatus
from app.services.messaging import MetaMessagingError, send_whatsapp_text
from app.services.meta import MetaMediaError, MetaMediaService
from app.services.webhook import ParsedPodMessage
from app.services.workflow_messages import (
    driver_pod_verified_message,
    owner_delivery_complete_message,
    pod_review_message,
)


logger = logging.getLogger(__name__)
SessionFactory = Callable[[], Session]
PodDownloader = Callable[[str, int, str | None], Path]
DocumentReader = Callable[[str], Awaitable[OCRResult]]
PodExtractor = Callable[[str], Awaitable[LogisticsExtraction]]
MessageSender = Callable[[str, str], None]


@dataclass
class PodIngestionResult:
    """POD messages claimed synchronously before background processing."""

    queued_shipment_ids: list[int] = field(default_factory=list)
    duplicates: int = 0
    ignored: int = 0
    failed: int = 0


async def extract_pod_fields(text: str) -> LogisticsExtraction:
    """Extract explicitly labelled POD fields without another AI provider."""

    truck_value = _labelled_value(text, ("vehicle no", "vehicle number", "truck"))
    truck = normalize_truck_number(truck_value) if truck_value else None
    destination = _labelled_value(text, ("destination", "delivery location"))
    party = _labelled_value(text, ("party", "consignee"))
    advance = _amount_value(_labelled_value(text, ("advanced", "advance")))
    balance = _amount_value(_labelled_value(text, ("balance", "remaining")))
    return LogisticsExtraction(
        party_name=party,
        truck_number=truck,
        destination=destination,
        advance_paid=advance,
        balance_due=balance,
    )


def claim_pod_messages(
    db: Session,
    messages: list[ParsedPodMessage],
) -> PodIngestionResult:
    """Attach each new POD message to its driver's latest active shipment."""

    result = PodIngestionResult()
    for message in messages:
        existing = _find_existing_pod(db, message)
        if existing is not None:
            logger.info(
                "pod_duplicate_ignored shipment_id=%s message_id=%s",
                existing.id,
                message.message_id,
            )
            result.duplicates += 1
            continue

        driver = db.scalar(select(Driver).where(Driver.phone == message.sender_number))
        if driver is None:
            logger.info("pod_ignored reason=unknown_driver sender=%s", message.sender_number)
            result.ignored += 1
            continue

        shipment = db.scalar(
            select(Shipment)
            .where(
                Shipment.driver_id == driver.id,
                Shipment.driver_confirmation_status
                == DriverConfirmationStatus.CONFIRMED,
                or_(
                    Shipment.status == ShipmentStatus.IN_TRANSIT,
                    Shipment.status == ShipmentStatus.COMPLETED,
                    Shipment.status == ShipmentStatus.PARSED,
                ),
            )
            .order_by(Shipment.updated_at.desc(), Shipment.id.desc())
        )
        if shipment is None:
            logger.info("pod_ignored reason=no_active_shipment driver_id=%s", driver.id)
            result.ignored += 1
            continue
        if (
            shipment.pod_message_id is not None
            and shipment.status is not ShipmentStatus.PARSED
        ):
            logger.info(
                "pod_duplicate_ignored shipment_id=%s reason=shipment_already_has_pod",
                shipment.id,
            )
            result.duplicates += 1
            continue

        retrying_pod = shipment.status is ShipmentStatus.PARSED

        shipment.status = ShipmentStatus.IN_TRANSIT
        shipment.pod_message_id = message.message_id
        shipment.pod_media_id = message.media_id
        shipment.pod_media_path = None
        shipment.pod_text = None
        shipment.pod_error = None

        if message.media_id is None:
            shipment.status = ShipmentStatus.PARSED
            shipment.pod_error = "POD message did not include a media ID."
            _commit(db)
            result.failed += 1
            continue

        try:
            _commit(db)
        except IntegrityError:
            db.rollback()
            if _find_existing_pod(db, message) is None:
                raise
            result.duplicates += 1
            continue

        logger.info(
            "pod_received shipment_id=%s message_id=%s media_id=%s retry=%s",
            shipment.id,
            message.message_id,
            message.media_id,
            retrying_pod,
        )
        result.queued_shipment_ids.append(shipment.id)

    return result


async def process_pod(
    shipment_id: int,
    *,
    settings: AppSettings,
    session_factory: SessionFactory = SessionLocal,
    media_downloader: PodDownloader | None = None,
    document_reader: DocumentReader = extract_document_text,
    extractor: PodExtractor = extract_pod_fields,
    message_sender: MessageSender | None = None,
) -> None:
    """Download, read, validate, and compare one claimed POD document."""

    with session_factory() as session:
        shipment = session.get(Shipment, shipment_id)
        if shipment is None or not shipment.pod_media_id:
            return
        media_id = shipment.pod_media_id

    logger.info("pod_download_started shipment_id=%s media_id=%s", shipment_id, media_id)
    try:
        if media_downloader is None:
            path = await asyncio.to_thread(
                _download_pod_from_meta,
                settings,
                media_id,
                shipment_id,
                None,
            )
        else:
            path = await asyncio.to_thread(media_downloader, media_id, shipment_id, None)
    except Exception as exc:
        reason = _safe_failure("POD download failed", exc)
        _mark_review(session_factory, shipment_id, reason)
        logger.warning("pod_download_failed shipment_id=%s reason=%s", shipment_id, reason)
        await _notify_pod_review(session_factory, settings, shipment_id, reason, message_sender)
        return

    with session_factory() as session:
        shipment = session.get(Shipment, shipment_id)
        if shipment is None:
            path.unlink(missing_ok=True)
            return
        shipment.pod_media_path = str(path)
        _commit(session)
    logger.info("pod_download_completed shipment_id=%s file_name=%s", shipment_id, path.name)

    try:
        ocr_result = await document_reader(str(path))
    except Exception as exc:
        reason = _safe_failure("POD Vision processing failed", exc)
        _mark_review(session_factory, shipment_id, reason)
        logger.warning("pod_vision_failed shipment_id=%s reason=%s", shipment_id, reason)
        await _notify_pod_review(session_factory, settings, shipment_id, reason, message_sender)
        return

    with session_factory() as session:
        shipment = session.get(Shipment, shipment_id)
        if shipment is None:
            return
        shipment.pod_text = ocr_result.text or None
        _commit(session)

    quality = evaluate_ocr_quality(ocr_result)
    if quality is not OCRQuality.GOOD:
        provider_error = ocr_result.metadata.get("error")
        if isinstance(provider_error, str) and provider_error.strip():
            reason = _safe_failure("POD Vision failed", RuntimeError(provider_error))
        else:
            reason = f"POD Vision output quality was {quality.value}."
        _mark_review(session_factory, shipment_id, reason)
        logger.warning(
            "pod_vision_uncertain shipment_id=%s quality=%s reason=%s",
            shipment_id,
            quality.value,
            reason,
        )
        await _notify_pod_review(session_factory, settings, shipment_id, reason, message_sender)
        return

    try:
        extraction = await extractor(ocr_result.text)
        validation = validate_extraction(extraction, ocr_result.text)
    except Exception as exc:
        reason = _safe_failure("POD information extraction failed", exc)
        _mark_review(session_factory, shipment_id, reason)
        logger.warning("pod_extraction_failed shipment_id=%s reason=%s", shipment_id, reason)
        await _notify_pod_review(session_factory, settings, shipment_id, reason, message_sender)
        return

    if validation.status is not ValidationStatus.ACCEPTED:
        reason = "; ".join(validation.issues) or "POD information was uncertain."
        _mark_review(session_factory, shipment_id, reason)
        logger.warning("pod_verification_review shipment_id=%s reason=%s", shipment_id, reason)
        await _notify_pod_review(session_factory, settings, shipment_id, reason, message_sender)
        return

    with session_factory() as session:
        shipment = session.get(Shipment, shipment_id)
        if shipment is None:
            return
        issues, match_count = compare_pod_to_shipment(shipment, extraction)
        if issues or match_count == 0:
            reason = "; ".join(issues) or (
                "POD did not contain a shipment field that could be verified."
            )
            shipment.status = ShipmentStatus.PARSED
            shipment.pod_error = reason
            outcome = "NEEDS_REVIEW"
        else:
            shipment.status = ShipmentStatus.DELIVERED
            shipment.pod_error = None
            outcome = "DELIVERED"
        _commit(session)

    logger.info("pod_verification_completed shipment_id=%s outcome=%s", shipment_id, outcome)
    if outcome == "DELIVERED":
        await _notify_pod_delivered(session_factory, settings, shipment_id, message_sender)
    else:
        await _notify_pod_review(session_factory, settings, shipment_id, reason, message_sender)


def compare_pod_to_shipment(
    shipment: Shipment,
    pod: LogisticsExtraction,
) -> tuple[list[str], int]:
    """Compare only POD fields that are present; never invent missing evidence."""

    expected = shipment.extracted_data or {}
    issues: list[str] = []
    matches = 0

    pod_truck = normalize_truck_number(pod.truck_number) if pod.truck_number else None
    expected_truck_value = expected.get("truck_number") or (
        shipment.driver.truck_number if shipment.driver is not None else None
    )
    expected_truck = (
        normalize_truck_number(str(expected_truck_value))
        if expected_truck_value
        else None
    )
    if pod_truck and expected_truck:
        if pod_truck == expected_truck:
            matches += 1
        else:
            issues.append(
                f"POD truck number {pod_truck} conflicts with shipment truck {expected_truck}."
            )

    for field_name, label in (("destination", "destination"), ("party_name", "party")):
        pod_value = getattr(pod, field_name)
        expected_value = expected.get(field_name)
        if not pod_value or not expected_value:
            continue
        if field_name == "destination":
            matches_field = _destinations_match(
                str(pod_value),
                str(expected_value),
            )
        else:
            matches_field = (
                _comparison_key(str(pod_value)) == _comparison_key(str(expected_value))
            )
        if matches_field:
            matches += 1
        else:
            issues.append(
                f"POD {label} {pod_value!r} conflicts with shipment {label} "
                f"{expected_value!r}."
            )

    return issues, matches


def _comparison_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^\w]+", "", normalized)


def _labelled_value(text: str, labels: tuple[str, ...]) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        for label in labels:
            match = re.match(
                rf"^{re.escape(label)}\.?\s*(?::|-)?\s*(.*)$",
                line,
                flags=re.IGNORECASE,
            )
            if match is None:
                continue
            inline_value = match.group(1).strip()
            if inline_value:
                return inline_value
            if index + 1 < len(lines):
                return lines[index + 1]
    return None


def _amount_value(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d[\d,]*", value)
    return int(match.group().replace(",", "")) if match else None


_DESTINATION_ALIASES = {
    "दिल्ली": "delhi",
    "नईदिल्ली": "delhi",
    "नयीदिल्ली": "delhi",
}


def _destinations_match(pod_value: str, expected_value: str) -> bool:
    """Compare destination words across scripts with narrow OCR-error tolerance."""

    pod_tokens = _destination_tokens(pod_value)
    expected_tokens = _destination_tokens(expected_value)
    for pod_token in pod_tokens:
        for expected_token in expected_tokens:
            if pod_token == expected_token:
                return True
            if (
                pod_token.isascii()
                and expected_token.isascii()
                and min(len(pod_token), len(expected_token)) >= 5
                and _within_one_substitution(pod_token, expected_token)
            ):
                return True
    return False


def _destination_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    compact = re.sub(r"[^\w]+", "", normalized)
    tokens = set(re.findall(r"[a-z0-9]+|[ऀ-ॿ]+", normalized))
    tokens.add(compact)
    for source, canonical in _DESTINATION_ALIASES.items():
        if source in normalized or source in compact:
            tokens.add(canonical)
    return {token for token in tokens if token}


def _within_one_substitution(left: str, right: str) -> bool:
    """Allow one OCR character substitution, never insertion or deletion."""

    return len(left) == len(right) and sum(a != b for a, b in zip(left, right)) <= 1


def _download_pod_from_meta(
    settings: AppSettings,
    media_id: str,
    shipment_id: int,
    mime_type: str | None,
) -> Path:
    with httpx.Client(
        timeout=settings.meta_request_timeout_seconds,
        follow_redirects=True,
    ) as http_client:
        service = MetaMediaService(
            access_token=settings.meta_access_token,
            graph_api_base_url=settings.meta_graph_api_base_url,
            graph_api_version=settings.meta_api_version,
            output_dir=settings.media_download_dir,
            max_media_bytes=settings.media_max_bytes,
            http_client=http_client,
            phone_number_id=settings.meta_phone_number_id,
        )
        return service.download_document(media_id, shipment_id, mime_type)


def _mark_review(session_factory: SessionFactory, shipment_id: int, reason: str) -> None:
    with session_factory() as session:
        shipment = session.get(Shipment, shipment_id)
        if shipment is None:
            return
        shipment.status = ShipmentStatus.PARSED
        shipment.pod_error = reason
        _commit(session)


def _safe_failure(prefix: str, exc: Exception) -> str:
    if isinstance(exc, MetaMediaError):
        detail = str(exc)
    else:
        detail = str(exc) or type(exc).__name__
    return f"{prefix}: {sanitize_provider_message(detail)}"


async def _notify_pod_review(
    session_factory: SessionFactory,
    settings: AppSettings,
    shipment_id: int,
    reason: str,
    message_sender: MessageSender | None,
) -> None:
    with session_factory() as session:
        shipment = session.get(Shipment, shipment_id)
        if shipment is None or shipment.driver is None:
            return
        driver_name = shipment.driver.name
        driver_phone = shipment.driver.phone
    await _send_pod_workflow_message(
        settings,
        to=driver_phone,
        body=pod_review_message(driver_name, reason),
        event="driver_pod_review",
        shipment_id=shipment_id,
        message_sender=message_sender,
    )


async def _notify_pod_delivered(
    session_factory: SessionFactory,
    settings: AppSettings,
    shipment_id: int,
    message_sender: MessageSender | None,
) -> None:
    with session_factory() as session:
        shipment = session.get(Shipment, shipment_id)
        if shipment is None or shipment.driver is None:
            return
        driver_name = shipment.driver.name
        driver_phone = shipment.driver.phone
        owner_phone = shipment.user.whatsapp_number
        extracted = shipment.extracted_data or {}
        owner_message = owner_delivery_complete_message(
            shipment_id=shipment.id,
            party=extracted.get("party_name"),
            driver=driver_name,
            truck=extracted.get("truck_number") or shipment.driver.truck_number,
            destination=extracted.get("destination"),
            advance=extracted.get("advance_paid"),
            balance=extracted.get("balance_due"),
        )
    await _send_pod_workflow_message(
        settings,
        to=driver_phone,
        body=driver_pod_verified_message(driver_name),
        event="driver_pod_verified",
        shipment_id=shipment_id,
        message_sender=message_sender,
    )
    await _send_pod_workflow_message(
        settings,
        to=owner_phone,
        body=owner_message,
        event="owner_delivery_complete",
        shipment_id=shipment_id,
        message_sender=message_sender,
    )


async def _send_pod_workflow_message(
    settings: AppSettings,
    *,
    to: str,
    body: str,
    event: str,
    shipment_id: int,
    message_sender: MessageSender | None,
) -> None:
    sender = message_sender or (
        lambda recipient, text: send_whatsapp_text(settings, to=recipient, body=text)
    )
    try:
        await asyncio.to_thread(sender, to, body)
    except MetaMessagingError as exc:
        logger.warning(
            "pod_message_send_failed event=%s shipment_id=%s reason=%s",
            event,
            shipment_id,
            exc,
        )
    except Exception as exc:
        logger.error(
            "pod_message_send_failed event=%s shipment_id=%s error_type=%s",
            event,
            shipment_id,
            type(exc).__name__,
        )
    else:
        logger.info("pod_message_sent event=%s shipment_id=%s", event, shipment_id)


def _find_existing_pod(
    db: Session,
    message: ParsedPodMessage,
) -> Shipment | None:
    if message.message_id:
        existing = db.scalar(
            select(Shipment).where(Shipment.pod_message_id == message.message_id)
        )
        if existing is not None:
            return existing
    if message.message_id is None and message.media_id:
        return db.scalar(
            select(Shipment).where(Shipment.pod_media_id == message.media_id)
        )
    return None


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
