import pytest

from app.intelligence.exceptions import ExtractionInvalidResponseError, SttProviderError
from app.intelligence.models import (
    LogisticsExtraction,
    ProcessingStatus,
    STTResult,
)
from app.intelligence.service import InMemoryIdempotencyStore, run_audio_pipeline


@pytest.fixture
def audio_file(tmp_path):
    path = tmp_path / "note.ogg"
    path.write_bytes(b"OggS fake audio bytes for shipment note")
    return str(path)


def make_stt(transcript: str, *, call_counter: list[int] | None = None):
    async def _stt(file_path, keyterms=None):
        if call_counter is not None:
            call_counter[0] += 1
        return STTResult(transcript=transcript, provider="fake", model="fake")

    return _stt


def failing_stt():
    async def _stt(file_path, keyterms=None):
        raise SttProviderError("simulated Sarvam outage (503)")

    return _stt


def make_extractor(extraction: LogisticsExtraction, *, call_counter: list[int] | None = None):
    async def _extractor(transcript):
        if call_counter is not None:
            call_counter[0] += 1
        return extraction

    return _extractor


def failing_extractor():
    async def _extractor(transcript):
        raise ExtractionInvalidResponseError(
            "simulated malformed structured output after bounded retries"
        )

    return _extractor


# ---------------------------------------------------------------------------
# Successful pipeline / accepted result
# ---------------------------------------------------------------------------


async def test_successful_pipeline_end_to_end(audio_file):
    result = await run_audio_pipeline(
        shipment_id=42,
        file_path=audio_file,
        stt=make_stt("Ramesh ko truck RJ14GB1122 se advance das hazaar diya"),
        extractor=make_extractor(
            LogisticsExtraction(
                party_name="Ramesh", truck_number="RJ14GB1122", advance_paid=10000
            )
        ),
    )

    assert result.status == ProcessingStatus.ACCEPTED
    assert result.shipment_id == 42
    assert result.extraction.party_name == "Ramesh"
    assert result.extraction.truck_number == "RJ14GB1122"
    assert result.extraction.advance_paid == 10000
    assert result.reason is None


async def test_accepted_result_shape(audio_file):
    result = await run_audio_pipeline(
        shipment_id=7,
        file_path=audio_file,
        stt=make_stt("truck RJ14GB1122 confirmed"),
        extractor=make_extractor(LogisticsExtraction(truck_number="RJ14GB1122")),
    )

    assert result.status == ProcessingStatus.ACCEPTED
    assert result.shipment_id == 7
    assert isinstance(result.extraction, LogisticsExtraction)
    assert result.reason is None


# ---------------------------------------------------------------------------
# Failures at each stage
# ---------------------------------------------------------------------------


async def test_media_validation_failure_returns_failed():
    result = await run_audio_pipeline(shipment_id=1, file_path="/does/not/exist.ogg")

    assert result.status == ProcessingStatus.FAILED
    assert result.shipment_id == 1
    assert result.extraction is None
    assert "media validation failed" in result.reason


async def test_stt_failure_returns_failed(audio_file):
    result = await run_audio_pipeline(
        shipment_id=2,
        file_path=audio_file,
        stt=failing_stt(),
    )

    assert result.status == ProcessingStatus.FAILED
    assert result.extraction is None
    assert "speech-to-text failed" in result.reason


async def test_extraction_failure_returns_failed(audio_file):
    result = await run_audio_pipeline(
        shipment_id=3,
        file_path=audio_file,
        stt=make_stt("advance das hazaar diya"),
        extractor=failing_extractor(),
    )

    assert result.status == ProcessingStatus.FAILED
    assert result.extraction is None
    assert "logistics extraction failed" in result.reason


async def test_validation_failure_fabricated_field_returns_failed(audio_file):
    # The extractor claims a party name the transcript never mentions --
    # deterministic validation (Phase 2E) marks it INVALID, and since it's
    # the only field stated, the review-gate (Phase 2F) maps that to FAILED.
    result = await run_audio_pipeline(
        shipment_id=4,
        file_path=audio_file,
        stt=make_stt("truck left the yard this morning"),
        extractor=make_extractor(LogisticsExtraction(party_name="GhostParty")),
    )

    assert result.status == ProcessingStatus.FAILED
    assert result.extraction is None
    assert result.reason is not None
    assert result.invalid_fields == ["party_name"]
    assert result.missing_fields == [
        "truck_number",
        "destination",
        "advance_paid",
        "balance_due",
    ]


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


