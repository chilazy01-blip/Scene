"""Transcode the replay to browser-compatible H.264/yuv420p and verify decoding."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from .common import RUN_ROOT, sha256, write_json


def transcode(run_root: Path) -> dict:
    import av

    replay = run_root / "trajectory_01/replay"
    source = replay / "generated_scene_full_replay_4x_mp4v.mp4"
    output = replay / "generated_scene_full_replay_4x_h264.mp4"
    temporary = replay / "generated_scene_full_replay_4x_h264.partial.mp4"
    source_container = av.open(str(source))
    source_stream = source_container.streams.video[0]
    rate = source_stream.average_rate or 10
    target_container = av.open(str(temporary), mode="w", options={"movflags": "+faststart"})
    target_stream = target_container.add_stream("libx264", rate=rate)
    target_stream.width = source_stream.codec_context.width
    target_stream.height = source_stream.codec_context.height
    target_stream.pix_fmt = "yuv420p"
    target_stream.options = {"crf": "20", "preset": "medium"}
    encoded = 0
    try:
        for frame in source_container.decode(source_stream):
            for packet in target_stream.encode(frame):
                target_container.mux(packet)
            encoded += 1
        for packet in target_stream.encode():
            target_container.mux(packet)
    finally:
        source_container.close()
        target_container.close()
    temporary.replace(output)

    verified = 0
    probe = av.open(str(output))
    stream = probe.streams.video[0]
    codec = stream.codec_context.name
    profile = stream.codec_context.profile
    pixel_format = stream.codec_context.format.name
    width = stream.codec_context.width
    height = stream.codec_context.height
    for _frame in probe.decode(stream):
        verified += 1
    duration_s = float(probe.duration / av.time_base) if probe.duration is not None else None
    probe.close()
    if verified != encoded or codec != "h264" or pixel_format != "yuv420p":
        raise RuntimeError(
            f"H.264 verification failed: {verified=}, {encoded=}, {codec=}, {pixel_format=}"
        )
    report = {
        "schema": "embodied-generated-scene-video-transcode/v1",
        "source": str(source),
        "source_sha256": sha256(source),
        "output": str(output),
        "output_sha256": sha256(output),
        "codec": codec,
        "profile": profile,
        "pixel_format": pixel_format,
        "width": width,
        "height": height,
        "fps": float(rate),
        "frames_encoded": encoded,
        "frames_fully_decoded": verified,
        "duration_s": duration_s,
        "faststart_requested": True,
    }
    write_json(replay / "TRANSCODE.json", report)
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    args = parser.parse_args(argv)
    print(transcode(args.run_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

