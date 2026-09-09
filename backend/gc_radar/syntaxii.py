"""Import the public Syntaxii leaderboard as a reviewable historical baseline."""
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
import re
from typing import Callable
from urllib.request import Request, urlopen

from .database import CandidateRepository
from .parser import ParsedRun
from .youtube import extract_video_id


SHEET_ROOT = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vSg2rhuWbyxU6gWk79L54s3CoBLWuDUgrhxkaBZ2fnzOzdMEE48iuHff3O9z1NZBOiYR8f8dkMHHdnd/"
    "pub?single=true&output=csv&gid="
)


@dataclass(frozen=True)
class SyntaxiiDungeon:
    name: str
    category: str
    floor: int
    gid: str
    metric: str = "time"
    source_url: str | None = None

    @property
    def url(self) -> str:
        return self.source_url or SHEET_ROOT + self.gid


DUNGEONS = (
    SyntaxiiDungeon("Void Invasion", "void_invasion", 3, "1827141351"),
    SyntaxiiDungeon("Void Taint", "void_taint", 3, "1202569298"),
    SyntaxiiDungeon("Void Nightmare", "void_nightmare", 4, "288867483"),
    SyntaxiiDungeon("Void Apocalypse", "void_apocalypse", 3, "1151121372"),
    SyntaxiiDungeon("Tower of Disappearance", "tower_of_disappearance", 0, "1230006600"),
    SyntaxiiDungeon("Duel 4", "duel_4", 0, "1725380348"),
    SyntaxiiDungeon("LoJ Unlimited", "loj_unlimited", 0, "1478193332", "score"),
)

ARCHIVE_ROOT = "https://raw.githubusercontent.com/syntax817/leaderboard/main/"
ARCHIVE_DUNGEONS = (
    SyntaxiiDungeon("Void Invasion", "void_invasion", 3, "archive-v1", source_url=ARCHIVE_ROOT + "v1.csv"),
    SyntaxiiDungeon("Void Taint", "void_taint", 3, "archive-v2", source_url=ARCHIVE_ROOT + "v2.csv"),
    SyntaxiiDungeon("Void Nightmare", "void_nightmare", 4, "archive-v3", source_url=ARCHIVE_ROOT + "v3.csv"),
    SyntaxiiDungeon("Tower of Disappearance", "tower_of_disappearance", 0, "archive-tod", source_url=ARCHIVE_ROOT + "tod.csv"),
)

CHARACTERS = {
    "elesis": "Elesis", "lire": "Lire", "arme": "Arme", "lass": "Lass",
    "ryan": "Ryan", "ronan": "Ronan", "amy": "Amy", "jin": "Jin",
    "sieghart": "Sieghart", "mari": "Mari", "dio": "Dio", "zero": "Zero",
    "ley/rey": "Ley/Rey", "rey/ley": "Ley/Rey", "rufus/lupus": "Rufus/Lupus",
    "lupus/rufus": "Rufus/Lupus", "rin/lin": "Rin/Lin", "l-rin": "Rin/Lin",
    "d-rin": "Rin/Lin", "asin": "Asin", "lime/holy": "Lime/Holy",
    "holy/lime": "Lime/Holy", "edel": "Edel", "veigas": "Veigas", "uno": "Uno",
    "decanee": "Decanee", "kallia": "Kallia", "ai": "Ai", "iris": "Iris", "ereb": "Ereb",
}


def _clean_character(value: str) -> str | None:
    clean = re.sub(r"^\s*\d{1,2}\)\s*", "", value).strip()
    return CHARACTERS.get(clean.casefold())


def _time_ms(value: str) -> int | None:
    match = re.fullmatch(r"\s*(\d{1,2}):([0-5]\d)(?:[.,](\d{1,3}))?\s*", value)
    if not match:
        return None
    fraction = match.group(3)
    return (int(match.group(1)) * 60 + int(match.group(2))) * 1000 + (
        int(fraction.ljust(3, "0")) if fraction else 0
    )


def _iso_date(value: str) -> str | None:
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def fetch_csv(url: str, opener: Callable = urlopen) -> str:
    request = Request(url, headers={"User-Agent": "GC-Run-Radar/1.0"})
    with opener(request, timeout=30) as response:
        return response.read().decode("utf-8-sig")


