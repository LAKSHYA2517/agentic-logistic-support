"""Database engine, model base, and request-scoped session handling."""

import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import Engine, MetaData, create_engine, event, inspect
from sqlalchemy.schema import CreateTable
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        """Enable foreign-key enforcement for each SQLite connection."""

        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    """Base class for SQLAlchemy ORM models."""


def init_db() -> None:
    """Create tables that do not yet exist for local development."""

    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    upgrade_local_sqlite_schema(engine)


def upgrade_local_sqlite_schema(db_engine: Engine) -> None:
    """Add known MVP columns to SQLite databases created by earlier phases."""

    if db_engine.dialect.name != "sqlite":
        return

    inspector = inspect(db_engine)
    if "shipments" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("shipments")}
    if {"user_id", "status", "raw_event"} <= existing_columns:
        with db_engine.connect() as connection:
            table_sql = connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='shipments'"
            ).scalar_one_or_none()
        if table_sql and (
            "IN_TRANSIT" not in table_sql or "DELIVERED" not in table_sql
        ):
            _rebuild_shipments_with_current_statuses(db_engine, existing_columns)
            inspector = inspect(db_engine)

    existing_columns = {column["name"] for column in inspector.get_columns("shipments")}
    column_definitions = {
        "message_id": "VARCHAR(255)",
        "message_type": "VARCHAR(32)",
        "media_error": "TEXT",
        "transcript": "TEXT",
        "extracted_data": "JSON",
        "processing_error": "TEXT",
        "processing_started_at": "DATETIME",
        "processing_completed_at": "DATETIME",
        "driver_id": "INTEGER REFERENCES drivers(id)",
        "driver_confirmation_status": "VARCHAR(16)",
        "driver_message_sent_at": "DATETIME",
        "driver_reply_message_id": "VARCHAR(255)",
        "pod_message_id": "VARCHAR(255)",
        "pod_media_id": "VARCHAR(255)",
        "pod_media_path": "VARCHAR(1024)",
        "pod_text": "TEXT",
        "pod_error": "TEXT",
    }

    with db_engine.begin() as connection:
        for column_name, column_type in column_definitions.items():
            if column_name not in existing_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE shipments ADD COLUMN {column_name} {column_type}"
                )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_shipments_message_id "
            "ON shipments (message_id)"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_shipments_driver_reply_message_id "
            "ON shipments (driver_reply_message_id)"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_shipments_pod_message_id "
            "ON shipments (pod_message_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_shipments_pod_media_id "
            "ON shipments (pod_media_id)"
        )


def _rebuild_shipments_with_current_statuses(
    db_engine: Engine,
    existing_columns: set[str],
) -> None:
    """Recreate SQLite's status CHECK constraint while preserving all rows."""

    from app.models import Shipment

    temporary_name = "shipments_status_upgrade"
    temporary_metadata = MetaData()
    Base.metadata.tables["users"].to_metadata(temporary_metadata)
    Base.metadata.tables["drivers"].to_metadata(temporary_metadata)
    temporary_table = Shipment.__table__.to_metadata(
        temporary_metadata,
        name=temporary_name,
    )
    current_columns = [
        column.name
        for column in Shipment.__table__.columns
        if column.name in existing_columns
    ]
    quoted_columns = ", ".join(f'"{name}"' for name in current_columns)

    with db_engine.begin() as connection:
        connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{temporary_name}"')
        connection.execute(CreateTable(temporary_table))
        connection.exec_driver_sql(
            f'INSERT INTO "{temporary_name}" ({quoted_columns}) '
            f'SELECT {quoted_columns} FROM "shipments"'
        )
        connection.exec_driver_sql('DROP TABLE "shipments"')
        connection.exec_driver_sql(
            f'ALTER TABLE "{temporary_name}" RENAME TO "shipments"'
        )

        for index in Shipment.__table__.indexes:
            index.create(bind=connection, checkfirst=True)


def get_db() -> Generator[Session, None, None]:
    """Provide one database session per request and always close it."""

    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
