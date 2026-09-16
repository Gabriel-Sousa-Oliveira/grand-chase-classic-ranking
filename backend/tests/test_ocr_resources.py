import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from gc_radar.ocr import _run, _scan_frames, _deadline, read_video_time


class ResourceTests(unittest.TestCase):
    def test_subprocess_limits_nested_threads_without_mutating_parent(self):
        with patch.dict(os.environ, {"OMP_THREAD_LIMIT": "8"}), patch("gc_radar.ocr.subprocess.run") as run:
            _run(["tesseract", "image", "stdout"])
            self.assertEqual(run.call_args.kwargs["env"]["OMP_THREAD_LIMIT"], "1")
            self.assertEqual(os.environ["OMP_THREAD_LIMIT"], "8")

    def test_deadline_caps_subprocess_timeout(self):
        with patch("gc_radar.ocr.time.monotonic", return_value=100), patch("gc_radar.ocr.subprocess.run") as run:
            token = _deadline.set(107)
            try:
                _run(["tesseract"], timeout=20)
                self.assertEqual(run.call_args.kwargs["timeout"], 7)
            finally:
                _deadline.reset(token)

    def test_expired_budget_does_not_spawn(self):
        token = _deadline.set(0)
        try:
            with patch("gc_radar.ocr.subprocess.run") as run:
                with self.assertRaisesRegex(RuntimeError, "budget_exhausted"):
                    _run(["tesseract"])
                run.assert_not_called()
        finally:
            _deadline.reset(token)

    def test_deadline_reset_after_failure(self):
        with patch("gc_radar.ocr._read_video_time", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                read_video_time("test")
        self.assertIsNone(_deadline.get())

    def test_repeated_timeout_is_bounded_and_retryable(self):
        with patch("gc_radar.ocr._read_timer_frame", side_effect=subprocess.TimeoutExpired("tesseract", 20)) as read:
            with self.assertRaisesRegex(RuntimeError, "repeated_timeout"):
                _scan_frames([Path(str(i)) for i in range(10)], Path("."), "test", 10, 1)
            self.assertEqual(read.call_count, 3)

    def test_one_timeout_continues_but_does_not_become_no_consensus(self):
        with patch("gc_radar.ocr._read_timer_frame", side_effect=[subprocess.TimeoutExpired("tesseract", 20), []]) as read:
            with self.assertRaisesRegex(RuntimeError, "incomplete_scan"):
                _scan_frames([Path("a"), Path("b")], Path("."), "test", 2, 1)
            self.assertEqual(read.call_count, 2)
