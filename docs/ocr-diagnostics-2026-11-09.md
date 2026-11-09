# Persistent OCR diagnostics

Previously all unresolved scans were exported as `timer_not_frozen_or_not_readable`.
Each new attempt now records observed scan counters and a failure category:

- `results_screen_not_found`: no sampled frame passed the supported panel detector.
  This does **not** prove that the source video never displayed a results screen.
- `timer_not_found`: a panel passed detection but no valid time observation emerged.
- `conflicting_reads`: valid readings span different whole-second values, without
  the consensus required for acceptance. This can include a still-animating panel.
- `insufficient_stable_frames`: readings did not produce an accepted stable sequence.
- `download_error`: an exception occurred during the actual download stage.
- `technical_error`: another processing exception occurred.
- `diagnostic_unavailable`: the caller supplied no instrumented scan observations.
- `not_supported_layout` is reserved for explicitly confirmed unsupported layouts;
  the current detector does not guess a video's language from missing labels.

The version is the extraction-logic version (`gc-ocr-diagnostics-v1`), not an
invented Tesseract binary version. `evidence_seconds` is an approximate offset
**before the end of the downloaded excerpt** for a detected panel frame, not an
absolute timestamp in the full YouTube video. It may be null when no panel is seen.
The associated evidence path references the workflow's short-lived artifact.

A thread-local context gathers sampled/result/readable frame counts and distinct
second buckets without changing OCR acceptance. Existing scans remain bounded.
The database retains up to ten recent attempt summaries and a cumulative counter;
a successful retry removes the current failure reason while keeping recent history.

The workflow exports the fields in results, candidate raw_metadata, and diagnostic
artifacts, then sends the current round to `/api/candidates/ocr-outcomes` using the
same ingestion bearer token already used for candidate uploads. Interactive repair
continues to require the existing authenticated Site identity. Outcome reports do
not directly change candidate classification, time, approval, or rejection.

The API merges ordinary crawler metadata while retaining newer OCR keys, blocks
older outcome reports, never lowers the attempt counter for a compatible run, and
continues protecting approved/rejected records. Conflicting run identity replaces
incompatible metadata. API tests execute the real route handlers and SQL against
SQLite, including the insert → failure → crawler-refresh regression scenario.

`GET /api/candidates` adds `ocr_failures: {total_failed, breakdown}`. These counts
represent each **currently unresolved pending candidate's latest attempt**, not
all historical attempts. The aggregation is independent of the 500-row queue
response cap and excludes candidates whose times have since been resolved.
Legacy failures remain generic until reprocessed; no historical diagnosis is guessed.
The administrative queue shows the breakdown and the selected candidate's latest
reason, attempt counter, timestamp (Brasilia) and extraction version.

Validation: 142 Python tests, 45 Node tests (including five executable API/SQLite
integration tests), production build, and TypeScript with generated Workers types.
No live OCR batch was reprocessed as part of this instrumentation change. Existing
November 9 failures need a future scan to acquire detailed diagnostic counters.
