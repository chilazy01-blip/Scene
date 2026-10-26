"""Independently bind all frozen matrix outcomes, numeric episodes and videos."""

import argparse
import base64
import html
import json
import time
from collections import defaultdict
from pathlib import Path
import numpy as np

from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
    sha256_file,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.sonic_shadow import (
    SONIC_BODY_JOINT_ORDER,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    ISAACLAB_TO_MUJOCO,
)


def verify(binding):
    if sha256_file(Path(binding["path"])) != binding["sha256"]:
        raise ValueError("binding changed " + binding["path"])


def deliver(root):
    output = root / "delivery"
    output.mkdir(exist_ok=False)
    protocol = read_bound_json(root / "matrix_protocol_01/MATRIX.json")
    summary = read_bound_json(root / "matrix_run_01/RESULT.json")
    references = read_bound_json(root / "matrix_run_01/REFERENCE_AUDIT.json")
    for binding in [summary["protocol"], *protocol["dependencies"].values()]:
        verify(binding)
    by_scene = defaultdict(lambda: {"attempts": 0, "successes": 0})
    success = []
    fail = []
    rows = []
    physics = sonic_writes = 0
    stage_wall = 0.0
    expected = {item["id"]: item["case"]["sha256"] for item in protocol["cases"]}
    for binding in summary["case_results"]:
        verify(binding)
        case_result = read_bound_json(Path(binding["path"]))
        name = case_result["id"]
        if case_result["case"]["sha256"] != expected[name]:
            raise ValueError("unexpected case")
        verify(case_result["case"])
        case = read_bound_json(Path(case_result["case"]["path"]))
        by_scene[case["scene_id"]]["attempts"] += 1
        for stage in case_result["stages"]:
            verify(stage["report"])
            physics += stage["physics_steps"]
            sonic_writes += stage["sonic_writes"]
            stage_wall += stage["wall_s"]
        directory = root / "matrix_run_01" / name
        if case_result["accepted"]:
            audit = read_bound_json(directory / "full/AUDIT.json")
            integrity = read_bound_json(directory / "full/REFERENCE_AUDIT.json")
            episode = read_bound_json(directory / "episode/EPISODE.json")
            if not audit["task_passed"] or not integrity["passed"]:
                raise ValueError("unaccepted trajectory counted")
            for b in (
                audit["report"],
                audit["trace"],
                episode["arrays"],
                episode["report"],
                episode["audit"],
            ):
                verify(b)
            with np.load(episode["arrays"]["path"], allow_pickle=False) as arrays:
                if arrays["action_joint_target_rad"].shape != (300, 29):
                    raise ValueError("unexpected episode shape")
                if not all(np.isfinite(arrays[key]).all() for key in arrays.files):
                    raise ValueError("nonfinite arrays")
                if not np.allclose(
                    np.diff(arrays["episode_time_s"]), 0.02, rtol=0, atol=1e-12
                ):
                    raise ValueError("timebase mismatch")
            by_scene[case["scene_id"]]["successes"] += 1
            success.append(name)
            detail = f"误差 {audit['metrics']['target_error_m']*100:.1f} cm；制动帧 {integrity['reported_brake_frame']}"
        else:
            fail.append(name)
            detail = case_result["failure"] or "not accepted"
        rows.append(
            (
                name,
                case["scene_id"],
                case["goal_distance_m"],
                case["start_yaw_rad"],
                case["initialization_seed"],
                case_result["accepted"],
                detail,
            )
        )
    selection = json.loads((root / "VISUAL_SELECTION.json").read_text())[
        "selected_before_matrix_completion"
    ]
    videos = []
    cards = []
    for name in selection:
        manifest_path = root / "review_v4" / name / "MANIFEST.json"
        manifest = read_bound_json(manifest_path)
        for b in [
            manifest["report"],
            manifest["trace"],
            manifest["renderer"],
            manifest["layout_overlay"],
            manifest["independent_audit"],
            *manifest["artifacts"].values(),
        ]:
            verify(b)
        if min(manifest["minimum_robot_visibility_pixels"].values()) < 100:
            raise ValueError("occluded robot")
        movie = root / "review_v4" / name / "motion.mp4"
        videos.append(_file_binding(manifest_path))
        encoded = base64.b64encode(movie.read_bytes()).decode()
        cards.append(
            f'<section><h2>{name} — {html.escape(next(r[1] for r in rows if r[0]==name))}</h2><video controls loop playsinline preload="metadata" src="data:video/mp4;base64,{encoded}"></video></section>'
        )
    gates = {
        "all_48_frozen_cases_reported": len(rows) == 48
        and {r[0] for r in rows} == set(expected),
        "at_least_80_percent_success": len(success) >= 39,
        "all_3_scenes_have_success": len(by_scene) == 3
        and all(s["successes"] >= 1 for s in by_scene.values()),
        "all_reference_inputs_and_goal_events_match": references["passed"]
        and len(references["cases"]) >= len(success),
        "preselected_3_scene_videos_bound": len(videos) == 3,
        "failures_retained": len(success) + len(fail) == 48,
    }
    raw_order = [None] * 29
    for model_index, raw_index in enumerate(ISAACLAB_TO_MUJOCO):
        raw_order[raw_index] = SONIC_BODY_JOINT_ORDER[model_index]
    schema = {
        "schema": "locomotion-dataset-numeric-contract/v1",
        "control_hz": 50,
        "physics_hz": 200,
        "joint_position_target_torque_order": list(SONIC_BODY_JOINT_ORDER),
        "raw_action_isaaclab_order": raw_order,
        "quaternion": "wxyz",
        "linear_units": "m",
        "angular_units": "rad",
        "torque_units": "Nm",
        "split": "unassigned",
        "role": "development_validation",
        "held_out_evaluation": False,
        "privileged_channels": [
            "world root qpos",
            "world goal coordinates without deployment localization",
            "foot-contact quality labels",
        ],
        "rgb": "representative replays only; not RGB observation at every training step",
        "production_accepted": False,
    }
    write_json_atomic(output / "DATASET_SCHEMA.json", schema)
    table = "".join(
        f'<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]:.1f}m</td><td>{r[4]}</td><td>{"通过" if r[5] else "失败"}</td><td>{html.escape(r[6])}</td></tr>'
        for r in rows
    )
    page = '<!doctype html><meta charset="utf-8"><title>自生成场景行走采集闭环</title><style>body{background:#151b25;color:#eee;font:16px sans-serif;max-width:1100px;margin:28px auto}video{width:100%;background:#000}section{margin:28px 0}td,th{padding:8px;border-bottom:1px solid #46505d}small{color:#b6c2d2}</style>'
    page += f"<h1>自生成场景中的行走与停稳</h1><p>固定矩阵：{len(success)}/48 通过；3个布局、2个距离、2个初始姿态、4个微扰种子。视频用例在结果出现前选定。</p>"
    page += "<p>真实物理闭环姿态；绿色圆圈为目标区，右上角为生成布局和实测轨迹。机器人外观简化；本体collision-lite、环境保守碰撞代理。目标区域和低扰动条件均为开发验证，不是复杂导航、生产数据或held-out泛化结论。</p>"
    page += (
        "".join(cards)
        + "<h2>完整48条结果（不隐藏失败）</h2><table><tr><th>ID</th><th>场景</th><th>距离</th><th>种子</th><th>结果</th><th>说明</th></tr>"
        + table
        + "</table>"
    )
    (output / "index.html").write_text(page, encoding="utf-8")
    document = {
        "schema": "generated-locomotion-pipeline-delivery/v1",
        "classification": (
            "accepted_development_pipeline" if all(gates.values()) else "not_accepted"
        ),
        "gates": gates,
        "accepted_count": len(success),
        "failed_count": len(fail),
        "success_rate": len(success) / 48,
        "per_scene": dict(by_scene),
        "accepted_case_ids": success,
        "failed_case_ids": fail,
        "matrix": _file_binding(root / "matrix_protocol_01/MATRIX.json"),
        "matrix_result": _file_binding(root / "matrix_run_01/RESULT.json"),
        "reference_audit": _file_binding(root / "matrix_run_01/REFERENCE_AUDIT.json"),
        "videos": videos,
        "page": _file_binding(output / "index.html"),
        "schema_contract": _file_binding(output / "DATASET_SCHEMA.json"),
        "physics_steps": physics,
        "sonic_actuator_writes": sonic_writes,
        "report_wall_s": stage_wall,
        "accepted_utc_timestamp": time.time(),
        "implementation": _file_binding(Path(__file__)),
        "production_accepted": False,
        "held_out_generalization_validated": False,
        "grasp_success_validated": False,
    }
    document["content_sha256_excluding_this_field"] = canonical_sha256(document)
    write_json_atomic(output / "DELIVERY.json", document)
    print(
        json.dumps(
            {
                k: document[k]
                for k in ("classification", "gates", "accepted_count", "per_scene")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    deliver(p.parse_args().root)
