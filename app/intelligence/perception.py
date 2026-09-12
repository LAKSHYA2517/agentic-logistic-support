"""Document-perception orchestration backed by Sarvam Vision.

This module owns only orchestration and deterministic output-quality
annotation. Provider-specific API handling lives in ``app.intelligence.ocr``;
logistics extraction, Shipment updates, and webhook processing remain separate.
"""

from __future__ import annotations

from app.intelligence.models import OCRQuality, OCRResult
from app.intelligence.ocr import (
    SarvamVisionProvider,
    VisionProvider,
    evaluate_ocr_quality,
)


async def extract_document_text(
    file_path: str,
    *,
    vision_provider: VisionProvider | None = None,
) -> OCRResult:
    """Digitise one document and annotate its result with a quality verdict."""

    provider = vision_provider or SarvamVisionProvider()
    result = await provider.extract_text(file_path)
    quality = evaluate_ocr_quality(result)
    return _annotated(result, quality=quality)


def _annotated(
    result: OCRResult,
    *,
    quality: OCRQuality,
) -> OCRResult:
    metadata = dict(result.metadata)
    metadata["quality"] = quality.value
    return result.model_copy(update={"metadata": metadata})
