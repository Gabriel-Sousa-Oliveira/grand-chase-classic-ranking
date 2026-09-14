import unittest

from gc_radar.ocr import OcrResult, choose_consensus
from gc_radar.video_pipeline import triage_ocr_result


class OcrTriageTests(unittest.TestCase):
    def test_known_twenty_video_benchmark_is_fully_explained(self):
        cases = []
        for index in range(10):
            seconds = 60 + index
            cases.append(choose_consensus([
                ("010", seconds), ("011", seconds), ("011", seconds)
            ]))
        cases.extend([None] * 5)
        cases.extend([
            choose_consensus([("001", 80 + index), ("002", 80 + index),
                              ("003", 90 + index), ("004", 90 + index)])
            for index in range(5)
        ])
        decisions = [triage_ocr_result(result) for result in cases]
        self.assertEqual(len(decisions), 20)
        self.assertEqual(sum(d.destination == "approved" for d in decisions), 10)
        self.assertEqual(sum(d.destination == "manual_review" for d in decisions), 10)
        self.assertTrue(all(d.processing_reason in {
            "nearby_frame_consensus", "no_consensus"
        } for d in decisions))
        self.assertTrue(all(d.ocr_time_ms is not None and d.evidence_frame
                            for d in decisions[:10]))

    def test_invalid_and_irrelevant_results_have_explicit_destinations(self):
        invalid = OcrResult(-1, 0.9, 2, 2)
        self.assertEqual(triage_ocr_result(invalid).processing_reason,
                         "invalid_ocr_result")
        self.assertEqual(triage_ocr_result(None, irrelevant=True).destination,
                         "rejected")
        self.assertEqual(triage_ocr_result(None, RuntimeError("download")).processing_reason,
                         "technical_error")


if __name__ == "__main__":
    unittest.main()
