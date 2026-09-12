"""Media Intake & Validation layer.

Validates a locally-stored .ogg voice note before it is handed to the
Sarvam STT adapter. This module intentionally does no STT, no LLM
extraction, and no database state transitions -- it only establishes
that the file is a real, non-empty, correctly-typed, reasonably-sized
audio file, and computes a content hash for idempotency.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from app.intelligence.exceptions import (
    EmptyMediaError,
    InvalidMediaExtensionError,
    MediaNotFoundError,
    MediaTooLargeError,
)
from app.intelligence.models import MediaMetadata

ALLOWED_EXTENSIONS = {".ogg"}

# Voice notes are short (Sarvam's REST endpoint tops out around 30s of
# audio); 25 MB is a generous ceiling that still catches corrupt or
# mis-routed uploads.
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024

_HASH_CHUNK_SIZE = 1024 * 1024


def _read_and_hash(path: Path) -> tuple[int, str]:
    """Blocking helper: compute file size and SHA-256 digest in one pass."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


async def validate_media(file_path: str) -> MediaMetadata:
    """Validate a local audio file and return its metadata.

    Raises:
        MediaNotFoundError: the path does not exist or is not a regular file.
        InvalidMediaExtensionError: the file does not have an accepted extension.
        EmptyMediaError: the file has zero bytes.
        MediaTooLargeError: the file exceeds ``MAX_FILE_SIZE_BYTES``.
    """
    path = Path(file_path)

    if not path.exists() or not path.is_file():
        raise MediaNotFoundError(f"Media file not found: {file_path}")

    extension = path.suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise InvalidMediaExtensionError(
            f"Unsupported media extension '{extension}'; expected one of {sorted(ALLOWED_EXTENSIONS)}"
        )

    # Cheap size check first: reject an oversized (e.g. mis-routed) file
    # before paying the cost of streaming and hashing all of it.
    declared_size = await asyncio.to_thread(lambda: path.stat().st_size)
    if declared_size > MAX_FILE_SIZE_BYTES:
        raise MediaTooLargeError(
            f"Media file exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES} bytes: {declared_size} bytes"
        )

    size, sha256 = await asyncio.to_thread(_read_and_hash, path)

    if size == 0:
        raise EmptyMediaError(f"Media file is empty: {file_path}")

    if size > MAX_FILE_SIZE_BYTES:
        raise MediaTooLargeError(
            f"Media file exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES} bytes: {size} bytes"
        )

    return MediaMetadata(
        file_path=str(path),
        file_size=size,
        sha256=sha256,
        extension=extension,
    )
