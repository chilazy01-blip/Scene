#!/usr/bin/env python3
"""Encode the mug pick-and-place frames as browser-compatible H.264."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import struct
import sys

import numpy as np
from PIL import Image

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None


def read_frame(path: Path) -> np.ndarray | None:
    if cv2 is not None:
        return cv2.imread(str(path), cv2.IMREAD_COLOR)
    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGB"))
    except (OSError, ValueError):
        return None


def resize_thumbnail(image: np.ndarray) -> np.ndarray:
    if cv2 is not None:
        return cv2.resize(image, (320, 240))
    return np.asarray(
        Image.fromarray(image).resize((320, 240), Image.Resampling.LANCZOS)
    )


def write_png(path: Path, image: np.ndarray) -> None:
    if cv2 is not None:
        if not cv2.imwrite(str(path), image):
            raise RuntimeError(f"failed to write image: {path}")
        return
    Image.fromarray(image).save(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def move_mp4_index_to_front(path: Path) -> None:
    """Relocate a trailing MP4 moov atom and repair chunk offsets."""

    data = path.read_bytes()
    atoms = []
    offset = 0
    while offset < len(data):
        if offset + 8 > len(data):
            raise RuntimeError("truncated MP4 atom header")
        size = struct.unpack_from(">I", data, offset)[0]
        atom_type = data[offset + 4 : offset + 8]
        if size < 8 or offset + size > len(data):
            raise RuntimeError("invalid MP4 atom size")
        atoms.append((offset, size, atom_type))
        offset += size
    moov_rows = [row for row in atoms if row[2] == b"moov"]
    mdat_rows = [row for row in atoms if row[2] == b"mdat"]
    if len(moov_rows) != 1 or len(mdat_rows) != 1:
        raise RuntimeError("expected one moov and one mdat atom")
    moov_offset, moov_size, _ = moov_rows[0]
    mdat_offset, _, _ = mdat_rows[0]
    if moov_offset < mdat_offset:
        return

    moov = bytearray(data[moov_offset : moov_offset + moov_size])
    chunk_table_count = 0
    for tag, width in ((b"stco", 4), (b"co64", 8)):
        search_from = 0
        while True:
            tag_offset = moov.find(tag, search_from)
            if tag_offset < 0:
                break
            atom_start = tag_offset - 4
            atom_size = struct.unpack_from(">I", moov, atom_start)[0]
            entry_count = struct.unpack_from(">I", moov, atom_start + 12)[0]
            entries_start = atom_start + 16
            if entries_start + width * entry_count != atom_start + atom_size:
                raise RuntimeError("unexpected MP4 chunk-offset table layout")
            format_code = ">I" if width == 4 else ">Q"
            for index in range(entry_count):
                entry_offset = entries_start + width * index
                value = struct.unpack_from(format_code, moov, entry_offset)[0]
                struct.pack_into(format_code, moov, entry_offset, value + moov_size)
            chunk_table_count += 1
            search_from = atom_start + atom_size
    if chunk_table_count == 0:
        raise RuntimeError("MP4 moov atom has no chunk-offset table")

    ftyp_rows = [row for row in atoms if row[2] == b"ftyp"]
    if len(ftyp_rows) != 1 or ftyp_rows[0][0] != 0:
        raise RuntimeError("MP4 ftyp atom is missing or not first")
    ftyp_size = ftyp_rows[0][1]
    remainder = data[ftyp_size:moov_offset] + data[moov_offset + moov_size :]
    temporary = path.with_suffix(".faststart.tmp.mp4")
    temporary.write_bytes(data[:ftyp_size] + moov + remainder)
    temporary.replace(path)


def main() -> None:
    output = Path(sys.argv[1])
    frames_dir = output / "frames"
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        raise RuntimeError("no Blender frames found")
    render = json.loads((frames_dir / "RENDER.json").read_text())
    if len(frames) != int(render["frames"]):
        raise RuntimeError(
            f"frame count mismatch: found {len(frames)}, expected {render['frames']}"
        )
    first = read_frame(frames[0])
    if first is None:
        raise RuntimeError(f"invalid first frame: {frames[0]}")
    height, width = first.shape[:2]
    fps = int(render["fps"])
    report_path = output / "REPORT.json"
    report = json.loads(report_path.read_text())
    physics_contact_demo = bool(report.get("physics", {}).get("executed", False))
    full_pick_place_demo = bool(
        report.get("acceptance", {}).get("full_pick_place_claimed", False)
    )
    video = output / (
        "bedroom_g1_cup_pick_place_physics_h264.mp4"
        if full_pick_place_demo
        else (
            "bedroom_g1_cup_friction_lift_hold_h264.mp4"
            if physics_contact_demo
            else "bedroom_g1_cup_pick_place_h264.mp4"
        )
    )
    blender = Path(
        os.environ.get(
            "SAGE_BLENDER_BIN",
            "/data/wsj/tools/blender-4.3.2-linux-x64/blender",
        )
    )
    blender_encoder = Path(__file__).with_name("blender_encode_png_sequence_h264.py")
    subprocess.run(
        [
            str(blender),
            "-b",
            "--python",
            str(blender_encoder),
            "--",
            str(frames_dir),
            str(video),
            str(fps),
            str(width),
            str(height),
        ],
        check=True,
    )
    move_mp4_index_to_front(video)
    thumbs = []
    phases = report.get("phase_times_s", {})
    if all(name in phases for name in ("grasp_open", "grasp_closed", "lift", "place")):
        sample_indices = {
            0,
            int(round(float(phases["grasp_open"]) * fps)),
            int(round(float(phases["grasp_closed"]) * fps)),
            int(round(float(phases["lift"]) * fps)),
            int(round(float(phases["place"]) * fps)),
            len(frames) - 1,
        }
    else:
        sample_indices = set(np.linspace(0, len(frames) - 1, 6, dtype=int).tolist())
    for index, path in enumerate(frames):
        image = read_frame(path)
        if image is None or image.shape != first.shape:
            raise RuntimeError(f"invalid frame: {path}")
        if index in sample_indices:
            thumbs.append(resize_thumbnail(image))
    write_png(
        output / "contact_sheet.png",
        np.vstack([np.hstack(thumbs[:3]), np.hstack(thumbs[3:6])]),
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
        "faststart_moov_before_mdat": True,
        "render_strategy": render.get("render_strategy"),
        "background_compositing_used": render.get(
            "background_compositing_used", False
        ),
        "synthetic_video_interpolation_used": render.get(
            "synthetic_video_interpolation_used", False
        ),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["video"], indent=2))


if __name__ == "__main__":
    main()
