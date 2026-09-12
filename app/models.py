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
    FAILED = "FAILED"


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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="shipments")


__all__ = ["Base", "Shipment", "ShipmentStatus", "User", "UserRole"]
