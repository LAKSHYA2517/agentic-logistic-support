"""Natural Hinglish copy for automatic WhatsApp workflow messages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.intelligence.models import LogisticsExtraction


_REQUIRED_ASSIGNMENT_FIELDS: tuple[tuple[str, str], ...] = (
    ("party_name", "party/consignee"),
    ("truck_number", "truck number"),
    ("destination", "destination"),
    ("advance_paid", "advance"),
    ("balance_due", "remaining balance"),
)
_FIELD_LABELS = dict(_REQUIRED_ASSIGNMENT_FIELDS)


def missing_assignment_fields(data: Mapping[str, Any] | LogisticsExtraction | None) -> list[str]:
    """Return display labels for fields absent from a voice-note extraction."""

    if isinstance(data, LogisticsExtraction):
        values = data.model_dump(mode="python")
    else:
        values = data or {}
    return [label for key, label in _REQUIRED_ASSIGNMENT_FIELDS if _missing(values.get(key))]


def owner_missing_details_message(fields: Sequence[str]) -> str:
    """Ask the owner to resend only the details that were not extracted."""

    missing = _join_hinglish(fields)
    return (
        f"Sir, kuch details miss ho gayi hain — {missing} nahi mila. "
        "Please ek baar voice note dobara bhej dijiye, saari details ke saath."
    )


def owner_details_correction_message(
    *,
    missing_fields: Sequence[str],
    invalid_fields: Sequence[str],
) -> str:
    """Ask for a retry while distinguishing absent from unclear/wrong details."""

    issues: list[str] = []
    if missing_fields:
        issues.append(f"{_join_hinglish(missing_fields)} nahi mila")
    if invalid_fields:
        issues.append(f"{_join_hinglish(invalid_fields)} clear ya valid nahi tha")
    detail = "; aur ".join(issues) or "required details verify nahi ho paayi"
    return (
        f"Sir, voice note mein kuch details missing ya galat hain — {detail}. "
        "Please ek baar voice note dobara bhej dijiye, saari correct details ke saath."
    )


def assignment_field_labels(field_names: Sequence[str]) -> list[str]:
    """Convert internal field keys to concise user-facing names."""

    return [_FIELD_LABELS[name] for name in field_names if name in _FIELD_LABELS]


def driver_assignment_message(
    *,
    driver_name: str,
    party: object,
    truck: object,
    destination: object,
    advance: object,
    balance: object,
) -> str:
    """Tell a matched driver about a new assignment in concise Hinglish."""

    return (
        f"Namaste {driver_name} ji 👋\n\n"
        "Aapko ek nayi delivery assign hui hai:\n\n"
        f"Party: {_display(party)}\n"
        f"Truck: {_display(truck)}\n"
        f"Destination: {_display(destination)}\n"
        f"Advance: {_format_currency(advance)}\n"
        f"Remaining: {_format_currency(balance)}\n\n"
        "Delivery confirm karne ke liye YES reply karein.\n"
        "Agar koi dikkat hai to bata dijiye."
    )


def owner_assignment_success_message(driver_name: str) -> str:
    return (
        "Delivery assign ho gayi hai ✅\n"
        f"{driver_name} ko shipment ki saari details bhej di hain.\n"
        "Ab driver ke confirmation ka wait kar rahe hain."
    )


def driver_confirmation_message(driver_name: str) -> str:
    return (
        f"Thik hai {driver_name} ji 👍\n"
        "Delivery confirm ho gayi hai.\n"
        "Shipment ab IN TRANSIT hai."
    )


def owner_driver_confirmed_message(driver_name: str) -> str:
    return (
        f"{driver_name} ne delivery confirm kar di hai ✅\n"
        "Shipment ab IN TRANSIT mein hai."
    )


def pod_reminder_message(driver_name: str) -> str:
    return (
        f"{driver_name} ji, delivery complete hone ke baad POD/proof of delivery "
        "ka photo bhej dijiye 📦📸"
    )


def pod_review_message(driver_name: str, reason: str) -> str:
    """Turn a stored verification reason into safe, actionable Hinglish."""

    normalized = reason.casefold()
    if "truck number" in normalized and ("conflict" in normalized or "match" in normalized):
        detail = "Truck number match nahi kar raha hai."
    elif "destination" in normalized and ("conflict" in normalized or "match" in normalized):
        detail = "Destination shipment ki details se match nahi kar raha hai."
    elif "party" in normalized and ("conflict" in normalized or "match" in normalized):
        detail = "Party/consignee shipment ki details se match nahi kar raha hai."
    elif "destination" in normalized:
        return (
            "POD mein destination clearly nahi mila.\n"
            "Please aisa POD/photo bhejiye jisme destination clearly visible ho."
        )
    else:
        detail = "Details clearly verify nahi ho rahi hain."

    return (
        f"{driver_name} ji, POD verify nahi ho paaya.\n"
        f"{detail}\n"
        "Please correct POD ka photo dobara bhej dijiye."
    )


def driver_pod_verified_message(driver_name: str) -> str:
    return (
        f"POD verify ho gaya {driver_name} ji ✅\n"
        "Delivery successfully DELIVERED mark kar di gayi hai."
    )


def owner_delivery_complete_message(
    *,
    shipment_id: int | None = None,
    party: object = None,
    driver: object = None,
    truck: object = None,
    destination: object = None,
    advance: object = None,
    balance: object = None,
) -> str:
    """Notify the owner with only real, available shipment details."""

    details: list[str] = []
    if shipment_id is not None:
        details.append(f"Shipment: SHP-{shipment_id}")
    for label, value in (
        ("Party", party),
        ("Driver", driver),
        ("Truck", truck),
        ("Destination", destination),
    ):
        if not _missing(value):
            details.append(f"{label}: {value}")
    if isinstance(advance, int) and not isinstance(advance, bool):
        details.append(f"Advance: {_format_currency(advance)}")
    if isinstance(balance, int) and not isinstance(balance, bool):
        details.append(f"Remaining: {_format_currency(balance)}")

    rendered_details = "\n".join(details)
    detail_block = f"\n\nShipment details:\n{rendered_details}\n" if details else "\n"
    return (
        "Delivery successfully complete ho gayi hai ✅"
        f"{detail_block}"
        "POD verify ho gaya aur shipment DELIVERED mark kar diya gaya hai."
    )


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _display(value: object) -> str:
    if _missing(value):
        return "Nahi mila"
    return str(value)


def _format_currency(amount: object) -> str:
    if isinstance(amount, int) and not isinstance(amount, bool):
        return f"₹{amount:,}"
    return "Nahi mila"


def _join_hinglish(values: Sequence[str]) -> str:
    if not values:
        return "required details"
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} aur {values[1]}"
    return f"{', '.join(values[:-1])} aur {values[-1]}"


__all__ = [
    "driver_assignment_message",
    "driver_confirmation_message",
    "driver_pod_verified_message",
    "missing_assignment_fields",
    "assignment_field_labels",
    "owner_assignment_success_message",
    "owner_delivery_complete_message",
    "owner_driver_confirmed_message",
    "owner_details_correction_message",
    "owner_missing_details_message",
    "pod_reminder_message",
    "pod_review_message",
]
