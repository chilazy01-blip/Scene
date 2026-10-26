"""Package verified video frames as browser-portable GIF; no new rendering."""

import argparse
import base64
import json
from pathlib import Path

from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .audit_sonic_supported_execution import read_bound_json
from .sonic_native_planner_preflight import _file_binding


def package(source, output):
    import cv2
    from PIL import Image

    manifest = read_bound_json(source / "MANIFEST.json")
    for binding in manifest["artifacts"].values():
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise ValueError("render artifact changed")
    if "task_passed" not in manifest:
        raise ValueError("use a motion-cycle render manifest")
    output.mkdir(parents=True, exist_ok=False)
    cap = cv2.VideoCapture(str(source / "motion.mp4"))
    frames, decoded = [], 0
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        if decoded % 2 == 0:
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            frame = Image.fromarray(rgb).resize((720, 450), Image.Resampling.LANCZOS)
            frames.append(frame.quantize(colors=128))
        decoded += 1
    cap.release()
    if decoded != manifest["frames"]:
        raise ValueError("source frame count differs")
    gif = output / "motion.gif"
    frames[0].save(
        gif, save_all=True, append_images=frames[1:], duration=40, loop=0, disposal=2
    )
    with Image.open(gif) as check:
        assert check.n_frames == len(frames)
    data = base64.b64encode(gif.read_bytes()).decode()
    (output / "replay.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>SONIC真实行走回放</title>'
        '<body style="background:#151b25;color:#eee;font:18px sans-serif;max-width:960px;margin:32px auto">'
        "<h2>SONIC真实仿真轨迹回放</h2><p>简化外观；实际姿态。蓝色为左侧，橙色为右侧。动画循环播放。</p>"
        f'<img alt="真实仿真回放" style="width:100%" src="data:image/gif;base64,{data}">'
        "<p>这是实测起步—行走—制动—保持片段；是否通过以画面标记及独立审计为准。外观为简化代理模型，不是完整官方网格。</p></body>",
        encoding="utf-8",
    )
    result = {
        "schema": "sonic-browser-replay/v1",
        "source_manifest": _file_binding(source / "MANIFEST.json"),
        "implementation": _file_binding(Path(__file__)),
        "source_frames": decoded,
        "output_frames": len(frames),
        "fps": 25,
        "duration_s": len(frames) / 25,
        "physics_steps": 0,
        "generated_or_interpolated_motion": False,
        "artifacts": {p.name: _file_binding(p) for p in output.iterdir()},
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output / "MANIFEST.json", result)
    print(
        json.dumps(
            {
                "output": str(output),
                "frames": len(frames),
                "duration_s": len(frames) / 25,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package(args.source, args.output)


if __name__ == "__main__":
    main()
