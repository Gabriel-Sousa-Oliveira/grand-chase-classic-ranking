import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gc_radar.ocr import _download_excerpt, choose_consensus, extract_times


class OcrTextTests(unittest.TestCase):
    def test_extracts_common_timer_formats(self):
        self.assertEqual(extract_times("CLEAR TIME 01:32"), {92})
        self.assertEqual(extract_times("Tempo 2'56"), {176})
        self.assertEqual(extract_times("3m 07s"), {187})

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
            self.assertEqual(command[command.index("-S") + 1], "+res:360,+size,+br")
            self.assertEqual(command[command.index("--download-sections") + 1], "*-75-inf")

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
