"""Read-only selection shared by the bounded OCR workflow and its tests."""
from collections import Counter
import re
import sqlite3
from typing import Iterable


def pending_ocr_videos(connection: sqlite3.Connection,
                       categories: Iterable[str]) -> list[tuple[str, str]]:
    """Order eligible (video_id, category) pairs before applying the run cap.

    Never-attempted videos precede all retries, across categories. Retries
    prefer fewer attempts, then the oldest attempt. Equal histories prefer
    the largest category backlog, configured category order, and video ID.
    An outcome or timestamp also marks legacy rows with no counter as tried.
    """
    categories = tuple(dict.fromkeys(categories))
    if not categories:
        return []
    placeholders = ','.join('?' for _ in categories)
    rows = connection.execute(f"""
        SELECT video_id, category,
               COALESCE(CAST(json_extract(raw_metadata, '$.ocr_attempts') AS INTEGER), 0),
               json_extract(raw_metadata, '$.ocr_attempted_at'),
               json_extract(raw_metadata, '$.ocr_outcome')
        FROM candidates WHERE category IN ({placeholders})
          AND time_ms IS NULL
          AND status IN ('time_required', 'classification_required')
    """, categories).fetchall()
    counts = Counter(row[1] for row in rows)
    category_order = {category: index for index, category in enumerate(categories)}

    def priority(row):
        video_id, category, attempts, attempted_at, outcome = row
        tried = attempts > 0 or attempted_at is not None or outcome is not None
        return (tried, max(1, attempts) if tried else 0, attempted_at or '',
                -counts[category], category_order[category], video_id)

    return [(row[0], row[1]) for row in sorted(rows, key=priority)]


def select_ocr_videos(pending: list[tuple[str, str]], raw_video_ids: str = "",
                      limit: int = 12) -> list[tuple[str, str]]:
    """Select an exact bounded retry, or use the normal queue when unspecified.

    Missing/ineligible IDs fail before OCR starts; never silently substitute
    other videos. Workflow input arrives through an environment variable.
    """
    if not 1 <= limit <= 12:
        raise ValueError("OCR selection limit must be between 1 and 12")
    requested = set(filter(None, re.split(r"[\s,]+", raw_video_ids.strip())))
    if not requested:
        return pending[:limit]
    if len(requested) > limit or any(
        re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) is None
        for video_id in requested
    ):
        raise ValueError("Provide at most 12 valid YouTube video IDs within the run limit")
    selected = [row for row in pending if row[0] in requested]
    if {row[0] for row in selected} != requested:
        raise ValueError("Requested videos must be eligible pending candidates without a time")
    return selected
