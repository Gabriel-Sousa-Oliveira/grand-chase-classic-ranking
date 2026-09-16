"""Conservative OCR extraction for completion times shown inside YouTube videos."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextvars import ContextVar
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


MIN_TIME_MS = 20_000
MAX_TIME_MS = 20 * 60 * 1000
VIDEO_BUDGET_SECONDS = 300
_deadline: ContextVar[float | None] = ContextVar("ocr_deadline", default=None)
_anchors: ContextVar[dict] = ContextVar("ocr_anchors", default={})
DOWNLOAD_WINDOW_SECONDS = 120
COARSE_WINDOW_SECONDS = 90
COARSE_FPS = 1
DENSE_WINDOW_SECONDS = 30
DENSE_FPS = 2
TIMER_ROIS = {
    # Calibrated from full-frame mosaics captured across real GCC uploads.
    # Gameplay countdowns sit at the top-center; the completion screen exposes
    # a separate Clear Time field lower in the central results panel.
    # Every crop remains below 4% of the source frame.
    "top_center_timer": (0.40, 0.02, 0.60, 0.15),
    "top_center_timer_wide": (0.43, 0.02, 0.64, 0.15),
    "results_panel": (0.48, 0.67, 0.66, 0.85),
}


@dataclass(frozen=True)
class OcrObservation:
    frame_id: str
    time_ms: int
    seconds_from_end: float
    confidence: float
    evidence_path: str


@dataclass(frozen=True)
class OcrResult:
    time_ms: int
    confidence: float
    matching_frames: int
    observations: int
    evidence_frame: str | None = None
    evidence_seconds_from_end: int | None = None
    evidence_image: str | None = None
    roi: str | None = None
    source: str = "tesseract+opencv"


def _valid_ms(time_ms: int) -> bool:
    return MIN_TIME_MS <= time_ms <= MAX_TIME_MS


CHAPTER_LINE_PATTERN = re.compile(
    r"^\s*((?:\d{1,2}:)?\d{1,2}:\d{2})\s+(.+?)\s*$", re.MULTILINE
)
CHAPTER_FLOOR_PATTERN = re.compile(
    r"(?<!\d)([1-9])\s*(?:f|floor|andar|층|ชั้น)(?!\w)", re.IGNORECASE
)


def infer_chapter_time(description: str, floor: int | None) -> OcrResult | None:
    """Infer one floor duration from consecutive YouTube chapter markers.

    This intentionally requires a multi-floor chapter list. A lone timestamp in
    prose is not enough evidence, while a target floor followed by the next
    chapter provides explicit start and end boundaries.
    """
    if floor is None or floor <= 0:
        return None

    chapters: list[tuple[int, str, int | None]] = []
    for timestamp, label in CHAPTER_LINE_PATTERN.findall(description):
        parts = [int(part) for part in timestamp.split(":")]
        seconds = (parts[0] * 60 + parts[1]) if len(parts) == 2 else (
            parts[0] * 3600 + parts[1] * 60 + parts[2]
        )
        match = CHAPTER_FLOOR_PATTERN.search(label)
        chapters.append((seconds, label.strip(), int(match.group(1)) if match else None))

    if len(chapters) < 3 or any(
            current[0] >= following[0]
            for current, following in zip(chapters, chapters[1:])):
        return None
    floor_markers = [chapter for chapter in chapters if chapter[2] is not None]
    if len(floor_markers) < 2:
        return None
    targets = [index for index, chapter in enumerate(chapters) if chapter[2] == floor]
    if len(targets) != 1 or targets[0] + 1 >= len(chapters):
        return None

    index = targets[0]
    start, start_label, _ = chapters[index]
    end, end_label, _ = chapters[index + 1]
    time_ms = (end - start) * 1000
    if not _valid_ms(time_ms):
        return None
    return OcrResult(
        time_ms=time_ms,
        confidence=0.90,
        matching_frames=2,
        observations=len(chapters),
        evidence_frame=f"description:{start_label}->{end_label}",
        roi="description_chapters",
        source="youtube-description-chapters",
    )


def extract_time_values(text: str) -> set[int]:
    """Return plausible durations in milliseconds from noisy OCR text.

    GC may render the timer as MM:SS, MM:SS.mmm or MM:SS:CC, where CC is
    centiseconds. The latter is not treated as an hours field because supported
    dungeon runs are bounded to twenty minutes.
    """
    normalized = text.translate(str.maketrans({
        "O": "0", "o": "0", "I": "1", "l": "1", "|": "1",
        "’": ":", "'": ":", "′": ":", "：": ":", ",": ".",
    }))
    found: set[int] = set()
    occupied: list[tuple[int, int]] = []

    fractional = re.compile(
        r"(?<!\d)(\d{1,2})\s*:\s*(\d{2})\s*([:.])\s*(\d{2,3})(?!\d)"
    )
    for match in fractional.finditer(normalized):
        minutes, seconds = map(int, match.group(1, 2))
        fraction = match.group(4)
        millis = int(fraction) * (10 if len(fraction) == 2 else 1)
        total = (minutes * 60 + seconds) * 1000 + millis
        if seconds < 60 and _valid_ms(total):
            found.add(total)
        occupied.append(match.span())

    def overlaps(start: int, end: int) -> bool:
        return any(start < right and end > left for left, right in occupied)

    for match in re.finditer(
            r"(?<!\d)(\d{1,2})\s*:\s*(\d{2})(?!\s*[:.]\s*\d)(?!\d)",
            normalized):
        if overlaps(*match.span()):
            continue
        minutes, seconds = map(int, match.groups())
        total = (minutes * 60 + seconds) * 1000
        if seconds < 60 and _valid_ms(total):
            found.add(total)
    for match in re.finditer(
            r"(?<!\d)(\d{1,2})\s*[mM]\s*(\d{1,2})\s*[sS]?(?!\d)",
            normalized):
        minutes, seconds = map(int, match.groups())
        total = (minutes * 60 + seconds) * 1000
        if seconds < 60 and _valid_ms(total):
            found.add(total)
    return found


def extract_compact_time_values(text: str) -> set[int]:
    """Parse a separator-free timer only after spatial digit isolation.

    Tesseract commonly drops the tiny colons in GCC's stylized timer. Keep this
    deliberately strict: the entire OCR result must be 4, 6 or 7 digits, which
    map to MMSS, MMSScc or MMSSmmm. Temporal consensus still decides whether
    the observation is safe to accept.
    """
    normalized = text.translate(str.maketrans({
        "O": "0", "o": "0", "I": "1", "l": "1", "|": "1",
    }))
    compact = re.sub(r"\s+", "", normalized)
    if not re.fullmatch(r"(?:\d{4}|\d{6}|\d{7})", compact):
        return set()
    minutes, seconds = int(compact[:2]), int(compact[2:4])
    if seconds >= 60:
        return set()
    millis = 0
    if len(compact) == 6:
        millis = int(compact[4:]) * 10
    elif len(compact) == 7:
        millis = int(compact[4:])
    time_ms = (minutes * 60 + seconds) * 1000 + millis
    return {time_ms} if _valid_ms(time_ms) else set()


def extract_times(text: str) -> set[int]:
    """Backward-compatible whole-second view used by unit tests."""
    return {time_ms // 1000 for time_ms in extract_time_values(text)}


def choose_consensus(observations: list[tuple[str, int]]) -> OcrResult | None:
    """Choose a whole-second time only when it occurs in nearby frames.

    This compatibility entry point retains the original six-second frame
    numbering contract. The video pipeline uses ``choose_frozen_consensus``.
    """
    frames_by_time: dict[int, set[str]] = defaultdict(set)
    counts: dict[int, int] = defaultdict(int)
    for frame, seconds in observations:
        time_ms = seconds * 1000
        if _valid_ms(time_ms):
            frames_by_time[seconds].add(frame)
            counts[seconds] += 1
    nearby_frames: dict[int, list[int]] = {}
    for seconds, frame_names in frames_by_time.items():
        numbers = sorted({int(frame) for frame in frame_names if frame.isdigit()})
        nearby_frames[seconds] = max(
            ([number for number in numbers if start <= number <= start + 3]
             for start in numbers), key=len, default=[]
        )
    ranked = sorted(frames_by_time, key=lambda value: (
        len(nearby_frames[value]), len(frames_by_time[value]), counts[value]
    ), reverse=True)
    if not ranked:
        return None
    winner = ranked[0]
    matching_frames = len(nearby_frames[winner])
    if matching_frames < 2:
        return None
    if len(ranked) > 1 and len(nearby_frames[ranked[1]]) == matching_frames:
        return None
    confidence = min(
        0.94,
        0.72 + (matching_frames - 2) * 0.05
        + min(counts[winner] - matching_frames, 3) * 0.02,
    )
    evidence_number = max(nearby_frames[winner])
    return OcrResult(
        winner * 1000, confidence, matching_frames, counts[winner],
        f"frame-{evidence_number:03d}",
        max(0, 75 - (evidence_number - 1) * 6),
    )


def _stable_sequence(observations: list[OcrObservation], max_gap: float,
                     minimum_span: float) -> list[OcrObservation]:
    """Return the newest sequence whose identical timer spans long enough."""
    ordered = sorted(observations, key=lambda item: item.seconds_from_end)
    sequences: list[list[OcrObservation]] = []
    current: list[OcrObservation] = []
    for observation in ordered:
        if not current or abs(
                observation.seconds_from_end - current[-1].seconds_from_end
        ) <= max_gap:
            current.append(observation)
        else:
            sequences.append(current)
            current = [observation]
    if current:
        sequences.append(current)
    qualified = [sequence for sequence in sequences if len(sequence) >= 2 and (
        max(item.seconds_from_end for item in sequence)
        - min(item.seconds_from_end for item in sequence)
    ) >= minimum_span]
    return min(
        qualified,
        key=lambda sequence: min(item.seconds_from_end for item in sequence),
        default=[],
    )


def choose_frozen_consensus(observations: list[OcrObservation],
                            sample_interval: float) -> OcrResult | None:
    """Accept a timer only after it remains frozen across temporal frames."""
    by_time: dict[int, list[OcrObservation]] = defaultdict(list)
    for observation in observations:
        if _valid_ms(observation.time_ms):
            by_time[observation.time_ms].append(observation)
    stable: dict[int, list[OcrObservation]] = {}
    max_gap = sample_interval * 1.6
    # A running MM:SS timer can repeat inside a one-second bucket. Requiring
    # almost two seconds prevents that normal tick from looking "frozen".
    minimum_span = max(1.8, sample_interval)
    for time_ms, values in by_time.items():
        sequence = _stable_sequence(values, max_gap, minimum_span)
        if sequence:
            stable[time_ms] = sequence
    if len(stable) == 1:
        winner, sequence = next(iter(stable.items()))
        return _consensus_result(winner, sequence, len(by_time[winner]))

    # Fractional digits are the least stable part of the stylized GC timer.
    # If exact millisecond readings disagree, allow a second-level cluster only
    # when it is frozen for the same temporal span. A normally ticking timer
    # cannot pass because it stays in a second bucket for less than one second.
    by_second: dict[int, list[OcrObservation]] = defaultdict(list)
    for observation in observations:
        if _valid_ms(observation.time_ms):
            by_second[observation.time_ms // 1000].append(observation)
    second_stable = {
        second: sequence
        for second, values in by_second.items()
        if (sequence := _stable_sequence(values, max_gap, minimum_span))
    }
    if len(second_stable) != 1:
        return None
    sequence = next(iter(second_stable.values()))
    ranked_values = sorted(item.time_ms for item in sequence)
    median = ranked_values[len(ranked_values) // 2]
    representative = max(
        sequence,
        key=lambda item: (-abs(item.time_ms - median), item.confidence,
                          -item.seconds_from_end),
    )
    return _consensus_result(
        representative.time_ms, sequence, len(sequence), confidence_cap=0.86
    )


def _consensus_result(winner: int, sequence: list[OcrObservation],
                      observations: int, confidence_cap: float = 0.98) -> OcrResult:
    """Build an auditable result from a temporally stable OCR sequence."""
    best = max(sequence, key=lambda item: (
        -abs(item.time_ms - winner), item.confidence, -item.seconds_from_end
    ))
    average_engine_confidence = sum(
        item.confidence for item in sequence
    ) / len(sequence)
    confidence = min(
        confidence_cap,
        max(0.72, average_engine_confidence * 0.75 + 0.20
            + min(len(sequence) - 2, 4) * 0.015),
    )
    return OcrResult(
        winner, confidence, len(sequence), observations,
        best.frame_id, int(round(best.seconds_from_end)), best.evidence_path,
        best.frame_id.split("-", 1)[0],
    )


def _run(command: list[str], timeout: int = 240) -> subprocess.CompletedProcess[str]:
    deadline = _deadline.get()
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("ocr_video_budget_exhausted")
        timeout = min(timeout, remaining)
    # Each video already has a worker. Nested OpenMP pools oversubscribe CPUs.
    environment = dict(os.environ, OMP_THREAD_LIMIT="1", OMP_NUM_THREADS="1")
    try:
        return subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=timeout,
            env=environment,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise RuntimeError(detail[-1200:]) from error


def _require_tools() -> None:
    missing = [
        name for name in ("yt-dlp", "ffmpeg", "tesseract")
        if shutil.which(name) is None
    ]
    try:
        import cv2  # noqa: F401
    except ImportError:
        missing.append("opencv-python-headless")
    if missing:
        raise RuntimeError("missing OCR tools: " + ", ".join(missing))


def _download_excerpt(video_url: str, destination: Path,
                      window_seconds: int = DOWNLOAD_WINDOW_SECONDS) -> Path:
    if not 30 <= window_seconds <= 900:
        raise ValueError("Lookback must be between 30 and 900 seconds")
    output = destination / "video.%(ext)s"
    command = [
        "yt-dlp", "--no-playlist", "--no-warnings", "--quiet",
        "--js-runtimes", "node", "--remote-components", "ejs:npm",
        "--impersonate", "chrome", "-f", "bv*",
        "-S", "res:720,+size,+br",
        "--download-sections", f"*-{window_seconds}-inf",
        "-o", str(output),
    ]
    if os.environ.get("YOUTUBE_USE_PO_TOKEN") == "1":
        command.extend(["--extractor-args", "youtube:player_client=mweb"])
        browser_path = os.environ.get("YOUTUBE_PO_BROWSER_PATH")
        if browser_path:
            command.extend([
                "--extractor-args",
                f"youtubepot-wpc:browser_path={browser_path}",
            ])
    cookies_file = os.environ.get("YOUTUBE_COOKIES_FILE")
    if cookies_file:
        command.extend(["--cookies", cookies_file])
    command.append(video_url)
    _run(command, timeout=360)
    videos = [path for path in destination.glob("video.*")
              if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
    if not videos:
        raise RuntimeError("yt-dlp did not create a video file")
    return videos[0]


def _video_duration(video: Path) -> float:
    result = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=noprint_wrappers=1:nokey=1", str(video)], timeout=15)
    duration = float(result.stdout.strip())
    if not 0 < duration < 86400:
        raise ValueError("Invalid video duration")
    return duration


def _window_frames(video: Path, directory: Path, prefix: str,
                   start: float, duration: float, fps: float) -> list[Path]:
    if start < 0 or duration <= 0 or fps <= 0 or duration * fps > 181:
        raise ValueError("Invalid or excessive frame window")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-threads", "1",
          "-filter_threads", "1", "-ss", str(start), "-i", str(video),
          "-t", str(duration), "-vf", f"fps={fps},scale=1280:-2",
          "-frames:v", str(int(duration * fps) + 1),
          str(directory / f"{prefix}-%04d.png")], timeout=120)
    frames = sorted(directory.glob(f"{prefix}-*.png"))
    if not frames:
        raise RuntimeError("ffmpeg produced no inspection frames")
    return frames


def scout_video(video: Path, directory: Path, lookback: int = 300):
    """At most 60 full frames, no OCR. Return approximate excerpt timestamps."""
    from .visual import Sample
    if not 30 <= lookback <= 900:
        raise ValueError("Lookback must be between 30 and 900 seconds")
    duration = _video_duration(video)
    window = min(duration, lookback)
    start = duration - window
    fps = max(1 / window, min(0.2, 60 / window))
    frames = _window_frames(video, directory, "scout", start, window, fps)
    return [Sample(p, min(duration, start + i/fps)) for i, p in enumerate(frames)], duration


def _extract_frames(video: Path, destination: Path, prefix: str,
                    window_seconds: int, fps: int) -> list[Path]:
    pattern = destination / f"{prefix}-%04d.png"
    frame_limit = window_seconds * fps + 2
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-threads", "1", "-filter_threads", "1",
        "-sseof", f"-{window_seconds}", "-i", str(video),
        "-vf", f"fps={fps},scale=1280:-2", "-frames:v", str(frame_limit),
        str(pattern),
    ], timeout=240)
    return sorted(destination.glob(f"{prefix}-*.png"))


def roi_bounds(width: int, height: int,
               relative: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    """Convert a relative ROI to clamped pixel coordinates."""
    left, top, right, bottom = relative
    return (
        max(0, min(width, round(width * left))),
        max(0, min(height, round(height * top))),
        max(0, min(width, round(width * right))),
        max(0, min(height, round(height * bottom))),
    )


def _isolate_digit_band(pixels):
    """Locate one horizontal glyph band and normalize it for timer OCR."""
    import cv2

    height, width = pixels.shape[:2]
    gradient = cv2.convertScaleAbs(
        cv2.Sobel(pixels, cv2.CV_32F, 1, 0, ksize=3)
    )
    _, edges = cv2.threshold(
        gradient, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    kernel_width = max(9, width // 16)
    joined = cv2.morphologyEx(
        edges, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 3)),
    )
    contours, _ = cv2.findContours(
        joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    candidates = []
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        if (box_width >= width * 0.18 and box_height >= height * 0.08
                and box_height <= height * 0.80
                and box_width / max(1, box_height) >= 1.4):
            center_penalty = abs((y + box_height / 2) - height / 2) / height
            candidates.append((
                box_width * box_height * (1 - center_penalty * 0.55),
                x, y, box_width, box_height,
            ))
    if candidates:
        _, x, y, box_width, box_height = max(candidates)
        pad_y = max(4, box_height // 3)
        top, bottom = max(0, y-pad_y), min(height, y+box_height+pad_y)
        # A contour may cover just one digit. Use it only to locate the text
        # baseline and preserve the calibrated ROI's complete horizontal line.
        band = pixels[top:bottom, :]
    else:
        # The calibrated ROI is already tight. A centered fallback still
        # removes the HUD edges that most often confuse line segmentation.
        top, bottom = height // 8, height - height // 8
        band = pixels[top:bottom, :]

    scale = max(1.0, 160 / max(1, band.shape[0]))
    band = cv2.resize(
        band, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
    )
    band = cv2.copyMakeBorder(
        band, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255
    )
    _, binary = cv2.threshold(
        band, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    # Tesseract is more reliable with dark glyphs on a light field.
    if cv2.countNonZero(binary) < binary.size / 2:
        binary = cv2.bitwise_not(binary)
    return band, binary


def _preprocess_roi(frame: Path, destination: Path,
                    roi_name: str) -> list[Path]:
    """Crop the timer and create contrast-safe variants with OpenCV."""
    import cv2

    image = cv2.imread(str(frame))
    if image is None:
        raise RuntimeError(f"OpenCV could not read {frame.name}")
    height, width = image.shape[:2]
    if roi_name.startswith("anchor_"):
        from .visual import locate_anchor
        match = locate_anchor(image, _anchors.get()[roi_name])
        if match is None:
            return []
        left, top, right, bottom = match["roi"]
    else:
        left, top, right, bottom = roi_bounds(width, height, TIMER_ROIS[roi_name])
    crop = image[top:bottom, left:right]
    if crop.size == 0:
        raise RuntimeError(f"empty OCR ROI for {frame.name}")
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    # CLAHE retains thin timer strokes when attacks make a large part of the
    # crop bright. Global Otsu alone overexposed those frames in run 68.
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    blurred = cv2.GaussianBlur(clahe, (0, 0), 1.0)
    sharpened = cv2.addWeighted(clahe, 1.7, blurred, -0.7, 0)
    _, otsu = cv2.threshold(
        sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    adaptive = cv2.adaptiveThreshold(
        sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 7,
    )
    # First isolate the horizontal glyph band. This removes HUD labels and
    # effects before OCR and makes the fast pass useful even when tiny colons
    # disappear. The original variants remain available to exhaustive scans.
    digit_band, digit_binary = _isolate_digit_band(sharpened)
    variants = (("digits", digit_band), ("digits-binary", digit_binary),
                ("clahe", sharpened), ("adaptive", adaptive),
                ("otsu", otsu), ("inverse", cv2.bitwise_not(otsu)))
    paths: list[Path] = []
    for variant_name, pixels in variants:
        output = destination / f"{frame.stem}-{roi_name}-{variant_name}.png"
        if not cv2.imwrite(str(output), pixels):
            raise RuntimeError(f"OpenCV could not write {output.name}")
        paths.append(output)
    return paths


def _parse_tesseract_tsv(output: str) -> tuple[str, float]:
    words: list[str] = []
    confidences: list[float] = []
    for line in output.splitlines()[1:]:
        columns = line.split("\t")
        if len(columns) < 12 or not columns[11].strip():
            continue
        words.append(columns[11].strip())
        try:
            confidence = float(columns[10])
        except ValueError:
            continue
        if confidence >= 0:
            confidences.append(confidence / 100)
    return " ".join(words), (
        sum(confidences) / len(confidences) if confidences else 0.0
    )


def _read_timer_frame(frame: Path, destination: Path, roi_name: str,
                      seconds_from_end: float,
                      exhaustive: bool = False) -> list[OcrObservation]:
    variants = _preprocess_roi(frame, destination, roi_name)
    selected = variants if exhaustive else variants[:1]
    page_modes = (7, 13) if exhaustive else (7,)
    best_by_time: dict[int, OcrObservation] = {}
    for processed in selected:
        for page_mode in page_modes:
            try:
                result = _run([
                    "tesseract", str(processed), "stdout", "--psm",
                    str(page_mode), "-l", "eng", "-c",
                    "tessedit_char_whitelist=0123456789:.", "tsv",
                ], timeout=20)
            except RuntimeError as error:
                # Tesseract may exit non-zero for an empty/tiny connected
                # component even though the frame itself is valid. That means
                # "no observation", not a technical failure for the video.
                detail = str(error)
                harmless = (
                    "level\tpage_num\tblock_num" in detail
                    or "Image too small to scale" in detail
                    or "Line cannot be recognized" in detail
                    or "Empty page" in detail
                )
                if harmless:
                    continue
                raise
            text, confidence = _parse_tesseract_tsv(result.stdout)
            values = extract_time_values(text)
            if "-digits" in processed.stem:
                values.update(extract_compact_time_values(text))
            if os.environ.get("GC_OCR_DEBUG_TEXT") == "1" and text.strip():
                print("OCR_TEXT " + json.dumps({
                    "frame": frame.stem,
                    "roi": roi_name,
                    "variant": processed.stem.rsplit("-", 1)[-1],
                    "psm": page_mode,
                    "text": text,
                    "values_ms": sorted(values),
                }, ensure_ascii=True), file=sys.stderr, flush=True)
            for time_ms in values:
                observation = OcrObservation(
                    f"{roi_name}-{frame.stem}", time_ms, seconds_from_end,
                    confidence, str(processed),
                )
                previous = best_by_time.get(time_ms)
                if previous is None or observation.confidence > previous.confidence:
                    best_by_time[time_ms] = observation
    return list(best_by_time.values())


def _scan_frames(frames: list[Path], destination: Path, roi_name: str,
                 window_seconds: int, fps: int,
                 exhaustive: bool = False, seconds_offset: float = 0) -> tuple[OcrResult | None, int]:
    observations: list[OcrObservation] = []
    total = len(frames)
    first_consensus_at: int | None = None
    consensus: OcrResult | None = None
    timeouts = 0
    for reverse_index, frame in enumerate(reversed(frames)):
        chronological_index = total - reverse_index - 1
        seconds_from_end = max(0.0, (total - chronological_index - 1) / fps) + seconds_offset
        try:
            observations.extend(_read_timer_frame(
                frame, destination, roi_name, seconds_from_end, exhaustive
            ))
        except subprocess.TimeoutExpired:
            timeouts += 1
            if timeouts >= 3:
                raise RuntimeError("tesseract_repeated_timeout")
            continue
        consensus = choose_frozen_consensus(observations, 1 / fps)
        if consensus is not None and first_consensus_at is None:
            first_consensus_at = reverse_index
        # Inspect four additional seconds around a first match. This keeps the
        # backwards scan bounded while still surfacing conflicting readings.
        if (first_consensus_at is not None
                and reverse_index - first_consensus_at >= 4 * fps):
            return consensus, len(observations)
    if timeouts:
        # Preserve retryability rather than mislabel an incomplete scan as final.
        raise RuntimeError("tesseract_incomplete_scan_timeout")
    return choose_frozen_consensus(observations, 1 / fps), len(observations)


def _preserve_evidence(result: OcrResult, evidence_directory: Path | None,
                       evidence_name: str | None) -> OcrResult:
    if not result.evidence_image or evidence_directory is None:
        return result
    evidence_directory.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", evidence_name or "video")
    target = evidence_directory / f"{safe_name}-{result.time_ms}.png"
    shutil.copyfile(result.evidence_image, target)
    return OcrResult(
        result.time_ms, result.confidence, result.matching_frames,
        result.observations, result.evidence_frame,
        result.evidence_seconds_from_end,
        str(Path("ocr-evidence") / target.name), result.roi,
    )


def _preserve_diagnostic(directory: Path, evidence_directory: Path | None,
                         evidence_name: str | None) -> str | None:
    """Keep a compact ROI contact sheet when no timer reaches consensus."""
    if evidence_directory is None:
        return None
    import cv2

    candidates: list[Path] = []
    for roi_name in TIMER_ROIS:
        roi_candidates = sorted(directory.glob(f"dense-*-{roi_name}-clahe.png"))
        if not roi_candidates:
            roi_candidates = sorted(directory.glob(
                f"coarse-*-{roi_name}-clahe.png"
            ))
        if roi_candidates:
            count = min(4, len(roi_candidates))
            candidates.extend(roi_candidates[round(
                index * (len(roi_candidates) - 1) / max(1, count - 1)
            )] for index in range(count))
    if not candidates:
        return None
    count = min(12, len(candidates))
    indexes = [
        round(index * (len(candidates) - 1) / max(1, count - 1))
        for index in range(count)
    ]
    tiles = []
    for index in indexes:
        pixels = cv2.imread(str(candidates[index]), cv2.IMREAD_GRAYSCALE)
        if pixels is None:
            continue
        scale = 360 / pixels.shape[1]
        tile = cv2.resize(
            pixels, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
        )
        cv2.putText(
            tile, candidates[index].stem.rsplit("-clahe", 1)[0], (8, 22),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, 180, 1, cv2.LINE_AA,
        )
        tiles.append(tile)
    if not tiles:
        return None
    tile_height = max(tile.shape[0] for tile in tiles)
    normalized = [cv2.copyMakeBorder(
        tile, 0, tile_height - tile.shape[0], 0, 0,
        cv2.BORDER_CONSTANT, value=0,
    ) for tile in tiles]
    while len(normalized) % 4:
        normalized.append(normalized[-1] * 0)
    rows = [cv2.hconcat(normalized[index:index + 4])
            for index in range(0, len(normalized), 4)]
    contact_sheet = cv2.vconcat(rows)
    evidence_directory.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", evidence_name or "video")
    target = evidence_directory / f"{safe_name}-no-consensus.png"
    if not cv2.imwrite(str(target), contact_sheet):
        raise RuntimeError(f"OpenCV could not write {target.name}")
    return str(Path("ocr-evidence") / target.name)


def read_video_time(video_url: str, evidence_directory: Path | None = None,
                    evidence_name: str | None = None) -> OcrResult | None:
    token = _deadline.set(time.monotonic() + VIDEO_BUDGET_SECONDS)
    try:
        return _read_video_time(video_url, evidence_directory, evidence_name)
    finally:
        _deadline.reset(token)


def _read_video_time(video_url: str, evidence_directory: Path | None = None,
                     evidence_name: str | None = None) -> OcrResult | None:
    """Find a stable completion timer using adaptive temporal and spatial OCR."""
    _require_tools()
    with tempfile.TemporaryDirectory(prefix="gc-radar-ocr-") as temporary:
        directory = Path(temporary)
        if os.environ.get("GC_OCR_VISUAL_EVENTS") == "1":
            return _read_event_video(video_url, directory, evidence_directory, evidence_name)
        video = _download_excerpt(video_url, directory)
        coarse_frames = _extract_frames(
            video, directory, "coarse", COARSE_WINDOW_SECONDS, COARSE_FPS
        )
        if evidence_directory is not None:
            from .visual import Sample, write_inspection
            write_inspection([Sample(p, i / COARSE_FPS) for i, p in enumerate(coarse_frames)],
                             evidence_directory, evidence_name or "video", [], max_frames=8)
        dense_frames: list[Path] | None = None
        for roi_name in TIMER_ROIS:
            result, sightings = _scan_frames(
                coarse_frames, directory, roi_name,
                COARSE_WINDOW_SECONDS, COARSE_FPS,
            )
            if result is not None:
                return _preserve_evidence(
                    result, evidence_directory, evidence_name
                )
            # A final timer must remain visible for at least two seconds. If a
            # one-frame-per-second pass saw no plausible digits at all, a dense
            # pass over the same ROI only multiplies cost without supporting a
            # frozen-time consensus.
            # One accidental number inside an effects-heavy frame used to
            # trigger hundreds of dense OCR calls. A real frozen timer must be
            # visible in at least two coarse frames before the expensive pass.
            if sightings < 2:
                continue
            if dense_frames is None:
                dense_frames = _extract_frames(
                    video, directory, "dense", DENSE_WINDOW_SECONDS, DENSE_FPS
                )
            result, _ = _scan_frames(
                dense_frames, directory, roi_name,
                DENSE_WINDOW_SECONDS, DENSE_FPS,
                exhaustive=sightings > 0,
            )
            if result is not None:
                return _preserve_evidence(
                    result, evidence_directory, evidence_name
                )
        _preserve_diagnostic(directory, evidence_directory, evidence_name)
        return None


def _read_event_video(video_url: str, directory: Path,
                      evidence_directory: Path | None, evidence_name: str | None):
    from .visual import load_anchors, propose_windows, write_inspection
    lookback = int(os.environ.get("GC_OCR_LOOKBACK_SECONDS", "300"))
    manifest = os.environ.get("GC_OCR_ANCHORS")
    anchors = load_anchors(Path(manifest) if manifest else None)
    video = _download_excerpt(video_url, directory, lookback)
    samples, duration = scout_video(video, directory, lookback)
    windows = propose_windows(samples, anchors, duration)
    if not windows:
        windows = [{"start": max(0, duration-20), "end": duration,
                    "reason": "fallback_tail", "anchors": [], "score": 0}]
    # Save full-frame evidence before OCR, including if the subsequent scan fails.
    if evidence_directory is not None:
        write_inspection(samples, evidence_directory, evidence_name or "video", windows)
    token = _anchors.set({"anchor_" + a.name: a for a in anchors})
    try:
        for index, window in enumerate(windows):
            start, length = window["start"], window["end"] - window["start"]
            frames = _window_frames(video, directory, f"event{index}", start, length, 1)
            roi_names = ["anchor_" + name for name in window["anchors"]] or list(TIMER_ROIS)
            for roi_name in roi_names:
                result, sightings = _scan_frames(frames, directory, roi_name,
                                                 length, 1, seconds_offset=duration-window["end"])
                if result:
                    return _preserve_evidence(result, evidence_directory, evidence_name)
                if sightings < 2:
                    continue
                dense = _window_frames(video, directory, f"dense-event{index}-{roi_name}", start, length, 2)
                result, _ = _scan_frames(dense, directory, roi_name, length, 2,
                                         exhaustive=True, seconds_offset=duration-window["end"])
                if result:
                    return _preserve_evidence(result, evidence_directory, evidence_name)
        return None
    finally:
        _anchors.reset(token)
