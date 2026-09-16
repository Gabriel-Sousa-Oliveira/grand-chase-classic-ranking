import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from gc_radar.visual import Anchor, Sample, load_anchors, locate_anchor, propose_windows, write_inspection
from gc_radar.ocr import _download_excerpt, _read_event_video, _anchors
from gc_radar.inspect_frames import survey


class VisualTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.template = np.random.default_rng(12).integers(0, 255, (20, 30), dtype=np.uint8)
        self.anchor = Anchor("clear", self.template, (0, 25, 40, 15), (1.0,), 0.95)

    def test_anchor_uses_relative_timer_offset(self):
        image = np.zeros((160, 240), dtype=np.uint8)
        image[40:60, 50:80] = self.template
        result = locate_anchor(image, self.anchor)
        self.assertEqual(result["roi"], (50, 65, 90, 80))

    def test_anchor_rejects_duplicate_and_out_of_frame(self):
        image = np.zeros((160, 240), dtype=np.uint8)
        image[40:60, 50:80] = self.template
        image[40:60, 150:180] = self.template
        self.assertIsNone(locate_anchor(image, self.anchor))
        image[:] = 0
        image[140:160, 50:80] = self.template
        self.assertIsNone(locate_anchor(image, self.anchor))

    def test_anchor_scaled_offset(self):
        image = np.zeros((240, 320), dtype=np.uint8)
        image[40:70, 50:95] = cv2.resize(self.template, None, fx=1.5, fy=1.5)
        anchor = Anchor("clear", self.template, (0, 25, 40, 15), (1.5,), 0.95)
        self.assertEqual(locate_anchor(image, anchor)["roi"], (50, 78, 110, 100))

    def samples(self, colors):
        frames = []
        for i, color in enumerate(colors):
            path = self.directory / f"frame-{i}.png"
            cv2.imwrite(str(path), np.full((90, 160, 3), color, dtype=np.uint8))
            frames.append(Sample(path, i*5))
        return frames

    def test_flash_is_not_stable_transition(self):
        self.assertEqual(propose_windows(self.samples([0, 255, 0, 0]), [], 20), [])

    def test_stable_transition_proposes_not_proves_victory(self):
        windows = propose_windows(self.samples([0, 0, 255, 255, 255]), [], 25)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["reason"], "scene_change")
        self.assertEqual(windows[0]["anchors"], [])
        self.assertGreaterEqual(windows[0]["start"], 0)
        self.assertLessEqual(windows[0]["end"], 25)

    def test_disabled_anchor_requires_no_image(self):
        path = self.directory / "anchors.json"
        path.write_text(json.dumps({"anchors": [{"enabled": False}]}))
        self.assertEqual(load_anchors(path), [])

    def test_flat_template_rejected(self):
        cv2.imwrite(str(self.directory / "flat.png"), np.zeros((20, 20), dtype=np.uint8))
        path = self.directory / "anchors.json"
        path.write_text(json.dumps({"anchors": [{"enabled": True, "name": "flat", "image": "flat.png"}]}))
        with self.assertRaises(ValueError):
            load_anchors(path)

    def test_grid_outputs_full_resolution_and_coordinates(self):
        samples = self.samples([20, 100, 200])
        manifest = write_inspection(samples, self.directory / "out", "video", [])
        data = json.loads(manifest.read_text())
        self.assertEqual(len(data["frames"]), 3)
        image = cv2.imread(str(manifest.parent / data["frames"][0]["image"]))
        self.assertEqual(image.shape[:2], (90, 160))
        self.assertTrue((manifest.parent / "video-mosaic.jpg").exists())
        self.assertTrue((manifest.parent / data["frames"][0]["raw_image"]).exists())

    def test_survey_25_videos_does_not_call_ocr(self):
        samples = self.samples([0, 0, 255, 255, 255])
        with patch("gc_radar.inspect_frames.scout_video", return_value=(samples, 25)), \
             patch("gc_radar.ocr._read_timer_frame") as ocr:
            report = survey([Path(f"video{i}.mp4") for i in range(25)], self.directory / "survey")
        self.assertEqual(len(report["videos"]), 25)
        self.assertTrue(all("error" not in v for v in report["videos"]))
        ocr.assert_not_called()
        self.assertEqual(cv2.imread(str(self.directory / "survey/survey-mosaic.jpg")).shape[:2], (1350, 2400))

    def test_window_limit_and_no_overlap(self):
        samples = self.samples([0]*3 + [64]*6 + [128]*6 + [192]*6 + [255]*6)
        windows = propose_windows(samples, [], 135)
        self.assertLessEqual(len(windows), 3)
        for a, b in zip(windows, windows[1:]):
            self.assertLessEqual(a["end"], b["start"])

    def test_download_window_bounded(self):
        with self.assertRaises(ValueError):
            _download_excerpt("test", self.directory, 10000)
        (self.directory / "video.mp4").touch()
        with patch("gc_radar.ocr._run") as run:
            _download_excerpt("test", self.directory, 300)
        self.assertIn("*-300-inf", run.call_args.args[0])

    def test_events_without_sightings_do_not_trigger_dense_ocr(self):
        samples = self.samples([0, 0, 255, 255, 255])
        with patch("gc_radar.ocr._download_excerpt", return_value=Path("video.mp4")), \
             patch("gc_radar.ocr.scout_video", return_value=(samples, 25)), \
             patch("gc_radar.ocr._window_frames", return_value=[samples[0].path]) as frames, \
             patch("gc_radar.ocr._scan_frames", return_value=(None, 0)):
            result = _read_event_video("test", self.directory, self.directory / "out", "video")
            self.assertIsNone(result)
            self.assertEqual(frames.call_count, 1)
            self.assertEqual(_anchors.get(), {})


if __name__ == "__main__":
    unittest.main()
