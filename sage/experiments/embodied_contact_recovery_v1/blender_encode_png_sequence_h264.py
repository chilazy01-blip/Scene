#!/usr/bin/env python3
"""Encode a numbered PNG sequence with Blender's bundled FFmpeg."""

from __future__ import annotations

from pathlib import Path
import sys

import bpy


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :]
    if len(argv) != 5:
        raise RuntimeError("expected frames_dir output.mp4 fps width height")
    frames_dir = Path(argv[0])
    output = Path(argv[1])
    fps, width, height = map(int, argv[2:])
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        raise RuntimeError("no PNG frames found")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    editor = scene.sequence_editor_create()
    strip = editor.sequences.new_image(
        "G1 cup task frames",
        str(frames[0]),
        channel=1,
        frame_start=1,
    )
    for path in frames[1:]:
        strip.elements.append(path.name)
    strip.frame_final_duration = len(frames)

    scene.frame_start = 1
    scene.frame_end = len(frames)
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.render.fps_base = 1.0
    scene.render.use_sequencer = True
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    scene.render.ffmpeg.audio_codec = "NONE"
    scene.render.filepath = str(output)
    scene.render.use_file_extension = False
    bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
