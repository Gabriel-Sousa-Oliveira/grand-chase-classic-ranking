import json
import sqlite3
import unittest
from pathlib import Path

from gc_radar.ocr_queue import pending_ocr_videos


class OcrQueueTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE candidates (video_id TEXT, category TEXT, '
                        'time_ms INTEGER, status TEXT, raw_metadata TEXT)')

    def add(self, video_id, category='large', metadata=None, time=None,
            status='time_required'):
        self.db.execute('INSERT INTO candidates VALUES (?, ?, ?, ?, ?)',
                        (video_id, category, time, status, json.dumps(metadata or {})))

    def ids(self):
        return [video for video, _ in pending_ocr_videos(self.db, ['large', 'small'])]

    def test_new_videos_in_smaller_category_precede_all_retries(self):
        self.add('a-retry', metadata={'ocr_attempts': 1, 'ocr_outcome': 'error'})
        self.add('b-retry', metadata={'ocr_attempts': 2, 'ocr_outcome': 'no_consensus'})
        self.add('z-new', 'small')
        self.assertEqual(self.ids()[:1], ['z-new'])

    def test_retry_rotation_uses_count_then_oldest_attempt_not_updated_at(self):
        self.add('many', metadata={'ocr_attempts': 3, 'ocr_attempted_at': '2026-01-01'})
        self.add('recent', metadata={'ocr_attempts': 1, 'ocr_attempted_at': '2026-10-28'})
        self.add('old', metadata={'ocr_attempts': 1, 'ocr_attempted_at': '2026-10-01'})
        self.assertEqual(self.ids(), ['old', 'recent', 'many'])
        self.db.execute("UPDATE candidates SET raw_metadata = ? WHERE video_id = 'old'",
                        (json.dumps({'ocr_attempts': 2, 'ocr_attempted_at': '2026-10-28'}),))
        self.assertEqual(self.ids(), ['recent', 'old', 'many'])

    def test_legacy_outcome_or_timestamp_counts_as_attempt(self):
        self.add('a-outcome', metadata={'ocr_outcome': 'no_consensus'})
        self.add('b-timestamp', metadata={'ocr_attempted_at': '2026-01-01'})
        self.add('z-new')
        self.assertEqual(self.ids(), ['z-new', 'a-outcome', 'b-timestamp'])

    def test_filters_time_status_and_category_and_accepts_partial_classification(self):
        self.add('timed', time=80000)
        self.add('approved', status='approved')
        self.add('rejected', status='rejected')
        self.add('review', status='ready_for_review')
        self.add('unsupported', category='other')
        self.add('partial', status='classification_required')
        self.assertEqual(self.ids(), ['partial'])
        self.assertEqual(pending_ocr_videos(self.db, []), [])

    def test_ties_prefer_backlog_then_configured_category_then_id(self):
        self.add('z', 'small')
        self.add('b')
        self.add('a')
        self.assertEqual(self.ids(), ['a', 'b', 'z'])
        self.add('y', 'small')
        self.assertEqual(self.ids(), ['a', 'b', 'y', 'z'])

    def test_workflow_selects_once_globally_before_regrouping(self):
        # Execute the actual selection block embedded in the workflow, without
        # launching OCR, networking, or modifying the production database.
        import textwrap
        workflow = Path(__file__).resolve().parents[2] / '.github/workflows/ocr-scale.yml'
        source = workflow.read_text()
        start = source.index('          with sqlite3.connect(MASTER) as connection:')
        end = source.index('          order_index', start)
        with self.db:
            for index in range(15):
                self.add(f'retry-{index}', metadata={'ocr_attempts': 1})
            self.add('new', 'small')
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.sqlite3') as file:
            disk = sqlite3.connect(file.name)
            self.db.backup(disk)
            disk.close()
            namespace = dict(sqlite3=sqlite3, MASTER=file.name,
                             ALLOWED=('large', 'small'), MAX_VIDEOS_PER_RUN=12,
                             pending_ocr_videos=pending_ocr_videos)
            exec(textwrap.dedent(source[start:end]), namespace)
        self.assertEqual(len(namespace['selected']), 12)
        self.assertEqual(namespace['selected'][0], ('new', 'small'))
        self.assertEqual(namespace['counts'], {'large': 15, 'small': 1})
        self.assertNotIn('pending_ids(', source)


if __name__ == '__main__':
    unittest.main()
