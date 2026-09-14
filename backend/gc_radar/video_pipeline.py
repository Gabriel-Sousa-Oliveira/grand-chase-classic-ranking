"""Auditable post-OCR decisions for video candidates."""
from __future__ import annotations

from dataclasses import dataclass

from .ocr import OcrResult


@dataclass(frozen=True)
class OcrTriage:
    destination: str
    processing_reason: str
    ocr_time_ms: int | None = None
    ocr_confidence: float | None = None
    evidence_frame: str | None = None
    evidence_seconds_from_end: int | None = None


def triage_ocr_result(result: OcrResult | None, error: Exception | None = None,
                      irrelevant: bool = False) -> OcrTriage:
    if irrelevant:
        return OcrTriage("rejected", "irrelevant_before_ocr")
    if error is not None:
        return OcrTriage("manual_review", "technical_error")
    if result is None:
        return OcrTriage("manual_review", "no_consensus")
    if result.time_ms <= 0 or result.matching_frames < 2:
        return OcrTriage("manual_review", "invalid_ocr_result")
    return OcrTriage(
        "approved", "nearby_frame_consensus", result.time_ms,
        result.confidence, result.evidence_frame,
        result.evidence_seconds_from_end,
    )
