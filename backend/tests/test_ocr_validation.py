import argparse
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gc_radar.ocr_validation import (ValidationCase, parse_case,
                                     parse_time_hint, summarize, validate_case)


class OcrValidationTests(unittest.TestCase):
    def test_parses_manual_video_timestamp_hints(self):
        self.assertEqual(parse_time_hint("video=205"), ("video", 205.0))
        self.assertEqual(parse_time_hint("video=90.5"), ("video", 90.5))
        for value in ("invalid", "video=-1", "video=nan"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                parse_time_hint(value)

    def test_parses_validation_case(self):
        self.assertEqual(parse_case("video=48450"), ValidationCase("video", 48_450))
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_case("invalid")

    @patch("gc_radar.ocr_validation.read_video_time")
    def test_accepts_detection_inside_tolerance(self, read_video_time):
        read_video_time.return_value = SimpleNamespace(
            time_ms=48_450, confidence=0.82, matching_frames=3,
            observations=3, source="tesseract+opencv", roi="results_panel",
            evidence_image="evidence.png",
        )
        result = validate_case(
            ValidationCase("video", 48_000), Path("evidence"), 1_500
        )
        self.assertEqual(result["status"], "matched_expected")
        self.assertEqual(result["delta_ms"], 450)

    @patch("gc_radar.ocr_validation.read_video_time")
    def test_validation_passes_timestamp_hint_to_ocr(self, read_video_time):
        read_video_time.return_value = SimpleNamespace(
            time_ms=80_000, confidence=0.9, matching_frames=2,
            observations=2, source="tesseract+opencv", roi="results_panel",
            evidence_image="evidence.png",
        )
        result = validate_case(
            ValidationCase("video", 80_000), Path("evidence"), 1_500,
            time_hint_seconds=90.0,
        )
        self.assertEqual(result["status"], "matched_expected")
        self.assertEqual(result["video_time_hint_seconds"], 90.0)
        read_video_time.assert_called_once_with(
            "https://www.youtube.com/watch?v=video", Path("evidence"), "video",
            at_seconds=90.0,
        )

    def test_summary_fails_on_mismatch_or_missing_consensus(self):
        report = summarize([
            {"status": "matched_expected"},
            {"status": "mismatched"},
            {"status": "no_consensus"},
        ], 1_500)
        self.assertFalse(report["passed"])
        self.assertEqual(report["pass_rate"], 1 / 3)
        self.assertEqual(report["candidates"], [])


if __name__ == "__main__":
    unittest.main()
