"""Generate annotated full-frame surveys without Tesseract or database writes.

python -m gc_radar.inspect_frames --video-dir ./videos --output ./survey --limit 25
python -m gc_radar.inspect_frames --urls-file urls.txt --output ./survey --limit 25
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from .ocr import _deadline, _download_excerpt, scout_video
from .visual import load_anchors, propose_windows, write_inspection
from .youtube import extract_video_id


def survey(items, output: Path, lookback: int = 300, anchors=None) -> dict:
    import cv2
    import numpy as np
    if not 1 <= len(items) <= 30 or not 30 <= lookback <= 900:
        raise ValueError("Choose 1-30 videos and a 30-900 second lookback")
    output.mkdir(parents=True, exist_ok=True)
    report = {"lookback_seconds": lookback, "ocr_executed": False, "videos": []}
    tiles = []
    for index, item in enumerate(items):
        token = _deadline.set(time.monotonic() + 300)
        name = f"{index+1:02d}"
        try:
            with tempfile.TemporaryDirectory(prefix="gc-survey-") as tmp:
                directory = Path(tmp)
                if isinstance(item, Path):
                    video = item.resolve()
                    name += "-" + item.stem
                else:
                    video_id = extract_video_id(item)
                    name += "-" + video_id
                    video = _download_excerpt(f"https://www.youtube.com/watch?v={video_id}", directory, lookback)
                samples, duration = scout_video(video, directory, lookback)
                windows = propose_windows(samples, anchors or [], duration)
                manifest = write_inspection(samples, output, name, windows)
                data = json.loads(manifest.read_text())
                target_time = windows[0]["start"] + 5 if windows else duration / 2
                chosen = min(data["frames"], key=lambda f: abs(f["seconds_in_excerpt"] - target_time))
                image = cv2.imread(str(output / chosen["image"]))
                tile = np.zeros((270, 480, 3), dtype=np.uint8)
                scale = min(480 / image.shape[1], 270 / image.shape[0])
                small = cv2.resize(image, None, fx=scale, fy=scale)
                tile[:small.shape[0], :small.shape[1]] = small
                cv2.rectangle(tile, (0, 244), (480, 270), (0, 0, 0), -1)
                cv2.putText(tile, f"{name[:40]} | +{chosen['seconds_in_excerpt']:.1f}s",
                            (6, 262), cv2.FONT_HERSHEY_SIMPLEX, .48, (255, 255, 255), 1)
                tiles.append(tile)
                report["videos"].append({"input": str(item), "manifest": manifest.name,
                                         "representative": chosen, "windows": windows})
        except Exception as error:
            report["videos"].append({"input": str(item), "error": str(error)[:1200]})
        finally:
            _deadline.reset(token)
        (output / "survey.json").write_text(json.dumps(report, indent=2))
        print(f"Survey {index+1}/{len(items)}: {name}", flush=True)
    if tiles:
        while len(tiles) % 5:
            tiles.append(np.zeros_like(tiles[0]))
        mosaic = np.vstack([np.hstack(tiles[i:i+5]) for i in range(0, len(tiles), 5)])
        if not cv2.imwrite(str(output / "survey-mosaic.jpg"), mosaic):
            raise RuntimeError("Cannot write survey mosaic")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--video-dir", type=Path)
    source.add_argument("--urls-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--lookback", type=int, default=300)
    parser.add_argument("--anchors", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        parser.error("--limit must be between 1 and 30")
    if args.video_dir:
        items = sorted(p for p in args.video_dir.iterdir() if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"})
    else:
        items = list(dict.fromkeys(line.strip() for line in args.urls_file.read_text().splitlines()
                                   if line.strip() and not line.lstrip().startswith("#")))
    if not items:
        parser.error("No videos supplied")
    result = survey(items[:args.limit], args.output, args.lookback, load_anchors(args.anchors))
    if all("error" in video for video in result["videos"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
