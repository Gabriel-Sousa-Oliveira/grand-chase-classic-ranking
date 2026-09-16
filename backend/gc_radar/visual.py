"""Bounded visual scouting. Scene changes propose windows, never prove a run."""
from __future__ import annotations

import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Sample:
    path: Path
    seconds: float  # Relative to the downloaded excerpt, not the original video.


@dataclass(frozen=True)
class Anchor:
    name: str
    template: object
    offset: tuple[float, float, float, float]  # dx, dy, width, height at template scale
    scales: tuple[float, ...] = (0.75, 1.0, 1.25)
    threshold: float = 0.9


def load_anchors(manifest: Path | None) -> list[Anchor]:
    import cv2
    if manifest is None:
        return []
    records = json.loads(manifest.read_text())["anchors"]
    if len(records) > 3:
        raise ValueError("At most three calibrated anchors per profile")
    result = []
    for item in records:
        if not item.get("enabled", False):
            continue
        name = item["name"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", name):
            raise ValueError("Invalid anchor name")
        template = cv2.imread(str(manifest.parent / item["image"]), cv2.IMREAD_GRAYSCALE)
        if template is None or min(template.shape) < 8 or template.std() < 5:
            raise ValueError(f"Missing, tiny or constant template: {name}")
        offset = tuple(float(x) for x in item["timer_offset"])
        scales = tuple(float(x) for x in item.get("scales", [0.75, 1, 1.25]))
        threshold = float(item.get("threshold", 0.9))
        if (len(offset) != 4 or not all(math.isfinite(x) for x in offset)
                or min(offset[2:]) <= 0 or not 0.8 <= threshold <= 1
                or not 1 <= len(scales) <= 5
                or any(not math.isfinite(s) or not 0.25 <= s <= 3 for s in scales)):
            raise ValueError(f"Invalid anchor settings: {name}")
        if any(a.name == name for a in result):
            raise ValueError("Duplicate anchor name")
        result.append(Anchor(name, template, offset, scales, threshold))
    return result


def locate_anchor(image, anchor: Anchor):
    """Return a tight timer ROI, rejecting ambiguous matches and clipped boxes."""
    import cv2
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape
    best = None
    for scale in anchor.scales:
        template = cv2.resize(anchor.template, None, fx=scale, fy=scale)
        th, tw = template.shape
        if th > height or tw > width or min(th, tw) < 8 or template.std() < 5:
            continue
        scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if not math.isfinite(score) or score < anchor.threshold:
            continue
        # A second equally plausible copy makes the anchor unsafe.
        scores[max(0, y-th):y+th+1, max(0, x-tw):x+tw+1] = -1
        if cv2.minMaxLoc(scores)[1] > score - 0.05:
            continue
        dx, dy, rw, rh = anchor.offset
        left, top = round(x + dx * scale), round(y + dy * scale)
        right, bottom = left + round(rw * scale), top + round(rh * scale)
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            continue
        if (right-left)*(bottom-top) > width*height*0.15:
            continue
        if best is None or score > best["score"]:
            best = {"name": anchor.name, "score": float(score),
                    "scale": scale, "roi": (left, top, right, bottom)}
    return best


def propose_windows(samples: list[Sample], anchors: list[Anchor], duration: float,
                    max_windows: int = 3) -> list[dict]:
    """Rank persistent anchor appearances and cuts followed by stable scenes."""
    import cv2
    if not 1 <= max_windows <= 3:
        raise ValueError("Choose one to three event windows")
    histograms, hits = [], []
    for sample in samples:
        image = cv2.imread(str(sample.path))
        if image is None:
            raise ValueError(f"Unreadable scout frame: {sample.path}")
        small = cv2.resize(image, (160, 90))
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256])
        histograms.append(cv2.normalize(hist, None).flatten())
        hits.append([a.name for a in anchors if locate_anchor(image, a)])
    changes = [0.0] + [float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA))
                        for a, b in zip(histograms, histograms[1:])]
    candidates = []
    for i in range(1, len(samples) - 1):
        stable_anchors = sorted(set(hits[i]) & set(hits[i+1]))
        returns_after_flash = i >= 2 and cv2.compareHist(
            histograms[i-2], histograms[i], cv2.HISTCMP_BHATTACHARYYA) <= 0.12
        scene = changes[i] >= 0.45 and changes[i+1] <= 0.12 and not returns_after_flash
        if not stable_anchors and not scene:
            continue
        # Include the prior sample: the cut happened somewhere in this interval.
        start = max(0.0, samples[i-1].seconds - 2)
        end = min(duration, samples[i].seconds + 10)
        candidates.append({"start": start, "end": end,
                           "reason": "anchor" if stable_anchors else "scene_change",
                           "anchors": stable_anchors,
                           "score": 1 + len(stable_anchors) if stable_anchors else changes[i]})
    chosen = []
    for candidate in sorted(candidates, key=lambda w: w["score"], reverse=True):
        if candidate["end"] <= candidate["start"]:
            continue
        if any(candidate["start"] < w["end"] and candidate["end"] > w["start"] for w in chosen):
            continue
        chosen.append(candidate)
        if len(chosen) >= max_windows:
            break
    return sorted(chosen, key=lambda w: w["start"])