def parse_sheet(text: str, dungeon: SyntaxiiDungeon) -> list[dict]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample else csv.excel
    rows = list(csv.reader(StringIO(text), dialect))
    header_index = next((i for i, row in enumerate(rows) if row and row[0].strip() == "Position"), None)
    if header_index is None:
        raise ValueError(f"Syntaxii sheet has no Position header: {dungeon.name}")
    headers = [column.strip() for column in rows[header_index]]
    video_column = "Scorerun video:" if dungeon.metric == "score" else "Speedrun video:"
    value_column = "Score" if dungeon.metric == "score" else "Time"
    parsed = []
    for source_row in rows[header_index + 1:]:
        source_row += [""] * (len(headers) - len(source_row))
        row = dict(zip(headers, source_row))
        video_url = row.get(video_column, "").strip()
        character = _clean_character(row.get("Character", ""))
        player = row.get("Player", "").strip()
        if not video_url or not character or not player:
            continue
        try:
            video_id = extract_video_id(video_url)
        except ValueError:
            continue
        time_ms = _time_ms(row.get(value_column, "")) if dungeon.metric == "time" else None
        score_text = row.get(value_column, "").strip() if dungeon.metric == "score" else None
        if dungeon.metric == "time" and time_ms is None:
            continue
        parsed.append({
            "video_id": video_id, "video_url": video_url, "character": character,
            "player_nick": player, "time_ms": time_ms, "score": score_text,
            "published_at": _iso_date(row.get("Post date (dd/mm/yyyy)", "")),
            "position": row.get("Position", "").strip(),
        })
    return parsed


def import_syntaxii(repo: CandidateRepository, *, opener: Callable = urlopen,
                    era_key: str = "current", include_archive: bool = True) -> dict:
    inserted = duplicates = skipped_scores = 0
    per_dungeon: dict[str, int] = {}
    failures: dict[str, str] = {}
    sheets: dict[SyntaxiiDungeon, str] = {}
    sources = []
    if include_archive:
        sources.extend((dungeon, "syntaxii_2026_archive", "github_archive") for dungeon in ARCHIVE_DUNGEONS)
    # Live rows are processed last so they win when the same video also exists in the snapshot.
    sources.extend((dungeon, era_key, "live") for dungeon in DUNGEONS)
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        pending = {
            executor.submit(fetch_csv, dungeon.url, opener): (dungeon, source_kind)
            for dungeon, _, source_kind in sources
        }
        for future in as_completed(pending):
            dungeon, source_kind = pending[future]
            try:
                sheets[dungeon] = future.result()
            except Exception as error:  # preserve the other public sources on a partial outage
                failures[f"{source_kind}:{dungeon.category}"] = str(error)
    for dungeon, source_era, source_kind in sources:
        if dungeon not in sheets:
            per_dungeon.setdefault(dungeon.category, 0)
            continue
        records = parse_sheet(sheets[dungeon], dungeon)
        per_dungeon[dungeon.category] = per_dungeon.get(dungeon.category, 0) + len(records)
        for record in records:
            if dungeon.metric == "score":
                skipped_scores += 1
                continue
            label = f"{record['character']} | {dungeon.name}"
            if dungeon.floor:
                label += f" {dungeon.floor}F"
            seconds = record["time_ms"] // 1000
            label += f" | {seconds // 60:02d}:{seconds % 60:02d} | Syntaxii"
            parsed = ParsedRun(
                title=label, character=record["character"], category=dungeon.category,
                floor=dungeon.floor, time_ms=record["time_ms"], solo=None,
                no_potions=None, no_quotes=None, confidence=0.95,
                status="ready_for_review", missing_fields=(),
            )
            metadata = {
                "source": "syntaxii", "source_url": dungeon.url,
                "source_leaderboard": "https://syntax817.github.io/leaderboard/",
                "source_position": record["position"], "metric": dungeon.metric,
                "source_kind": source_kind,
            }
            _, created = repo.add(
                record["video_id"], record["video_url"], parsed,
                channel=record["player_nick"], player_nick=record["player_nick"],
                published_at=record["published_at"], metadata=metadata, era_key=source_era,
                enrich_existing=True,
            )
            inserted += int(created)
            duplicates += int(not created)
    return {
        "source": "syntaxii", "dungeons": len(DUNGEONS), "per_dungeon": per_dungeon,
        "archive_included": include_archive,
        "inserted": inserted, "duplicates": duplicates, "score_rows_deferred": skipped_scores,
        "failures": failures,
    }
