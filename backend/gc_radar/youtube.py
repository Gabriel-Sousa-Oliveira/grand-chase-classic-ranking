"""Small YouTube Data API client using only Python's standard library."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import urlopen


DEFAULT_SEARCH_QUERIES = (
    "Grand Chase Classic Void Invasion",
    "Grand Chase Classic Vazio Invasão",
    "Grand Chase Classic Void Taint",
    "Grand Chase Classic Vazio Contaminação",
    "Grand Chase Classic Void Nightmare",
    "Grand Chase Classic Vazio Pesadelo",
    "Grand Chase Classic Void Apocalypse",
    "Grand Chase Classic Vazio Apocalipse",
)


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


def _api_key(api_key: str | None) -> str:
    key = api_key or os.getenv("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("Set YOUTUBE_API_KEY before searching YouTube")
    return key


def _published_after(days: int, now: datetime | None = None) -> str:
    if days < 1:
        raise ValueError("days must be at least 1")
    current = now or datetime.now(timezone.utc)
    return (current - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


def search_videos(query: str, *, api_key: str | None = None, days: int = 3,
                  max_results: int = 50, page_token: str | None = None,
                  opener: Callable = urlopen, now: datetime | None = None) -> dict:
    """Run one quota-bounded search.list request and normalize its videos."""
    if not 1 <= max_results <= 50:
        raise ValueError("max_results must be between 1 and 50")
    params = {
        "part": "snippet", "type": "video", "order": "date", "q": query,
        "publishedAfter": _published_after(days, now), "maxResults": max_results,
        "key": _api_key(api_key),
    }
    if page_token:
        params["pageToken"] = page_token
    with opener("https://www.googleapis.com/youtube/v3/search?" + urlencode(params),
                timeout=20) as response:
        payload = json.load(response)
    videos = []
    for item in payload.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        if not video_id:
            continue
        videos.append({
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle"),
            "published_at": snippet.get("publishedAt"),
            "raw": item,
            "query": query,
        })
    return {"videos": videos, "next_page_token": payload.get("nextPageToken")}


def discover_videos(queries: Iterable[str] = DEFAULT_SEARCH_QUERIES, *,
                    api_key: str | None = None, days: int = 3,
                    max_results: int = 50, opener: Callable = urlopen,
                    now: datetime | None = None) -> list[dict]:
    """Search each query once and merge repeated results by YouTube video ID."""
    discovered: dict[str, dict] = {}
    for query in queries:
        result = search_videos(query, api_key=api_key, days=days,
                               max_results=max_results, opener=opener, now=now)
        for video in result["videos"]:
            discovered.setdefault(video["video_id"], video)
    return list(discovered.values())