def annotated_grid(image, label: str):
    """Keep full resolution; labels refer to pixels in this exact frame."""
    import cv2
    result = image.copy()
    h, w = result.shape[:2]
    for x in range(0, w, max(1, w // 8)):
        cv2.line(result, (x, 0), (x, h-1), (80, 170, 80), 1)
        cv2.putText(result, f"x={x}", (x+2, 36), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1)
    for y in range(0, h, max(1, h // 6)):
        cv2.line(result, (0, y), (w-1, y), (80, 170, 80), 1)
        cv2.putText(result, f"y={y}", (2, min(h-5, y+18)), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1)
    cv2.rectangle(result, (0, h-28), (w, h), (0, 0, 0), -1)
    cv2.putText(result, label[:120], (5, h-9), cv2.FONT_HERSHEY_SIMPLEX, .48, (255, 255, 255), 1)
    return result


def write_inspection(samples: list[Sample], directory: Path, name: str,
                     windows: list[dict], max_frames: int = 12) -> Path:
    import cv2
    import numpy as np
    directory.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    indexes = {round(i*(len(samples)-1)/max(1, min(max_frames, len(samples))-1))
               for i in range(min(max_frames, len(samples)))}
    # Prioritize event frames as well as evenly spaced coverage.
    for window in windows:
        if samples:
            indexes.add(min(range(len(samples)), key=lambda i: abs(samples[i].seconds-window["start"]-5)))
    rows, tiles = [], []
    for index in sorted(indexes):
        sample = samples[index]
        image = cv2.imread(str(sample.path))
        if image is None:
            raise ValueError(f"Unreadable frame: {sample.path}")
        grid = annotated_grid(image, f"{safe} | excerpt +{sample.seconds:.1f}s | {image.shape[1]}x{image.shape[0]}")
        target = directory / f"{safe}-frame-{index:03d}.jpg"
        raw = directory / f"{safe}-frame-{index:03d}-raw.png"
        shutil.copyfile(sample.path, raw)
        if not cv2.imwrite(str(target), grid):
            raise RuntimeError("Cannot save inspection frame")
        # Black letterbox preserves aspect ratio in mosaics.
        tile = np.zeros((300, 480, 3), dtype=np.uint8)
        ratio = min(480/image.shape[1], 300/image.shape[0])
        resized = cv2.resize(grid, None, fx=ratio, fy=ratio)
        tile[:resized.shape[0], :resized.shape[1]] = resized
        cv2.rectangle(tile, (0, 274), (480, 300), (0, 0, 0), -1)
        cv2.putText(tile, f"{safe[:40]} | +{sample.seconds:.1f}s", (6, 292),
                    cv2.FONT_HERSHEY_SIMPLEX, .48, (255, 255, 255), 1)
        tiles.append(tile)
        rows.append({"image": target.name, "raw_image": raw.name, "seconds_in_excerpt": sample.seconds,
                     "width": image.shape[1], "height": image.shape[0]})
    manifest = directory / f"{safe}-inspection.json"
    manifest.write_text(json.dumps({"video": name, "timestamps": "relative_to_excerpt_approximate",
                                   "windows": windows, "frames": rows}, indent=2))
    if tiles:
        while len(tiles) % 3:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[i:i+3]) for i in range(0, len(tiles), 3)])
        if not cv2.imwrite(str(directory / f"{safe}-mosaic.jpg"), sheet):
            raise RuntimeError("Cannot save inspection mosaic")
    return manifest
