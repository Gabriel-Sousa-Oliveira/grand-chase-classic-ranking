"""Empirical OCR validation against runs with independently known times."""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .ocr import read_video_time


@dataclass(frozen=True)
class ValidationCase:
    video_id: str
    expected_ms: int

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


def parse_case(value: str) -> ValidationCase:
    try:
        video_id, expected = value.rsplit("=", 1)
        expected_ms = int(expected)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError(
            "case must use VIDEO_ID=EXPECTED_MS"
        ) from error
    if not video_id.strip() or expected_ms <= 0:
        raise argparse.ArgumentTypeError(
            "case must use a non-empty video id and positive milliseconds"
        )
    return ValidationCase(video_id.strip(), expected_ms)


def validate_case(case: ValidationCase, evidence_dir: Path,
                  tolerance_ms: int) -> dict:
    try:
        result = read_video_time(case.url, evidence_dir, case.video_id)
    except Exception as error:
        return {
            "video_id": case.video_id,
            "expected_ms": case.expected_ms,
            "status": "error",
            "error_type": type(error).__name__,
            "error": str(error)[:500],
        }
    if result is None:
        return {
            "video_id": case.video_id,
            "expected_ms": case.expected_ms,
            "status": "no_consensus",
        }
    delta_ms = result.time_ms - case.expected_ms
    return {
        "video_id": case.video_id,
        "expected_ms": case.expected_ms,
        "detected_ms": result.time_ms,
        "delta_ms": delta_ms,
        "status": (
            "matched_expected" if abs(delta_ms) <= tolerance_ms
            else "mismatched"
        ),
        "confidence": result.confidence,
        "matching_frames": result.matching_frames,
        "observations": result.observations,
        "source": result.source,
        "roi": result.roi,
        "evidence_image": result.evidence_image,
    }


def summarize(results: list[dict], tolerance_ms: int) -> dict:
    counts = {
        status: sum(result["status"] == status for result in results)
        for status in ("matched_expected", "mismatched", "no_consensus", "error")
    }
    total = len(results)
    return {
        "mode": "ocr-validation",
        "tolerance_ms": tolerance_ms,
        "cases": total,
        **counts,
        "pass_rate": counts["matched_expected"] / total if total else 0.0,
        "passed": total > 0 and counts["matched_expected"] == total,
        "results": results,
        # Keep the validation report compatible with the workflow summary while
        # ensuring it cannot modify the hosted review queue.
        "candidates": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="gc-ocr-validation")
    parser.add_argument("--case", action="append", type=parse_case,
                        dest="cases", required=True)
    parser.add_argument("--tolerance-ms", type=int, default=1_500)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--evidence-dir", type=Path,
                        default=Path("../data/ocr-evidence"))
    args = parser.parse_args()
    if args.tolerance_ms < 0:
        parser.error("--tolerance-ms must be non-negative")
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(args.workers, 4, len(args.cases)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(
            lambda case: validate_case(case, args.evidence_dir,
                                       args.tolerance_ms),
            args.cases,
        ))
    print(json.dumps(summarize(results, args.tolerance_ms),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
