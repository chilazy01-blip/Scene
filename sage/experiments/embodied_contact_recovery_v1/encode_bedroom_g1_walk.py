#!/usr/bin/env python3
"""Encode Blender PNG frames as a browser-compatible H.264 delivery."""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path
import sys

import av
import cv2
import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    output = Path(sys.argv[1])
    frames_dir = output / "frames"
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        raise RuntimeError("no Blender frames found")
    first = cv2.imread(str(frames[0]), cv2.IMREAD_COLOR)
    height, width = first.shape[:2]
    render = json.loads((frames_dir / "RENDER.json").read_text())
    fps = int(render["fps"])
    video = output / "full_bedroom_g1_walk_h264.mp4"
    container = av.open(str(video), "w", format="mp4", options={"movflags": "+faststart"})
    stream = container.add_stream("libx264", rate=fps)
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": "18", "preset": "medium", "profile": "high"}
    thumbs = []
    sample_indices = set(np.linspace(0, len(frames) - 1, 6, dtype=int).tolist())
    try:
        for index, path in enumerate(frames):
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None or image.shape != first.shape:
                raise RuntimeError(f"invalid frame: {path}")
            frame = av.VideoFrame.from_ndarray(image, format="bgr24")
            frame.pts = index
            frame.time_base = Fraction(1, fps)
            for packet in stream.encode(frame):
                container.mux(packet)
            if index in sample_indices:
                thumbs.append(cv2.resize(image, (320, 240)))
    finally:
        for packet in stream.encode():
            container.mux(packet)
        container.close()
    cv2.imwrite(
        str(output / "contact_sheet.png"),
        np.vstack([np.hstack(thumbs[:3]), np.hstack(thumbs[3:6])]),
    )
    report_path = output / "REPORT.json"
    report = json.loads(report_path.read_text())
    report["acceptance"]["visual_demo_generated"] = True
    report["integration"]["background_compositing_used"] = bool(
        render.get("background_compositing_used", False)
    )
    report["video"] = {
        "path": str(video),
        "sha256": sha256(video),
        "bytes": video.stat().st_size,
        "codec": "h264/yuv420p",
        "resolution": [width, height],
        "fps": fps,
        "frames": len(frames),
        "duration_s": len(frames) / fps,
        "source_frames": render.get("source_frames"),
        "render_strategy": render.get("render_strategy"),
        "synthetic_motion_interpolation_used": render.get(
            "synthetic_motion_interpolation_used"
        ),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["video"], indent=2))


if __name__ == "__main__":
    main()
