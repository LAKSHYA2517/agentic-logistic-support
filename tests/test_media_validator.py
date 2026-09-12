import hashlib

import pytest

from app.intelligence.exceptions import (
    EmptyMediaError,
    InvalidMediaExtensionError,
    MediaNotFoundError,
    MediaTooLargeError,
)
from app.intelligence.media_validator import MAX_FILE_SIZE_BYTES, validate_media
from app.intelligence.models import MediaMetadata


async def test_valid_ogg_file_returns_metadata(tmp_path):
    audio = tmp_path / "note.ogg"
    content = b"OggS" + b"fake audio bytes"
    audio.write_bytes(content)

    metadata = await validate_media(str(audio))

    assert isinstance(metadata, MediaMetadata)
    assert metadata.file_path == str(audio)
    assert metadata.file_size == len(content)
    assert metadata.extension == ".ogg"
    assert metadata.sha256 == hashlib.sha256(content).hexdigest()


async def test_missing_file_raises(tmp_path):
    missing = tmp_path / "does_not_exist.ogg"

    with pytest.raises(MediaNotFoundError):
        await validate_media(str(missing))


async def test_directory_path_raises(tmp_path):
    with pytest.raises(MediaNotFoundError):
        await validate_media(str(tmp_path))


async def test_empty_file_raises(tmp_path):
    audio = tmp_path / "empty.ogg"
    audio.write_bytes(b"")

    with pytest.raises(EmptyMediaError):
        await validate_media(str(audio))


async def test_wrong_extension_raises(tmp_path):
    audio = tmp_path / "note.mp3"
    audio.write_bytes(b"some bytes")

    with pytest.raises(InvalidMediaExtensionError):
        await validate_media(str(audio))


async def test_oversized_file_raises(tmp_path, monkeypatch):
    audio = tmp_path / "huge.ogg"
    audio.write_bytes(b"x" * 100)

    monkeypatch.setattr(
        "app.intelligence.media_validator.MAX_FILE_SIZE_BYTES", 10
    )

    with pytest.raises(MediaTooLargeError):
        await validate_media(str(audio))


async def test_oversized_file_rejected_before_hashing(tmp_path, monkeypatch):
    # The size check must happen before the file is streamed/hashed, so
    # an oversized file is rejected cheaply rather than after paying the
    # full cost of reading and hashing it.
    audio = tmp_path / "huge.ogg"
    audio.write_bytes(b"x" * 100)

    monkeypatch.setattr("app.intelligence.media_validator.MAX_FILE_SIZE_BYTES", 10)

    def _fail(path):
        raise AssertionError("hashing must not run for an oversized file")

    monkeypatch.setattr("app.intelligence.media_validator._read_and_hash", _fail)

    with pytest.raises(MediaTooLargeError):
        await validate_media(str(audio))


async def test_duplicate_file_hash_matches_for_idempotency(tmp_path):
    content = b"identical audio payload"
    audio_a = tmp_path / "a.ogg"
    audio_b = tmp_path / "b.ogg"
    audio_a.write_bytes(content)
    audio_b.write_bytes(content)

    meta_a = await validate_media(str(audio_a))
    meta_b = await validate_media(str(audio_b))

    assert meta_a.sha256 == meta_b.sha256
    assert meta_a.file_path != meta_b.file_path


async def test_different_content_yields_different_hash(tmp_path):
    audio_a = tmp_path / "a.ogg"
    audio_b = tmp_path / "b.ogg"
    audio_a.write_bytes(b"payload one")
    audio_b.write_bytes(b"payload two")

    meta_a = await validate_media(str(audio_a))
    meta_b = await validate_media(str(audio_b))

    assert meta_a.sha256 != meta_b.sha256
