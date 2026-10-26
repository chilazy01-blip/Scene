"""Decode the camera-corrected negative video, no physics or success inference."""

import argparse
from pathlib import Path
import numpy as np
from .closeout import check
from .report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    import av
    import cv2

    video = root / "version_03/diagnostic_video"
    manifest = read_bound_json(video / "MANIFEST.json")
    for b in manifest["files"].values():
        check(b)
    for key in ("report", "trace", "model", "scene", "case", "implementation"):
        check(manifest[key])
    assert not manifest["task_passed"] and manifest["new_physics_steps"] == 0
    output = root / "version_03_video_review"
    output.mkdir(exist_ok=False)
    selected = {0, 100, 150, 175, 220, 255}
    images = []
    times = []
    movie = av.open(str(video / "motion.mp4"))
    for index, frame in enumerate(movie.decode(video=0)):
        times.append(float(frame.time))
        if index in selected:
            rgb = frame.to_ndarray(format="rgb24")
            cv2.imwrite(
                str(output / f"frame_{index:04d}.jpg"),
                cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
            )
            images.append(cv2.resize(rgb, (640, 480)))
    movie.close()
    assert len(times) == manifest["frames"] == 256
    assert np.max(np.abs(np.asarray(times) - np.arange(256) / 50)) < 1e-9
    grid = np.concatenate(
        [np.concatenate(images[i : i + 3], axis=1) for i in range(0, len(images), 3)],
        axis=0,
    )
    cv2.imwrite(
        str(output / "decoded_review.jpg"), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR)
    )
    safe_save(
        output / "REVIEW.json",
        {
            "schema": "native-mug-preferred-video-decode/v1",
            "all256frames_decoded": True,
            "duration_s": 256 / 50,
            "manual_image_review_pending": True,
            "task_completed": False,
            "new_physics_steps": 0,
            "preferred_camera_only_correction": False,
            "original_bad_camera_video_preserved": _file_binding(
                root / "version_02/diagnostic_video/MANIFEST.json"
            ),
            "video": _file_binding(video / "MANIFEST.json"),
            "implementation": _file_binding(Path(__file__)),
            "files": {
                f.name: _file_binding(f)
                for f in sorted(output.iterdir())
                if f.is_file()
            },
        },
    )
    print({"decoded": 256, "seconds": 5.12, "output": str(output)}, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    run(ap.parse_args().root)

