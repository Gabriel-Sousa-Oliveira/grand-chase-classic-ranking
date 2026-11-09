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


class OcrDiagnosticsTests(unittest.TestCase):
    def test_reasons_require_positive_observations(self):
        from gc_radar.ocr import OcrDiagnostics
        diagnostic = OcrDiagnostics()
        self.assertEqual(diagnostic.reason(), 'diagnostic_unavailable')
        diagnostic.sampled_frames.add('frame-1')
        self.assertEqual(diagnostic.reason(), 'results_screen_not_found')
        diagnostic.panel_frames.add('frame-1')
        self.assertEqual(diagnostic.reason(), 'timer_not_found')
        diagnostic.read_frames.add('frame-1')
        diagnostic.values_ms.update([80000, 80450])
        self.assertEqual(diagnostic.reason(), 'insufficient_stable_frames')
        diagnostic.values_ms.add(92000)
        self.assertEqual(diagnostic.reason(), 'conflicting_reads')

    def test_download_and_other_errors_remain_distinguishable(self):
        from gc_radar.ocr import OcrDiagnostics
        diagnostic = OcrDiagnostics(stage='downloading')
        self.assertEqual(diagnostic.reason(TimeoutError()), 'download_error')
        diagnostic.stage = 'scanning'
        self.assertEqual(diagnostic.reason(TimeoutError()), 'technical_error')

    def test_workers_do_not_share_diagnostics(self):
        from concurrent.futures import ThreadPoolExecutor
        from gc_radar.ocr import collect_ocr_diagnostics, _diagnostics
        def inspect(index):
            with collect_ocr_diagnostics() as diagnostic:
                diagnostic.sampled_frames.add(str(index))
                self.assertIs(_diagnostics.get(), diagnostic)
                return diagnostic.payload()['ocr_diagnostics']['sampled_frames']
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(inspect, range(12))), [1] * 12)
        self.assertIsNone(_diagnostics.get())