async def test_ambiguous_amount_returns_needs_review(audio_file):
    result = await run_audio_pipeline(
        shipment_id=5,
        file_path=audio_file,
        stt=make_stt("Ramesh shayad das hazaar advance dega"),
        extractor=make_extractor(
            LogisticsExtraction(party_name="Ramesh", advance_paid=10000)
        ),
    )

    assert result.status == ProcessingStatus.NEEDS_REVIEW
    assert result.extraction is not None
    assert result.extraction.party_name == "Ramesh"
    assert result.reason is not None


async def test_conflicting_amounts_returns_needs_review(audio_file):
    result = await run_audio_pipeline(
        shipment_id=6,
        file_path=audio_file,
        stt=make_stt("advance paid 5000, advance bhi 8000 hua tha"),
        extractor=make_extractor(LogisticsExtraction(advance_paid=5000)),
    )

    assert result.status == ProcessingStatus.NEEDS_REVIEW
    assert result.reason is not None


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


async def test_duplicate_processing_is_served_from_cache(audio_file):
    stt_calls: list[int] = [0]
    extractor_calls: list[int] = [0]
    store = InMemoryIdempotencyStore()

    kwargs = dict(
        shipment_id=99,
        file_path=audio_file,
        stt=make_stt("truck RJ14GB1122 confirmed", call_counter=stt_calls),
        extractor=make_extractor(
            LogisticsExtraction(truck_number="RJ14GB1122"), call_counter=extractor_calls
        ),
        idempotency_store=store,
    )

    first = await run_audio_pipeline(**kwargs)
    second = await run_audio_pipeline(**kwargs)

    assert first == second
    assert stt_calls[0] == 1
    assert extractor_calls[0] == 1


async def test_transient_stt_failure_is_not_cached_and_can_be_retried(audio_file):
    # Regression test: a FAILED result caused by a transient provider
    # failure must not be cached -- otherwise a brief outage would
    # permanently block that exact audio content from ever succeeding.
    store = InMemoryIdempotencyStore()

    first = await run_audio_pipeline(
        shipment_id=55,
        file_path=audio_file,
        stt=failing_stt(),
        idempotency_store=store,
    )
    assert first.status == ProcessingStatus.FAILED

    second = await run_audio_pipeline(
        shipment_id=55,
        file_path=audio_file,
        stt=make_stt("truck RJ14GB1122 confirmed"),
        extractor=make_extractor(LogisticsExtraction(truck_number="RJ14GB1122")),
        idempotency_store=store,
    )

    assert second.status == ProcessingStatus.ACCEPTED


async def test_transient_extraction_failure_is_not_cached_and_can_be_retried(audio_file):
    store = InMemoryIdempotencyStore()

    first = await run_audio_pipeline(
        shipment_id=56,
        file_path=audio_file,
        stt=make_stt("truck RJ14GB1122 confirmed"),
        extractor=failing_extractor(),
        idempotency_store=store,
    )
    assert first.status == ProcessingStatus.FAILED

    second = await run_audio_pipeline(
        shipment_id=56,
        file_path=audio_file,
        stt=make_stt("truck RJ14GB1122 confirmed"),
        extractor=make_extractor(LogisticsExtraction(truck_number="RJ14GB1122")),
        idempotency_store=store,
    )

    assert second.status == ProcessingStatus.ACCEPTED


async def test_different_shipment_ids_are_not_conflated(audio_file):
    store = InMemoryIdempotencyStore()

    result_a = await run_audio_pipeline(
        shipment_id=1,
        file_path=audio_file,
        stt=make_stt("truck RJ14GB1122 confirmed"),
        extractor=make_extractor(LogisticsExtraction(truck_number="RJ14GB1122")),
        idempotency_store=store,
    )
    result_b = await run_audio_pipeline(
        shipment_id=2,
        file_path=audio_file,
        stt=make_stt("truck RJ14GB1122 confirmed"),
        extractor=make_extractor(LogisticsExtraction(truck_number="RJ14GB1122")),
        idempotency_store=store,
    )

    assert result_a.shipment_id == 1
    assert result_b.shipment_id == 2


async def test_without_idempotency_store_pipeline_reruns_every_call(audio_file):
    stt_calls: list[int] = [0]

    kwargs = dict(
        shipment_id=11,
        file_path=audio_file,
        stt=make_stt("truck RJ14GB1122 confirmed", call_counter=stt_calls),
        extractor=make_extractor(LogisticsExtraction(truck_number="RJ14GB1122")),
    )

    await run_audio_pipeline(**kwargs)
    await run_audio_pipeline(**kwargs)

    assert stt_calls[0] == 2
