"""Database engine, model base, and request-scoped session handling."""

import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, event, inspect
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
    column_definitions = {
        "message_id": "VARCHAR(255)",
        "message_type": "VARCHAR(32)",
        "media_error": "TEXT",
        "transcript": "TEXT",
        "extracted_data": "JSON",
        "processing_error": "TEXT",
        "processing_started_at": "DATETIME",
        "processing_completed_at": "DATETIME",
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
