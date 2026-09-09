"""Conservative OCR extraction for completion times shown inside YouTube videos."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


MIN_TIME_SECONDS = 20
MAX_TIME_SECONDS = 20 * 60


@dataclass(frozen=True)
class OcrResult:
    time_ms: int
    confidence: float
    matching_frames: int
    observations: int


def _valid(seconds: int) -> bool:
    return MIN_TIME_SECONDS <= seconds <= MAX_TIME_SECONDS


def extract_times(text: str) -> set[int]:
    """Return plausible run durations in seconds from noisy OCR text."""
    normalized = text.translate(str.maketrans({
        "O": "0", "o": "0", "I": "1", "l": "1", "|": "1",
        "’": "'", "′": "'", "：": ":",
    }))
    found: set[int] = set()
    for match in re.finditer(r"(?<!\d)(\d{1,2})\s*[:']\s*(\d{2})(?!\d)", normalized):
        minutes, seconds = map(int, match.groups())
        total = minutes * 60 + seconds
        if seconds < 60 and _valid(total):
            found.add(total)
    for match in re.finditer(r"(?<!\d)(\d{1,2})\s*[mM]\s*(\d{1,2})\s*[sS]?(?!\d)", normalized):
        minutes, seconds = map(int, match.groups())
        total = minutes * 60 + seconds
        if seconds < 60 and _valid(total):
            found.add(total)
    return found


def choose_consensus(observations: list[tuple[str, int]]) -> OcrResult | None:
    """Choose a time only when it occurs in at least two different frames."""
    frames_by_time: dict[int, set[str]] = defaultdict(set)
    counts: dict[int, int] = defaultdict(int)
    for frame, seconds in observations:
        if _valid(seconds):
            frames_by_time[seconds].add(frame)
            counts[seconds] += 1
    ranked = sorted(frames_by_time, key=lambda value: (len(frames_by_time[value]), counts[value]), reverse=True)
    if not ranked:
        return None
    winner = ranked[0]
    matching_frames = len(frames_by_time[winner])
    if matching_frames < 2:
        return None
    if len(ranked) > 1 and len(frames_by_time[ranked[1]]) == matching_frames:
        return None
    confidence = min(0.94, 0.72 + (matching_frames - 2) * 0.05 + min(counts[winner] - matching_frames, 3) * 0.02)
    return OcrResult(winner * 1000, confidence, matching_frames, counts[winner])


def _run(command: list[str], timeout: int = 240) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise RuntimeError(detail[-1200:]) from error


def _require_tools() -> None:
    missing = [name for name in ("yt-dlp", "ffmpeg", "tesseract") if shutil.which(name) is None]
    if missing:
        raise RuntimeError("missing OCR tools: " + ", ".join(missing))


def _download_excerpt(video_url: str, destination: Path) -> Path:
    output = destination / "video.%(ext)s"
    command = [
        "yt-dlp", "--no-playlist", "--no-warnings", "--quiet",
        "--js-runtimes", "node", "--remote-components", "ejs:npm",
        "--impersonate", "chrome",
        "-f", "worstvideo[height>=360]/worstvideo/bestvideo",
        "-o", str(output),
    ]
    if os.environ.get("YOUTUBE_USE_PO_TOKEN") == "1":
        command.extend(["--extractor-args", "youtube:player_client=mweb"])
        # Browser-based providers can mint one video-bound token per download.
        browser_path = os.environ.get("YOUTUBE_PO_BROWSER_PATH")
        if browser_path:
            command.extend(["--extractor-args", f"youtubepot-wpc:browser_path={browser_path}"])
    cookies_file = os.environ.get("YOUTUBE_COOKIES_FILE")
    if cookies_file:
        command.extend(["--cookies", cookies_file])
    command.append(video_url)
    _run(command, timeout=360)
    videos = [path for path in destination.glob("video.*") if path.is_file()]
    if not videos:
        raise RuntimeError("yt-dlp did not create a video file")
    return videos[0]


def _extract_frames(video: Path, destination: Path) -> list[Path]:
    filters = {
        "full": "fps=1/6,scale=1280:-2,format=gray,eq=contrast=1.6",
        "center": "fps=1/6,crop=iw*0.80:ih*0.70:iw*0.10:ih*0.12,scale=1280:-2,format=gray,eq=contrast=1.7",
        "lower": "fps=1/6,crop=iw:ih*0.58:0:ih*0.42,scale=1280:-2,format=gray,eq=contrast=1.7",
    }
    frames: list[Path] = []
    for region, video_filter in filters.items():
        pattern = destination / f"{region}-%03d.png"
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-sseof", "-75", "-i", str(video),
              "-vf", video_filter, "-frames:v", "14", str(pattern)], timeout=180)
        frames.extend(sorted(destination.glob(f"{region}-*.png")))
    return frames


def read_video_time(video_url: str) -> OcrResult | None:
    """Download the final excerpt, sample frames and OCR a stable completion time."""
    _require_tools()
    with tempfile.TemporaryDirectory(prefix="gc-radar-ocr-") as temporary:
        directory = Path(temporary)
        video = _download_excerpt(video_url, directory)
        frames = _extract_frames(video, directory)
        observations: list[tuple[str, int]] = []
        for frame in frames:
            result = _run([
                "tesseract", str(frame), "stdout", "--psm", "11", "-l", "eng",
                "-c", "tessedit_char_whitelist=0123456789:;'mMsS",
            ], timeout=45)
            frame_id = frame.stem.rsplit("-", 1)[-1]
            observations.extend((frame_id, seconds) for seconds in extract_times(result.stdout))
        return choose_consensus(observations)
