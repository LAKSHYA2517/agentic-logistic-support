"""SQLAlchemy models for users and shipment lifecycle data."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Enum as SqlEnum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, Enum):
    """Application roles supported for WhatsApp users."""

    OWNER = "OWNER"
    TRANSPORTER = "TRANSPORTER"


class ShipmentStatus(str, Enum):
    """Supported shipment processing states."""

    RECEIVED = "RECEIVED"
    TRANSCRIBING = "TRANSCRIBING"
    PARSED = "PARSED"
    CONFIRMED = "CONFIRMED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class DriverConfirmationStatus(str, Enum):
    """Where a driver stands on one shipment assignment.

    Set to ``PENDING`` the moment the assignment WhatsApp message is
    sent, and moves to ``CONFIRMED``/``REJECTED`` only once the driver
    actually replies YES/NO. ``None`` on the shipment (not a member of
    this enum) means no driver has been assigned at all yet -- that is
    a distinct state from "assigned but not yet replied".
    """

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class User(Base):
    """A WhatsApp user and their application role."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    whatsapp_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    role: Mapped[UserRole] = mapped_column(
        SqlEnum(UserRole, native_enum=False, create_constraint=True, validate_strings=True),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    shipments: Mapped[list[Shipment]] = relationship(back_populates="user")


class Driver(Base):
    """A truck driver who can be assigned to a shipment for confirmation.

    ``truck_number`` is stored in the same canonical form Phase 2's
    validation layer already normalizes extracted truck numbers to
    (uppercase, no separators, e.g. "RJ14GB1122") -- see
    ``app.intelligence.validation.normalize_truck_number`` -- so a
    shipment's ``extracted_data["truck_number"]`` can be looked up
    directly against it.
    """

    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    truck_number: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    shipments: Mapped[list[Shipment]] = relationship(back_populates="driver")


class Shipment(Base):
    """A shipment event and its current processing state."""

    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[ShipmentStatus] = mapped_column(
        SqlEnum(
            ShipmentStatus,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ShipmentStatus.RECEIVED,
        server_default=ShipmentStatus.RECEIVED.value,
        index=True,
    )
    media_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    message_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    message_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    raw_event: Mapped[dict[str, Any]] = mapped_column(JSON)
    media_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    media_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    driver_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("drivers.id"), nullable=True, index=True
    )
    driver_confirmation_status: Mapped[Optional[DriverConfirmationStatus]] = mapped_column(
        SqlEnum(
            DriverConfirmationStatus,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    driver_message_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    driver_reply_message_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    pod_message_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    pod_media_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    pod_media_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    pod_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pod_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="shipments")
    driver: Mapped[Optional[Driver]] = relationship(back_populates="shipments")


__all__ = [
    "Base",
    "Driver",
    "DriverConfirmationStatus",
    "Shipment",
    "ShipmentStatus",
    "User",
    "UserRole",
]
