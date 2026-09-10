"""Command-line entry point for local validation and ingestion."""
from __future__ import annotations

import argparse
import json

from .database import CandidateRepository
from .ocr import read_video_time
from .parser import parse_title
from .syntaxii import import_syntaxii
from .youtube import (DEFAULT_SEARCH_QUERIES, channel_archive, discover_videos,
                      extract_video_id, fetch_video, fill_ranking_queries)


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
    channel_cmd = commands.add_parser("channel-archive")
    channel_cmd.add_argument("reference_video")
    channel_cmd.add_argument("--max-results", type=int, default=500)
    channel_cmd.add_argument("--era", default="current")
    crawl_cmd = commands.add_parser("crawl")
    crawl_cmd.add_argument("--days", type=int, default=3)
    crawl_cmd.add_argument("--max-results", type=int, default=50)
    crawl_cmd.add_argument("--query", action="append", dest="queries")
    crawl_cmd.add_argument("--era", default="current")
    fill_cmd = commands.add_parser("fill-ranking")
    fill_cmd.add_argument("--days", type=int, default=365)
    fill_cmd.add_argument("--max-results", type=int, default=25)
    fill_cmd.add_argument("--era", default="current")
    syntaxii_cmd = commands.add_parser("import-syntaxii")
    syntaxii_cmd.add_argument("--era", default="current")
    ocr_cmd = commands.add_parser("ocr-queue")
    ocr_cmd.add_argument("--limit", type=int, default=8)
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
            # Directly supplied URLs must refresh pending rows after parser aliases evolve.
            result, created = repo.add(metadata["video_id"], metadata["url"],
                                       parse_title(metadata["title"]), metadata["channel"],
                                       metadata["published_at"], metadata["raw"],
                                       enrich_existing=True)
            print(json.dumps({"created": created, "candidate": result}, ensure_ascii=False, indent=2))
        elif args.command == "channel-archive":
            videos = channel_archive(args.reference_video, max_results=args.max_results)
            created = duplicates = ignored = 0
            statuses: dict[str, int] = {}
            for metadata in videos:
                parsed = parse_title(metadata["title"])
                if parsed.character is None and parsed.category is None:
                    ignored += 1
                    continue
                candidate, was_created = repo.add(
                    metadata["video_id"], metadata["url"], parsed,
                    metadata["channel"], metadata["published_at"], metadata["raw"],
                    era_key=args.era, enrich_existing=True,
                )
                created += int(was_created)
                duplicates += int(not was_created)
                statuses[candidate["status"]] = statuses.get(candidate["status"], 0) + 1
            exported = [{key: candidate[key] for key in (
                "video_id", "video_url", "title", "channel", "player_nick",
                "published_at", "character", "category", "floor", "time_ms",
                "confidence", "status", "era_key", "raw_metadata"
            )} for candidate in repo.queue()]
            print(json.dumps({
                "mode": "channel_archive", "reference_video": args.reference_video,
                "scanned": len(videos), "created": created, "duplicates": duplicates,
                "ignored": ignored, "statuses": statuses,
                "queue_size": len(exported), "candidates": exported,
            }, ensure_ascii=False, indent=2))
        elif args.command == "import-syntaxii":
            summary = import_syntaxii(repo, era_key=args.era)
            exported = [{key: candidate[key] for key in (
                "video_id", "video_url", "title", "channel", "player_nick",
                "published_at", "character", "category", "floor", "time_ms",
                "confidence", "status", "era_key", "raw_metadata"
            )} for candidate in repo.queue()]
            print(json.dumps({**summary, "queue_size": len(exported), "candidates": exported},
                             ensure_ascii=False, indent=2))
        elif args.command in {"crawl", "fill-ranking"}:
            ranking_mode = args.command == "fill-ranking"
            queries = fill_ranking_queries() if ranking_mode else (args.queries or DEFAULT_SEARCH_QUERIES)
            videos = discover_videos(queries,
                                     days=args.days, max_results=args.max_results)
            created = 0
            duplicates = 0
            ignored = 0
            statuses: dict[str, int] = {}
            for metadata in videos:
                parsed = parse_title(metadata["title"])
                if ranking_mode:
                    accepted = (parsed.character is not None and
                                parsed.category == "void_invasion" and parsed.floor == 3)
                else:
                    accepted = parsed.character is not None or parsed.category is not None
                if not accepted:
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
            exported = [{key: candidate[key] for key in (
                "video_id", "video_url", "title", "channel", "player_nick",
                "published_at", "character", "category", "floor", "time_ms",
                "confidence", "status", "era_key", "raw_metadata"
            )} for candidate in repo.queue()]
            print(json.dumps({
                "mode": "fill-ranking" if ranking_mode else "recent",
                "target": "void_invasion_3f" if ranking_mode else "all_supported_dungeons",
                "queries": len(queries),
                "discovered_unique": len(videos), "created": created,
                "duplicates": duplicates, "ignored": ignored, "statuses": statuses,
                "queue_size": len(repo.queue()), "candidates": exported,
            }, ensure_ascii=False, indent=2))
        elif args.command == "ocr-queue":
            processed = matched = failed = 0
            results = []
            for candidate in repo.time_required(args.limit):
                processed += 1
                try:
                    ocr = read_video_time(candidate["video_url"])
                    if ocr is None:
                        repo.record_ocr_attempt(candidate["id"], "no_consensus")
                        results.append({"video_id": candidate["video_id"], "result": "no_consensus"})
                        continue
                    repo.set_ocr_time(candidate["id"], ocr.time_ms, ocr.confidence, {
                        "engine": "tesseract", "matching_frames": ocr.matching_frames,
                        "observations": ocr.observations,
                    })
                    matched += 1
                    results.append({"video_id": candidate["video_id"], "result": "matched",
                                    "time_ms": ocr.time_ms, "confidence": ocr.confidence})
                except Exception as error:
                    failed += 1
                    repo.record_ocr_attempt(candidate["id"], "error")
                    results.append({"video_id": candidate["video_id"], "result": "error",
                                    "error": str(error)[:240]})
            exported = [{key: candidate[key] for key in (
                "video_id", "video_url", "title", "channel", "player_nick",
                "published_at", "character", "category", "floor", "time_ms",
                "confidence", "status", "era_key", "raw_metadata"
            )} for candidate in repo.queue()]
            print(json.dumps({"mode": "ocr", "processed": processed, "matched": matched,
                              "failed": failed, "results": results,
                              "queue_size": len(exported), "candidates": exported},
                             ensure_ascii=False, indent=2))
        else:
            print(json.dumps(repo.queue(), ensure_ascii=False, indent=2))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
