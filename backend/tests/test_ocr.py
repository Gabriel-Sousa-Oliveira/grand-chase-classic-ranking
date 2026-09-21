import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gc_radar.ocr import (TIMER_ROIS, OcrObservation, _download_excerpt,
                          _parse_tesseract_tsv, _read_timer_frame,
                          choose_consensus,
                          choose_frozen_consensus,
                          extract_compact_time_values,
                          extract_result_time_values, extract_time_values,
                          extract_times, infer_chapter_time, read_video_time,
                          roi_bounds)


class OcrTextTests(unittest.TestCase):
    def test_infers_target_floor_from_consecutive_description_chapters(self):
        description = "0:00 1f\n2:09 2f\n2:39 3f\n3:54 4f\n4:57 Stats"
        result = infer_chapter_time(description, 4)
        self.assertIsNotNone(result)
        self.assertEqual(result.time_ms, 63_000)
        self.assertEqual(result.source, "youtube-description-chapters")

    def test_chapter_inference_rejects_ambiguous_or_unordered_markers(self):
        self.assertIsNone(infer_chapter_time("0:00 4f\n1:03 Stats", 4))
        self.assertIsNone(infer_chapter_time(
            "0:00 1f\n2:00 4f\n1:30 Stats", 4
        ))

    def test_extracts_common_timer_formats(self):
        self.assertEqual(extract_times("CLEAR TIME 01:32"), {92})
        self.assertEqual(extract_times("Tempo 2'56"), {176})
        self.assertEqual(extract_times("3m 07s"), {187})

    def test_extracts_gc_fractional_timer_formats(self):
        self.assertEqual(extract_time_values("CLEAR 01:23:45"), {83_450})
        self.assertEqual(extract_time_values("TIME 01:23.456"), {83_456})

    def test_parses_clear_time_result_notation_contextually(self):
        self.assertEqual(extract_result_time_values("48'4"), {48_400})
        self.assertEqual(extract_result_time_values("1'23\"45"), {83_450})
        self.assertEqual(extract_result_time_values("48:4."), {48_400})
        self.assertEqual(extract_result_time_values("4845"), {48_450})
        self.assertEqual(extract_result_time_values("14845"), {108_450})
        self.assertEqual(extract_result_time_values("Time 48'4"), set())

    def test_recovers_separator_free_segmented_timers(self):
        self.assertEqual(extract_compact_time_values("012345"), {83_450})
        self.assertEqual(extract_compact_time_values("0123456"), {83_456})
        self.assertEqual(extract_compact_time_values("0132"), {92_000})

    def test_rejects_ambiguous_compact_numbers(self):
        self.assertEqual(extract_compact_time_values("123"), set())
        self.assertEqual(extract_compact_time_values("016099"), set())
        self.assertEqual(extract_compact_time_values("score 012345"), set())

    def test_repairs_common_ocr_characters(self):
        self.assertEqual(extract_times("O1:3I"), {91})

    def test_rejects_invalid_or_implausible_times(self):
        self.assertEqual(extract_times("12:99 00:04 21:00"), set())

    def test_requires_two_distinct_frames(self):
        self.assertIsNone(choose_consensus([("001", 92), ("001", 92)]))
        result = choose_consensus([("001", 92), ("002", 92), ("002", 92)])
        self.assertIsNotNone(result)
        self.assertEqual(result.time_ms, 92000)

    def test_rejects_tied_consensus(self):
        self.assertIsNone(choose_consensus([
            ("001", 92), ("002", 92), ("003", 78), ("004", 78),
        ]))

    def test_requires_consensus_frames_to_be_nearby(self):
        self.assertIsNone(choose_consensus([("001", 92), ("009", 92)]))

    def test_consensus_preserves_best_evidence_frame(self):
        result = choose_consensus([("010", 92), ("011", 92), ("011", 92)])
        self.assertEqual(result.evidence_frame, "frame-011")
        self.assertEqual(result.evidence_seconds_from_end, 15)

    def test_relative_timer_roi_reduces_area_by_more_than_ninety_percent(self):
        self.assertEqual(
            set(TIMER_ROIS),
            {"top_center_timer", "top_center_timer_wide", "results_panel"},
        )
        for relative in TIMER_ROIS.values():
            left, top, right, bottom = roi_bounds(1920, 1080, relative)
            area_ratio = ((right - left) * (bottom - top)) / (1920 * 1080)
            self.assertLess(area_ratio, 0.04)

    def test_accepts_fractional_ocr_jitter_inside_a_frozen_second(self):
        observations = [
            OcrObservation(f"top_right-coarse-{index:04d}", time_ms,
                           float(index), 0.82, f"frame-{index}.png")
            for index, time_ms in enumerate((83_420, 83_450, 83_460))
        ]
        result = choose_frozen_consensus(observations, 1.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.time_ms, 83_450)
        self.assertLessEqual(result.confidence, 0.86)

    def test_accepts_a_timer_frozen_for_two_seconds(self):
        observations = [
            OcrObservation(f"top_center-coarse-{index:04d}", 83_450,
                           float(index), 0.90, f"frame-{index}.png")
            for index in range(3)
        ]
        result = choose_frozen_consensus(observations, 1.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.time_ms, 83_450)
        self.assertEqual(result.matching_frames, 3)

    def test_rejects_a_normally_ticking_timer_and_conflicts(self):
        ticking = [
            OcrObservation(str(index), 80_000 + index * 1000,
                           float(index), 0.90, f"frame-{index}.png")
            for index in range(5)
        ]
        self.assertIsNone(choose_frozen_consensus(ticking, 1.0))
        conflict = [
            OcrObservation(f"a-{index}", 83_000, float(index), 0.9, "a.png")
            for index in range(3)
        ] + [
            OcrObservation(f"b-{index}", 91_000, float(index + 5), 0.9, "b.png")
            for index in range(3)
        ]
        self.assertIsNone(choose_frozen_consensus(conflict, 1.0))

    def test_reads_text_and_real_confidence_from_tesseract_tsv(self):
        tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
               "left\ttop\twidth\theight\tconf\ttext\n"
               "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t90\t01:23:45\n")
        text, confidence = _parse_tesseract_tsv(tsv)
        self.assertEqual(text, "01:23:45")
        self.assertAlmostEqual(confidence, 0.9)

    def test_timer_ocr_uses_the_restricted_vocabulary(self):
        tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
               "left\ttop\twidth\theight\tconf\ttext\n"
               "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t95\t01:23:45\n")
        with tempfile.TemporaryDirectory() as temporary, \
                patch("gc_radar.ocr._preprocess_roi") as preprocess, \
                patch("gc_radar.ocr._run") as run:
            processed = Path(temporary) / "timer.png"
            preprocess.return_value = [processed]
            run.return_value = SimpleNamespace(stdout=tsv)
            observations = _read_timer_frame(
                Path(temporary) / "frame.png", Path(temporary),
                "top_center", 3.0,
            )
            command = run.call_args.args[0]
            self.assertIn("tessedit_char_whitelist=0123456789:.", command)
            self.assertEqual(observations[0].time_ms, 83_450)
            self.assertAlmostEqual(observations[0].confidence, 0.95)

    def test_results_panel_rejects_compact_inventory_icon_numbers(self):
        tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
               "left\ttop\twidth\theight\tconf\ttext\n"
               "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t95\t2383\n")
        with tempfile.TemporaryDirectory() as temporary, \
                patch("gc_radar.ocr._preprocess_roi") as preprocess, \
                patch("gc_radar.ocr._run") as run:
            processed = Path(temporary) / "frame-results_panel-digits.png"
            preprocess.return_value = [processed]
            run.return_value = SimpleNamespace(stdout=tsv)
            observations = _read_timer_frame(
                Path(temporary) / "frame.png", Path(temporary),
                "results_panel", 3.0,
            )
            self.assertEqual(observations, [])

    def test_results_panel_keeps_compact_mmss_from_digit_band(self):
        tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
               "left\ttop\twidth\theight\tconf\ttext\n"
               "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t95\t0126\n")
        with tempfile.TemporaryDirectory() as temporary, \
                patch("gc_radar.ocr._preprocess_roi") as preprocess, \
                patch("gc_radar.ocr._run") as run:
            processed = Path(temporary) / "frame-results_panel-digits.png"
            preprocess.return_value = [processed]
            run.return_value = SimpleNamespace(stdout=tsv)
            observations = _read_timer_frame(
                Path(temporary) / "frame.png", Path(temporary),
                "results_panel", 3.0,
            )
            self.assertEqual([item.time_ms for item in observations], [86_000])

    def test_empty_tesseract_component_is_not_a_video_error(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch("gc_radar.ocr._preprocess_roi") as preprocess, \
                patch("gc_radar.ocr._run") as run:
            preprocess.return_value = [Path(temporary) / "timer.png"]
            run.side_effect = RuntimeError(
                "Image too small to scale!!\nLine cannot be recognized!!"
            )
            observations = _read_timer_frame(
                Path(temporary) / "frame.png", Path(temporary),
                "top_right_wide", 3.0,
            )
            self.assertEqual(observations, [])

    def test_skips_dense_scan_when_coarse_rois_have_no_timer_sightings(self):
        with patch("gc_radar.ocr._require_tools"), \
                patch("gc_radar.ocr._download_excerpt") as download, \
                patch("gc_radar.ocr._extract_frames") as extract, \
                patch("gc_radar.ocr._scan_frames") as scan, \
                patch("gc_radar.ocr._preserve_diagnostic"):
            download.return_value = Path("video.mp4")
            extract.return_value = [Path("coarse-0001.png")]
            scan.side_effect = [(None, 0)] * len(TIMER_ROIS)
            self.assertIsNone(read_video_time("https://youtu.be/example"))
            self.assertEqual(extract.call_count, 1)

    def test_anonymous_po_token_uses_mweb_client(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {"YOUTUBE_USE_PO_TOKEN": "1"}, clear=True), \
                patch("gc_radar.ocr._run") as run:
            video = Path(temporary) / "video.mp4"
            video.touch()
            self.assertEqual(_download_excerpt("https://youtu.be/example", Path(temporary)), video)
            command = run.call_args.args[0]
            self.assertIn("youtube:player_client=mweb", command)
            self.assertNotIn("--cookies", command)

    def test_download_accepts_combined_video_formats(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {}, clear=True), \
                patch("gc_radar.ocr._run") as run:
            video = Path(temporary) / "video.mp4"
            video.touch()
            _download_excerpt("https://youtu.be/example", Path(temporary))
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("-f") + 1], "bv*")
            self.assertEqual(command[command.index("-S") + 1], "res:720,+size,+br")
            self.assertEqual(command[command.index("--download-sections") + 1], "*-120-inf")

    def test_browser_po_token_uses_configured_chrome(self):
        environment = {
            "YOUTUBE_USE_PO_TOKEN": "1",
            "YOUTUBE_PO_BROWSER_PATH": "/usr/bin/google-chrome",
        }
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, environment, clear=True), \
                patch("gc_radar.ocr._run") as run:
            video = Path(temporary) / "video.mp4"
            video.touch()
            _download_excerpt("https://youtu.be/example", Path(temporary))
            command = run.call_args.args[0]
            self.assertIn("youtubepot-wpc:browser_path=/usr/bin/google-chrome", command)


if __name__ == "__main__":
    unittest.main()
