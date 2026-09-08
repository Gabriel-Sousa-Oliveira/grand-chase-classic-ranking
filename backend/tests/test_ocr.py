import unittest

from gc_radar.ocr import choose_consensus, extract_times


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


if __name__ == "__main__":
    unittest.main()
