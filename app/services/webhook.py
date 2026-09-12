"""Defensive parsing for Meta WhatsApp webhook envelopes."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ParsedMetaMessage:
    """Fields needed from an incoming WhatsApp message."""

    sender_number: str
    message_id: Optional[str]
    media_id: Optional[str]
    message_type: str


@dataclass(frozen=True)
class ParsedTextMessage:
    """Fields needed from an incoming WhatsApp text message (e.g. a driver's YES/NO)."""

    sender_number: str
    message_id: Optional[str]
    text_body: str


def extract_text_messages(payload: dict[str, Any]) -> list[ParsedTextMessage]:
    """Extract plain-text messages while tolerating missing/unexpected fields.

    Mirrors ``extract_audio_messages`` -- same envelope-walking helpers,
    just filtered to ``type == "text"`` messages with a non-empty body.
    """

    extracted: list[ParsedTextMessage] = []

    for entry in _dict_items(payload.get("entry")):
        for change in _dict_items(entry.get("changes")):
            value = change.get("value")
            if not isinstance(value, dict):
                continue

            fallback_sender = _contact_number(value.get("contacts"))
            for message in _dict_items(value.get("messages")):
                if _optional_string(message.get("type")) != "text":
                    continue

                text = message.get("text")
                body = _optional_string(text.get("body")) if isinstance(text, dict) else None
                if body is None:
                    continue

                sender_number = _optional_string(message.get("from")) or fallback_sender
                if sender_number is None:
                    continue

                extracted.append(
                    ParsedTextMessage(
                        sender_number=sender_number,
                        message_id=_optional_string(message.get("id")),
                        text_body=body,
                    )
                )

    return extracted


def extract_audio_messages(payload: dict[str, Any]) -> list[ParsedMetaMessage]:
    """Extract audio messages while tolerating missing or unexpected fields."""

    extracted: list[ParsedMetaMessage] = []

    for entry in _dict_items(payload.get("entry")):
        for change in _dict_items(entry.get("changes")):
            value = change.get("value")
            if not isinstance(value, dict):
                continue

            fallback_sender = _contact_number(value.get("contacts"))
            for message in _dict_items(value.get("messages")):
                audio = message.get("audio")
                message_type = _optional_string(message.get("type"))

                if message_type not in {"audio", "voice"} and not isinstance(audio, dict):
                    continue

                sender_number = _optional_string(message.get("from")) or fallback_sender
                if sender_number is None:
                    continue

                media_id = _optional_string(audio.get("id")) if isinstance(audio, dict) else None
                extracted.append(
                    ParsedMetaMessage(
                        sender_number=sender_number,
                        message_id=_optional_string(message.get("id")),
                        media_id=media_id,
                        message_type=message_type or "audio",
                    )
                )

    return extracted


def _dict_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _contact_number(contacts: object) -> Optional[str]:
    for contact in _dict_items(contacts):
        number = _optional_string(contact.get("wa_id"))
        if number is not None:
            return number
    return None


def _optional_string(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
