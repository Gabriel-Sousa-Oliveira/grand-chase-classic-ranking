"""Command-line entry point for local validation and ingestion."""
from __future__ import annotations

import argparse
import json

from .database import CandidateRepository
from .parser import parse_title
from .youtube import extract_video_id, fetch_video


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
        else:
            print(json.dumps(repo.queue(), ensure_ascii=False, indent=2))
    finally:
        repo.close()


if __name__ == "__main__":
    main()

