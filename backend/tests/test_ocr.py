import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gc_radar.ocr import (OCR_ACCEPT_ROIS, TIMER_ROIS, OcrObservation, _download_excerpt,
                          _parse_tesseract_tsv, _read_timer_frame, _preprocess_roi,
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
        self.assertEqual(extract_result_time_values("01'20"), {80_000})
        self.assertEqual(extract_result_time_values("01'02"), {62_000})
        self.assertEqual(extract_result_time_values("03'04"), {184_000})
        self.assertEqual(extract_result_time_values("48:4."), {48_400})
        self.assertEqual(extract_result_time_values("4845"), {48_450})
        self.assertEqual(extract_result_time_values("14845"), {108_450})
        self.assertEqual(extract_result_time_values("Time 48'4"), set())

    def test_recovers_separator_free_segmented_timers(self):
        self.assertEqual(extract_compact_time_values("012345"), {83_450})
        self.assertEqual(extract_compact_time_values("0123456"), {83_456})
        self.assertEqual(extract_compact_time_values("0132"), {92_000})

    def test_results_parser_handles_duplicate_minute_separator_from_real_replay(self):
        self.assertEqual(extract_result_time_values("01:'20"), {80_000})
        self.assertEqual(extract_result_time_values("03:'04"), {184_000})
        # Do not turn arbitrary repeated punctuation or incomplete digits
        # into durations, and do not broaden the general timer parser.
        for text in ("01::20", "01:'2", "Time 01:'20", "01:'99"):
            self.assertEqual(extract_result_time_values(text), set())
        self.assertEqual(extract_time_values("01:'20"), set())

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

    def test_only_clear_time_panel_can_produce_auto_time(self):
        self.assertEqual(OCR_ACCEPT_ROIS, ("results_panel",))
        self.assertNotIn("top_center_timer", OCR_ACCEPT_ROIS)

    def test_relative_timer_roi_reduces_area_by_more_than_ninety_percent(self):
        self.assertEqual(
            set(TIMER_ROIS),
            {"top_center_timer", "top_center_timer_wide", "results_panel"},
        )
        for relative in TIMER_ROIS.values():
            left, top, right, bottom = roi_bounds(1920, 1080, relative)
            area_ratio = ((right - left) * (bottom - top)) / (1920 * 1080)
            self.assertLess(area_ratio, 0.04)

    def test_results_panel_roi_covers_clear_time_without_best_time_row(self):
        _, _, _, bottom = roi_bounds(1536, 710, TIMER_ROIS["results_panel"])
        self.assertGreater(bottom, round(0.39 * 710))
        self.assertLess(bottom, round(0.41 * 710))

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

    def test_hinted_results_consensus_accepts_four_repeat_reads_in_075_seconds(self):
        # Both preserved hints have a stable results timer for less than the
        # generic gameplay requirement of 1.8 seconds.
        observations = [
            OcrObservation(f"results_panel-frame-{index:04d}", 80_000,
                           index * .25, .9, f"frame-{index}.png")
            for index in range(6)
        ]
        self.assertIsNone(choose_frozen_consensus(observations, .25))
        result = choose_frozen_consensus(
            observations, .25, minimum_span_override=.75, minimum_frames=4
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.time_ms, 80_000)
        self.assertEqual(result.matching_frames, 6)
        self.assertIsNone(choose_frozen_consensus(
            observations[:3], .25, minimum_span_override=.75, minimum_frames=4
        ))

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

    def test_results_panel_recovers_compact_gold_digits_in_both_scan_modes(self):
        # Gold isolation returns only this variant. No fallback image exists
        # when the small apostrophe disappears during preprocessing.
        for exhaustive in (False, True):
            for text, expected in (("0120", 80_000), ("0304", 184_000),
                                   ("0603", 363_000), ("2383", None)):
                with self.subTest(exhaustive=exhaustive, text=text), \
                        tempfile.TemporaryDirectory() as temporary, \
                        patch("gc_radar.ocr._preprocess_roi") as preprocess, \
                        patch("gc_radar.ocr._run") as run:
                    directory = Path(temporary)
                    preprocess.return_value = [
                        directory / "frame-results_panel-yellow-digits.png"
                    ]
                    run.return_value = SimpleNamespace(stdout=(
                        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                        "left\ttop\twidth\theight\tconf\ttext\n"
                        f"5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t95\t{text}\n"
                    ))
                    observations = _read_timer_frame(
                        directory / "frame.png", directory, "results_panel",
                        3.0, exhaustive=exhaustive,
                    )
                    self.assertEqual(
                        [item.time_ms for item in observations],
                        [] if expected is None else [expected],
                    )

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

    def test_download_can_target_a_short_video_timestamp_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {}, clear=True), patch("gc_radar.ocr._run") as run:
                video = Path(temporary) / "video.mp4"
                video.touch()
                _download_excerpt("https://youtu.be/example", Path(temporary), at_seconds=205)
                command = run.call_args.args[0]
                self.assertEqual(
                    command[command.index("--download-sections") + 1],
                    "*195.000-220.000",
                )

    def test_manual_hint_runs_dense_scan_even_without_coarse_sightings(self):
        from gc_radar.ocr import _read_event_video, OcrResult
        expected = OcrResult(80_000, .9, 8, 8)
        with tempfile.TemporaryDirectory() as temporary, \
                patch("gc_radar.ocr._download_excerpt", return_value=Path("video.mp4")), \
                patch("gc_radar.ocr.scout_video", return_value=([], 25.0)), \
                patch("gc_radar.ocr._window_frames", return_value=[]) as frames, \
                patch("gc_radar.ocr._scan_frames", side_effect=[(None, 0), (expected, 8)]) as scan, \
                patch("gc_radar.ocr._preserve_evidence", return_value=expected):
            result = _read_event_video("test", Path(temporary), None, "test", 90)
        self.assertEqual(result.time_ms, 80_000)
        self.assertEqual(frames.call_args.args[-1], 4)
        self.assertTrue(scan.call_args.kwargs["exhaustive"])

    def test_gold_crop_excludes_time_label_and_keeps_rightmost_digit(self):
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = np.zeros((720, 1280, 3), dtype=np.uint8)
            cv2.putText(image, "Time", (1020, 270), cv2.FONT_HERSHEY_SIMPLEX,
                        .5, (220, 220, 180), 1)
            for x in (1130, 1165, 1210, 1250):
                cv2.rectangle(image, (x, 250), (x + 12, 275), (0, 220, 255), -1)
            frame = directory / "frame.png"
            cv2.imwrite(str(frame), image)
            with patch("gc_radar.ocr._has_results_panel", return_value=True):
                outputs = _preprocess_roi(frame, directory, "results_panel")
            self.assertEqual(len(outputs), 1)
            self.assertTrue(outputs[0].stem.endswith("-yellow-digits"))
            pixels = cv2.imread(str(outputs[0]), cv2.IMREAD_GRAYSCALE)
            # The old crop ended at x=1242 and cut the last digit.
            self.assertEqual(roi_bounds(1280, 720, TIMER_ROIS["results_panel"])[2], 1280)
            self.assertTrue((pixels[:, -100:] < 100).any())
            # The cyan label occupies the left part of the ROI.
            self.assertTrue((pixels[:, :300] == 255).all())

    def test_results_panel_requires_heading_and_time_label(self):
        import numpy as np
        from gc_radar.ocr import _has_results_panel
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as temporary:
            for text, expected in [
                ("Results\nClear Time\nTime 01 20\nBest Time", True),
                ("Results\nBest Time", True),
                ("Inventory 22:10", False),
                ("Clear Time 01:20", False),
                ("Results 01:20", False),
                ("", False),
            ]:
                with self.subTest(text=text), patch("gc_radar.ocr._run",
                        return_value=SimpleNamespace(stdout=text)):
                    self.assertEqual(_has_results_panel(
                        image, Path(temporary), "frame"), expected)

    def test_results_heading_retry_still_requires_both_labels(self):
        import numpy as np
        from gc_radar.ocr import _has_results_panel
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as temporary:
            for heading, expected in (("Results", True), ("Inventory", False),
                                      ("", False), ("Results inventory", False)):
                with self.subTest(heading=heading), patch("gc_radar.ocr._run",
                        side_effect=[SimpleNamespace(stdout="Clear Time"),
                                     SimpleNamespace(stdout=heading)]) as run:
                    self.assertEqual(_has_results_panel(
                        image, Path(temporary), "frame"), expected)
                    self.assertEqual(run.call_count, 2)

    def test_inventory_is_rejected_before_any_timer_ocr(self):
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            frame = directory / "inventory.png"
            cv2.imwrite(str(frame), np.zeros((720, 1280, 3), dtype=np.uint8))
            with patch("gc_radar.ocr._run",
                       return_value=SimpleNamespace(stdout="Inventory 22:10")) as run:
                self.assertEqual(_read_timer_frame(
                    frame, directory, "results_panel", 0, exhaustive=True), [])
                self.assertEqual(run.call_count, 1)
                self.assertNotIn("tsv", run.call_args.args[0])

    def test_hinted_excerpt_is_preserved_for_offline_replay(self):
        import json
        from gc_radar.ocr import _preserve_hinted_excerpt
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "video.mp4"
            video.write_bytes(b"public video excerpt")
            output = root / "evidence"
            _preserve_hinted_excerpt(video, output, "DDzlbGAOo2I", 90)
            self.assertEqual((output / "DDzlbGAOo2I-excerpt.mp4").read_bytes(),
                             video.read_bytes())
            metadata = json.loads((output / "DDzlbGAOo2I-excerpt.json").read_text())
            self.assertEqual(metadata["requested_start_seconds"], 80)
            self.assertEqual(metadata["requested_end_seconds"], 105)
            self.assertEqual(metadata["status"], "saved")

    def test_non_hinted_queue_does_not_copy_video_evidence(self):
        from gc_radar.ocr import _preserve_hinted_excerpt
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            _preserve_hinted_excerpt(Path("not-downloaded.mp4"), output, "test", None)
            self.assertFalse(output.exists())

    def test_oversized_excerpt_is_reported_without_copying(self):
        import json
        from gc_radar.ocr import _preserve_hinted_excerpt
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "video.mp4"
            with video.open("wb") as stream:
                stream.truncate(50 * 1024 * 1024 + 1)
            output = root / "evidence"
            _preserve_hinted_excerpt(video, output, "test", 5)
            metadata = json.loads((output / "test-excerpt.json").read_text())
            self.assertEqual(metadata["status"], "size_limit_exceeded")
            self.assertEqual(metadata["requested_start_seconds"], 0)
            self.assertFalse((output / "test-excerpt.mp4").exists())

    def test_timestamp_hint_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                _download_excerpt("https://youtu.be/example", Path(temporary), at_seconds=-1)

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

