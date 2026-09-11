"""SQLite persistence for candidates and ranking decisions."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .parser import ParsedRun

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id TEXT NOT NULL UNIQUE,
  video_url TEXT NOT NULL,
  title TEXT NOT NULL,
  channel TEXT,
  player_nick TEXT,
  published_at TEXT,
  character TEXT,
  category TEXT,
  floor INTEGER,
  time_ms INTEGER,
  solo INTEGER,
  no_potions INTEGER,
  no_quotes INTEGER,
  confidence REAL NOT NULL,
  status TEXT NOT NULL CHECK(status IN (
    'ready_for_review','time_required','classification_required','approved','rejected'
  )),
  rejection_reason TEXT,
  era_key TEXT NOT NULL DEFAULT 'current',
  raw_metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_candidates_queue ON candidates(status, category, character);
CREATE TABLE IF NOT EXISTS rankings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id INTEGER NOT NULL UNIQUE REFERENCES candidates(id),
  character TEXT NOT NULL,
  category TEXT NOT NULL,
  floor INTEGER NOT NULL,
  time_ms INTEGER NOT NULL,
  player_nick TEXT NOT NULL,
  era_key TEXT NOT NULL DEFAULT 'current',
  approved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rankings_time ON rankings(category, floor, time_ms);
"""


