"""Small YouTube Data API client using only Python's standard library."""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import urlopen


def extract_video_id(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    parsed = urlparse(value)
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/")[0]
    else:
        candidate = parse_qs(parsed.query).get("v", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        raise ValueError("invalid YouTube video URL or id")
    return candidate


def fetch_video(value: str, api_key: str | None = None) -> dict:
    key = api_key or os.getenv("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("Set YOUTUBE_API_KEY before fetching YouTube metadata")
    video_id = extract_video_id(value)
    query = urlencode({"part": "snippet,contentDetails", "id": video_id, "key": key})
    with urlopen("https://www.googleapis.com/youtube/v3/videos?" + query, timeout=20) as response:
        payload = json.load(response)
    if not payload.get("items"):
        raise LookupError(f"YouTube video not found: {video_id}")
    item = payload["items"][0]
    snippet = item["snippet"]
    return {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": snippet["title"], "channel": snippet["channelTitle"],
            "published_at": snippet["publishedAt"], "duration": item["contentDetails"]["duration"],
            "raw": item}

