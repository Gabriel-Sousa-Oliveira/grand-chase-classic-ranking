"""Command-line entry point for local validation and ingestion."""
from __future__ import annotations

import argparse
import json

from .database import CandidateRepository
from .parser import parse_title
from .youtube import DEFAULT_SEARCH_QUERIES, discover_videos, extract_video_id, fetch_video


def main() -> None:
    parser = argparse.ArgumentParser(prog="gc-radar")
    parser.add_argument("--db", default="gc_radar.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    parse_cmd = commands.add_parser("parse")
    parse_cmd.add_argument("title")
    add_cmd = commands.add_parser("add")
    add_cmd.add_argument("url")
    add_cmd.add_argument("--title", required=True)
    add_cmd.add_argument("--channel")
    yt_cmd = commands.add_parser("youtube")
    yt_cmd.add_argument("url")
    crawl_cmd = commands.add_parser("crawl")
    crawl_cmd.add_argument("--days", type=int, default=3)
    crawl_cmd.add_argument("--max-results", type=int, default=50)
    crawl_cmd.add_argument("--query", action="append", dest="queries")
    crawl_cmd.add_argument("--era", default="current")
    commands.add_parser("queue")
    args = parser.parse_args()

    if args.command == "parse":
        print(json.dumps(parse_title(args.title).to_dict(), ensure_ascii=False, indent=2))
        return
    repo = CandidateRepository(args.db)
    try:
        if args.command == "add":
            video_id = extract_video_id(args.url)
            result, created = repo.add(video_id, args.url, parse_title(args.title), args.channel)
            print(json.dumps({"created": created, "candidate": result}, ensure_ascii=False, indent=2))
        elif args.command == "youtube":
            metadata = fetch_video(args.url)
            result, created = repo.add(metadata["video_id"], metadata["url"],
                                       parse_title(metadata["title"]), metadata["channel"],
                                       metadata["published_at"], metadata["raw"])
            print(json.dumps({"created": created, "candidate": result}, ensure_ascii=False, indent=2))
        elif args.command == "crawl":
            videos = discover_videos(args.queries or DEFAULT_SEARCH_QUERIES,
                                     days=args.days, max_results=args.max_results)
            created = 0
            duplicates = 0
            ignored = 0
            statuses: dict[str, int] = {}
            exported: list[dict] = []
            for metadata in videos:
                parsed = parse_title(metadata["title"])
                # Broad YouTube queries can return unrelated videos. Keep only
                # titles where at least a character or supported category was found.
                if parsed.character is None and parsed.category is None:
                    ignored += 1
                    continue
                candidate, was_created = repo.add(
                    metadata["video_id"], metadata["url"], parsed,
                    metadata["channel"], metadata["published_at"], metadata["raw"],
                    era_key=args.era,
                )
                created += int(was_created)
                duplicates += int(not was_created)
                statuses[candidate["status"]] = statuses.get(candidate["status"], 0) + 1
                exported.append({key: candidate[key] for key in (
                    "video_id", "video_url", "title", "channel", "player_nick",
                    "published_at", "character", "category", "floor", "time_ms",
                    "confidence", "status", "era_key", "raw_metadata"
                )})
            print(json.dumps({
                "queries": len(args.queries or DEFAULT_SEARCH_QUERIES),
                "discovered_unique": len(videos), "created": created,
                "duplicates": duplicates, "ignored": ignored, "statuses": statuses,
                "queue_size": len(repo.queue()), "candidates": exported,
            }, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(repo.queue(), ensure_ascii=False, indent=2))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
