"""Perception orchestration: decides GOOD vs POOR/FAILED and when to fall back.

    IMAGE / DOCUMENT
           |
    AI4BHARAT INDICOCR  (primary)
           |
    evaluate_ocr_quality()
           |
      GOOD ----------------------------+
           |                           |
      POOR / FAILED                    |
           |                           |
    SARVAM VISION (fallback,           |
    only if a vision_provider          |
    was supplied)                      |
           |                           |
           +---------------------------+
                       |
              unified OCRResult

This module contains no provider-specific API logic -- it only knows
the ``OCRProvider``/``VisionProvider`` Protocol shape
(``app.intelligence.ocr``) and the fallback decision rule. It does not
perform logistics/POD extraction, Shipment updates, or database
operations.

Primary OCR always runs. The fallback provider is only ever called
when the primary result is POOR or FAILED, and only if one was
supplied -- IndicOCR + Vision are never both run unconditionally, to
avoid doubling API cost/latency and never producing two conflicting
readings of a GOOD document.
"""

from __future__ import annotations

from app.intelligence.models import OCRQuality, OCRResult
from app.intelligence.ocr import OCRProvider, VisionProvider, evaluate_ocr_quality


async def extract_document_text(
    file_path: str,
    *,
    ocr_provider: OCRProvider,
    vision_provider: VisionProvider | None = None,
) -> OCRResult:
    """Run primary OCR, and fall back to Vision only when necessary.

    Returns the primary ``OCRResult`` unchanged (metadata carries the
    computed ``quality`` and ``fallback_used: False``) when quality is
    GOOD, or when quality is POOR/FAILED but no ``vision_provider`` was
    supplied. Otherwise runs ``vision_provider`` and returns its
    result, with ``fallback_used: True`` and the primary result's
    quality recorded for observability.
    """
    primary_result = await ocr_provider.extract_text(file_path)
    primary_quality = evaluate_ocr_quality(primary_result)

    if primary_quality == OCRQuality.GOOD or vision_provider is None:
        return _annotated(primary_result, quality=primary_quality, fallback_used=False)

    vision_result = await vision_provider.extract_text(file_path)
    vision_quality = evaluate_ocr_quality(vision_result)

    return _annotated(
        vision_result,
        quality=vision_quality,
        fallback_used=True,
        primary_quality=primary_quality,
    )


def _annotated(
    result: OCRResult,
    *,
    quality: OCRQuality,
    fallback_used: bool,
    primary_quality: OCRQuality | None = None,
) -> OCRResult:
    metadata = dict(result.metadata)
    metadata["quality"] = quality.value
    metadata["fallback_used"] = fallback_used
    if primary_quality is not None:
        metadata["primary_quality"] = primary_quality.value
    return result.model_copy(update={"metadata": metadata})