def _ensure_column(connection: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _bit(value: bool | None) -> int | None:
    return None if value is None else int(value)


def canonical_player_nick(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return "Borkaz" if cleaned.casefold() == "bork" else cleaned


class CandidateRepository:
    def __init__(self, path: str | Path = "gc_radar.sqlite3") -> None:
        self.path = str(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        _ensure_column(self.connection, "candidates", "player_nick", "TEXT")
        _ensure_column(self.connection, "candidates", "era_key", "TEXT NOT NULL DEFAULT 'current'")
        _ensure_column(self.connection, "rankings", "player_nick", "TEXT")
        _ensure_column(self.connection, "rankings", "era_key", "TEXT NOT NULL DEFAULT 'current'")
        self.connection.execute("""UPDATE rankings SET player_nick = COALESCE(
            player_nick, (SELECT COALESCE(c.player_nick, c.channel, 'Desconhecido')
            FROM candidates c WHERE c.id = rankings.candidate_id))""")
        self.connection.execute("""UPDATE candidates SET player_nick = 'Borkaz'
            WHERE lower(trim(player_nick)) = 'bork'""")
        self.connection.execute("""UPDATE rankings SET player_nick = 'Borkaz'
            WHERE lower(trim(player_nick)) = 'bork'""")
        self.connection.execute("""CREATE INDEX IF NOT EXISTS idx_rankings_character
            ON rankings(era_key, category, floor, character, time_ms)""")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def add(self, video_id: str, video_url: str, parsed: ParsedRun,
            channel: str | None = None, published_at: str | None = None,
            metadata: dict | None = None, player_nick: str | None = None,
            era_key: str = "current", enrich_existing: bool = False) -> tuple[dict, bool]:
        values = (video_id, video_url, parsed.title, channel,
                  canonical_player_nick(player_nick or channel),
                  published_at,
                  parsed.character, parsed.category, parsed.floor, parsed.time_ms,
                  _bit(parsed.solo), _bit(parsed.no_potions), _bit(parsed.no_quotes),
                  parsed.confidence, parsed.status, era_key,
                  json.dumps(metadata or {}, ensure_ascii=False))
        try:
            cursor = self.connection.execute("""
                INSERT INTO candidates (
                  video_id, video_url, title, channel, player_nick, published_at, character,
                  category, floor, time_ms, solo, no_potions, no_quotes,
                  confidence, status, era_key, raw_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, values)
            self.connection.commit()
            return self.get(cursor.lastrowid), True
        except sqlite3.IntegrityError:
            if enrich_existing:
                self.connection.execute("""UPDATE candidates SET
                    video_url = ?, title = ?, channel = COALESCE(?, channel),
                    player_nick = COALESCE(?, player_nick),
                    published_at = COALESCE(?, published_at), character = ?, category = ?,
                    floor = ?, time_ms = ?, confidence = ?, status = ?, era_key = ?,
                    raw_metadata = ?, updated_at = CURRENT_TIMESTAMP
                  WHERE video_id = ? AND status NOT IN ('approved', 'rejected')""",
                  (video_url, parsed.title, channel,
                   canonical_player_nick(player_nick or channel), published_at,
                   parsed.character, parsed.category, parsed.floor, parsed.time_ms,
                   parsed.confidence, parsed.status, era_key,
                   json.dumps(metadata or {}, ensure_ascii=False), video_id))
                self.connection.commit()
            row = self.connection.execute(
                "SELECT * FROM candidates WHERE video_id = ?", (video_id,)
            ).fetchone()
            return dict(row), False

    def get(self, candidate_id: int) -> dict:
        row = self.connection.execute(
            "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return dict(row)

    def queue(self) -> list[dict]:
        rows = self.connection.execute("""
            SELECT * FROM candidates
            WHERE status IN ('ready_for_review','time_required','classification_required')
            ORDER BY confidence DESC, created_at ASC
        """).fetchall()
        return [dict(row) for row in rows]

    def set_time(self, candidate_id: int, time_ms: int) -> dict:
        if time_ms <= 0:
            raise ValueError("time_ms must be positive")
        self.connection.execute("""
            UPDATE candidates SET time_ms = ?, status = CASE
              WHEN character IS NOT NULL AND category IS NOT NULL AND floor IS NOT NULL
              THEN 'ready_for_review' ELSE 'classification_required' END,
              updated_at = CURRENT_TIMESTAMP WHERE id = ?
        """, (time_ms, candidate_id))
        self.connection.commit()
        return self.get(candidate_id)

    def time_required(self, limit: int = 8) -> list[dict]:
        rows = self.connection.execute("""
            SELECT * FROM candidates WHERE status = 'time_required'
            ORDER BY json_extract(raw_metadata, '$.ocr_attempted_at') IS NOT NULL,
                     updated_at ASC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(row) for row in rows]

    def ocr_candidates(self, limit: int = 8,
                       include_classification: bool = False) -> list[dict]:
        """Return missing-time videos that have not produced a final OCR result.

        A previous ``no_consensus`` is final and belongs in the manual queue.
        Technical errors remain eligible for a later retry.
        """
        statuses = ("time_required", "classification_required") \
            if include_classification else ("time_required",)
        placeholders = ",".join("?" for _ in statuses)
        query = f"""
            SELECT * FROM candidates
            WHERE time_ms IS NULL AND status IN ({placeholders})
              AND COALESCE(json_extract(raw_metadata, '$.ocr_outcome'), '')
                  != 'no_consensus'
            ORDER BY json_extract(raw_metadata, '$.ocr_outcome') = 'error',
                     updated_at ASC
        """
        parameters: list[object] = list(statuses)
        if limit > 0:
            query += " LIMIT ?"
            parameters.append(limit)
        rows = self.connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def ocr_remaining(self, include_classification: bool = False) -> int:
        statuses = ("time_required", "classification_required") \
            if include_classification else ("time_required",)
        placeholders = ",".join("?" for _ in statuses)
        row = self.connection.execute(f"""
            SELECT COUNT(*) FROM candidates
            WHERE time_ms IS NULL AND status IN ({placeholders})
              AND COALESCE(json_extract(raw_metadata, '$.ocr_outcome'), '')
                  != 'no_consensus'
        """, statuses).fetchone()
        return int(row[0])

    def record_ocr_attempt(self, candidate_id: int, outcome: str) -> dict:
        candidate = self.get(candidate_id)
        metadata = json.loads(candidate["raw_metadata"] or "{}")
        metadata["ocr_attempted_at"] = datetime.now(timezone.utc).isoformat()
        metadata["ocr_outcome"] = outcome
        metadata["ocr_attempts"] = int(metadata.get("ocr_attempts", 0)) + 1
        self.connection.execute("""
            UPDATE candidates SET raw_metadata = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (json.dumps(metadata, ensure_ascii=False), candidate_id))
        self.connection.commit()
        return self.get(candidate_id)

    def set_ocr_time(self, candidate_id: int, time_ms: int, confidence: float,
                     evidence: dict) -> dict:
        if time_ms <= 0:
            raise ValueError("time_ms must be positive")
        candidate = self.get(candidate_id)
        metadata = json.loads(candidate["raw_metadata"] or "{}")
        metadata["ocr"] = evidence
        metadata["ocr_attempted_at"] = datetime.now(timezone.utc).isoformat()
        metadata["ocr_outcome"] = "matched"
        metadata["ocr_attempts"] = int(metadata.get("ocr_attempts", 0)) + 1
        self.connection.execute("""
            UPDATE candidates SET time_ms = ?, confidence = ?, raw_metadata = ?,
              status = CASE
                WHEN character IS NOT NULL AND category IS NOT NULL AND floor IS NOT NULL
                THEN 'ready_for_review' ELSE 'classification_required' END,
              updated_at = CURRENT_TIMESTAMP WHERE id = ?
        """, (time_ms, confidence, json.dumps(metadata, ensure_ascii=False), candidate_id))
        self.connection.commit()
        return self.get(candidate_id)

    def decide(self, candidate_id: int, approved: bool,
               rejection_reason: str | None = None) -> dict:
        candidate = self.get(candidate_id)
        if approved and any(candidate[key] is None for key in ("character","category","floor","time_ms")):
            raise ValueError("candidate is incomplete")
        status = "approved" if approved else "rejected"
        with self.connection:
            self.connection.execute("""UPDATE candidates SET status = ?, rejection_reason = ?,
                updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (status, rejection_reason, candidate_id))
            if approved:
                player_nick = candidate["player_nick"] or candidate["channel"] or "Desconhecido"
                self.connection.execute("""INSERT OR REPLACE INTO rankings
                    (candidate_id, character, category, floor, time_ms, player_nick, era_key)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""", (candidate_id, candidate["character"],
                    candidate["category"], candidate["floor"], candidate["time_ms"],
                    player_nick, candidate["era_key"]))
        return self.get(candidate_id)

    def ranking(self, category: str, floor: int) -> list[dict]:
        rows = self.connection.execute("""SELECT r.*, c.channel, c.video_url
            FROM rankings r JOIN candidates c ON c.id = r.candidate_id
            WHERE r.category = ? AND r.floor = ? ORDER BY r.time_ms ASC""",
            (category, floor)).fetchall()
        return [dict(row) for row in rows]

    def character_ranking(self, category: str, floor: int, character: str,
                          era_key: str = "current", limit: int = 4) -> list[dict]:
        """Return each nick's fastest approved run for one character."""
        rows = self.connection.execute("""
            SELECT r.*, c.channel, c.video_url FROM rankings r
            JOIN candidates c ON c.id = r.candidate_id
            JOIN (
              SELECT player_nick, MIN(time_ms) AS best_time
              FROM rankings
              WHERE category = ? AND floor = ? AND character = ? AND era_key = ?
              GROUP BY player_nick
            ) best ON best.player_nick = r.player_nick AND best.best_time = r.time_ms
            WHERE r.category = ? AND r.floor = ? AND r.character = ? AND r.era_key = ?
            GROUP BY r.player_nick
            ORDER BY r.time_ms ASC, r.approved_at ASC
            LIMIT ?
        """, (category, floor, character, era_key,
                category, floor, character, era_key, limit)).fetchall()
        return [dict(row) for row in rows]

    def ranking_by_character(self, category: str, floor: int,
                             era_key: str = "current", limit: int = 4) -> dict[str, list[dict]]:
        characters = self.connection.execute("""
            SELECT DISTINCT character FROM rankings
            WHERE category = ? AND floor = ? AND era_key = ? ORDER BY character
        """, (category, floor, era_key)).fetchall()
        return {row["character"]: self.character_ranking(
            category, floor, row["character"], era_key, limit
        ) for row in characters}
