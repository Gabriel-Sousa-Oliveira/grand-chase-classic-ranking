"""Command-line entry point for local validation and ingestion."""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .database import CandidateRepository
from .ocr import infer_chapter_time, read_video_time
from .parser import parse_title
from .relevance import description_from_metadata, evaluate_video_relevance
from .syntaxii import import_syntaxii
from .youtube import (DEFAULT_SEARCH_QUERIES, channel_archive, discover_videos,
                      extract_video_id, fetch_video, fill_ranking_queries)
from .video_pipeline import triage_ocr_result


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
    ocr_cmd.add_argument("--workers", type=int, default=1)
    ocr_cmd.add_argument("--all-missing", action="store_true")
    ocr_cmd.add_argument("--retry-no-consensus", action="store_true")
    ocr_cmd.add_argument("--character", action="append", dest="characters")
    ocr_cmd.add_argument("--video-id", action="append", dest="video_ids")
    commands.add_parser("queue")
    commands.add_parser("prune-irrelevant")
    args = parser.parse_args()

    if args.command == "parse":
        print(json.dumps(parse_title(args.title).to_dict(), ensure_ascii=False, indent=2))
        return
    repo = CandidateRepository(args.db)
    try:
        if args.command == "add":
            video_id = extract_video_id(args.url)
            result, created = repo.add(video_id, args.url, parse_title(args.title), args.channel)
            print(json.dumps({"created": created, "candidate": result, "queue_size": 1,
                              "candidates": [result]}, ensure_ascii=False, indent=2))
        elif args.command == "youtube":
            metadata = fetch_video(args.url)
            # Directly supplied URLs must refresh pending rows after parser aliases evolve.
            result, created = repo.add(metadata["video_id"], metadata["url"],
                                       parse_title(metadata["title"]), metadata["channel"],
                                       metadata["published_at"], metadata["raw"],
                                       enrich_existing=True)
            print(json.dumps({"created": created, "candidate": result, "queue_size": 1,
                              "candidates": [result]}, ensure_ascii=False, indent=2))
        elif args.command == "channel-archive":
            videos = channel_archive(args.reference_video, max_results=args.max_results)
            created = duplicates = ignored = 0
            statuses: dict[str, int] = {}
            ignored_reasons: dict[str, int] = {}
            for metadata in videos:
                parsed = parse_title(metadata["title"])
                decision = evaluate_video_relevance(
                    metadata["title"], description_from_metadata(metadata["raw"]), parsed
                )
                if not decision.accepted:
                    ignored += 1
                    reason = decision.reasons[0] if decision.reasons else "low_relevance"
                    ignored_reasons[reason] = ignored_reasons.get(reason, 0) + 1
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
                "ignored": ignored, "ignored_reasons": ignored_reasons,
                "statuses": statuses,
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
            ignored_reasons: dict[str, int] = {}
            for metadata in videos:
                parsed = parse_title(metadata["title"])
                decision = evaluate_video_relevance(
                    metadata["title"], description_from_metadata(metadata["raw"]), parsed
                )
                if ranking_mode:
                    accepted = (decision.accepted and parsed.character is not None and
                                parsed.category == "void_invasion" and parsed.floor == 3)
                else:
                    accepted = decision.accepted
                if not accepted:
                    ignored += 1
                    reason = decision.reasons[0] if decision.reasons else "outside_target"
                    if ranking_mode and decision.accepted:
                        reason = "outside_target"
                    ignored_reasons[reason] = ignored_reasons.get(reason, 0) + 1
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
                "duplicates": duplicates, "ignored": ignored,
                "ignored_reasons": ignored_reasons, "statuses": statuses,
                "queue_size": len(repo.queue()), "candidates": exported,
            }, ensure_ascii=False, indent=2))
        elif args.command == "ocr-queue":
            processed = matched = failed = 0
            results = []
            evidence_directory = Path(args.db).resolve().parent / "ocr-evidence"
            candidates = repo.ocr_candidates(
                args.limit, args.all_missing, args.retry_no_consensus,
                args.characters, args.video_ids,
            )

            def inspect(candidate: dict) -> tuple[dict, object | None, Exception | None]:
                try:
                    chapter_time = infer_chapter_time(
                        description_from_metadata(candidate.get("raw_metadata")),
                        candidate.get("floor"),
                    )
                    if chapter_time is not None:
                        return candidate, chapter_time, None
                    return candidate, read_video_time(
                        candidate["video_url"], evidence_directory,
                        candidate["video_id"],
                    ), None
                except Exception as error:
                    return candidate, None, error

            workers = max(1, min(args.workers, 8))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                inspections = executor.map(inspect, candidates)
                for candidate, ocr, error in inspections:
                    processed += 1
                    triage = triage_ocr_result(ocr, error)
                    if triage.processing_reason == "technical_error":
                        failed += 1
                        repo.record_ocr_attempt(candidate["id"], "error", {
                            "error_type": type(error).__name__,
                            "error_detail": str(error)[:1200],
                        })
                        results.append({"video_id": candidate["video_id"], "result": "error",
                                        "error": str(error)[:240]})
                        continue
                    if triage.destination == "manual_review":
                        diagnostic = evidence_directory / (
                            f"{candidate['video_id']}-no-consensus.png"
                        )
                        repo.record_ocr_attempt(candidate["id"], "no_consensus", {
                            "evidence_image": str(Path("ocr-evidence") / diagnostic.name)
                            if diagnostic.exists() else None,
                            "processing_reason": "timer_not_frozen_or_not_readable",
                        })
                        results.append({"video_id": candidate["video_id"], "result": "no_consensus"})
                        continue
                    repo.set_ocr_time(candidate["id"], ocr.time_ms, ocr.confidence, {
                        "engine": ocr.source, "matching_frames": ocr.matching_frames,
                        "observations": ocr.observations,
                        "evidence_frame": ocr.evidence_frame,
                        "evidence_seconds_from_end": ocr.evidence_seconds_from_end,
                        "evidence_image": ocr.evidence_image,
                        "roi": ocr.roi,
                    })
                    matched += 1
                    results.append({"video_id": candidate["video_id"], "result": "matched",
                                    "time_ms": ocr.time_ms, "confidence": ocr.confidence,
                                    "source": ocr.source})
            exported = [{key: candidate[key] for key in (
                "video_id", "video_url", "title", "channel", "player_nick",
                "published_at", "character", "category", "floor", "time_ms",
                "confidence", "status", "era_key", "raw_metadata"
            )} for candidate in repo.queue()]
            print(json.dumps({"mode": "ocr", "processed": processed, "matched": matched,
                              "matched_by_source": {
                                  source: sum(r.get("source") == source for r in results)
                                  for source in sorted({r["source"] for r in results if "source" in r})
                              },
                              "failed": failed, "results": results,
                              "remaining_ocr": repo.ocr_remaining(
                                  args.all_missing, args.retry_no_consensus,
                                  args.characters, args.video_ids,
                              ),
                              "queue_size": len(exported), "candidates": exported},
                             ensure_ascii=False, indent=2))
        elif args.command == "prune-irrelevant":
            rejected_ids = []
            rejection_reasons: dict[str, int] = {}
            for candidate in repo.queue():
                parsed = parse_title(candidate["title"])
                decision = evaluate_video_relevance(
                    candidate["title"],
                    description_from_metadata(candidate.get("raw_metadata")), parsed,
                )
                # Existing ambiguous rows stay available for human review. Only
                # explicit guide/compilation evidence is removed automatically.
                if decision.hard_reject:
                    rejected_ids.append(candidate["id"])
                    reason = decision.reasons[0]
                    rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
            rejected = repo.reject_candidates(
                rejected_ids, "automatic_relevance_filter"
            )
            exported = [{key: candidate[key] for key in (
                "video_id", "video_url", "title", "channel", "player_nick",
                "published_at", "character", "category", "floor", "time_ms",
                "confidence", "status", "era_key", "raw_metadata"
            )} for candidate in [*repo.queue(), *rejected]]
            print(json.dumps({
                "mode": "prune_irrelevant", "rejected": len(rejected),
                "rejection_reasons": rejection_reasons,
                "queue_size": len(repo.queue()), "candidates": exported,
            }, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(repo.queue(), ensure_ascii=False, indent=2))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
