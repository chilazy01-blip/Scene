"""Task-level honest delivery, real-video decode and qualified-only export."""

import argparse
from pathlib import Path
import numpy as np
from .protocol_v2 import authorize
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def check(b):
    assert sha256_file(Path(b["path"])) == b["sha256"], b["path"]


def run(root, episode, video, dynamics=None):
    import cv2
    import av

    p = authorize(root)
    r = read_bound_json(episode / "REPORT.json")
    a = read_bound_json(episode / "AUDIT.json")
    if Path(r["protocol"]["path"]).name == "VERSION_02_PROTOCOL.json":
        from .protocol_v2 import authorize as second_authorize

        second_authorize(root)
    for b in [
        r["case"],
        r["protocol"],
        r["engine"],
        r["trace"],
        r["policy_io"],
        r["model"],
        a["report"],
        a["implementation"],
    ]:
        check(b)
    ledger = read_bound_json(root / "COST.json")
    cost = 0
    costs = []
    for reservation in ledger["reservations"]:
        path = Path(reservation["output"]) / "REPORT.json"
        if path.exists():
            result = read_bound_json(path)
            n = result["physics_steps"]
            binding = _file_binding(path)
        else:
            n = reservation["maximum_steps"]
            binding = None
        costs.append(
            {
                "output": reservation["output"],
                "steps": n,
                "report": binding,
                "unknown_full_reservation_charged": binding is None,
            }
        )
        cost += n
    assert cost <= p['max_new_physics_steps'] and p['prior_native_steps'] + cost <= p['cumulative_native_cap']
    trace = read_bound_json(Path(r["trace"]["path"]))
    rows = trace["warmup_substeps"] + [
        s for row in trace["records"] for s in row["substeps"]
    ]
    assert len(rows) == r["physics_steps"]
    vm = read_bound_json(video / "MANIFEST.json")
    for binding in vm["files"].values():
        check(binding)
    for binding in (
        vm["model"],
        vm["case"],
        vm["report"],
        vm["trace"],
        vm["implementation"],
    ):
        check(binding)
    assert vm["report"] == _file_binding(episode / "REPORT.json")
    assert vm["new_physics_steps"] == 0
    output = episode.parent / ("delivery" if r["task_passed"] else "partial_delivery")
    output.mkdir(exist_ok=False)
    positions = {0, vm["frames"] - 1}
    for stage in (
        "approach",
        "insert",
        "close",
        "lift",
        "carry",
        "place",
        "release",
        "settle",
    ):
        matches = [
            i // 4 for i, s in enumerate(rows) if i % 4 == 3 and s["stage"] == stage
        ]
        if matches:
            positions.update((matches[0], matches[len(matches) // 2]))
    decoded = []
    times = []
    movie = av.open(str(video / "motion.mp4"))
    for index, frame in enumerate(movie.decode(video=0)):
        times.append(float(frame.time))
        if index in positions:
            rgb = frame.to_ndarray(format="rgb24")
            cv2.imwrite(
                str(output / f"decoded_{index:04d}.jpg"),
                cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
            )
            decoded.append(cv2.resize(rgb, (640, 480)))
    movie.close()
    assert len(times) == vm["frames"]
    assert np.max(np.abs(np.asarray(times) - np.arange(len(times)) / 50)) < 1e-9
    assert abs(len(times) / 50 - len(rows) * 0.005) <= 0.01500001
    while len(decoded) % 3:
        decoded.append(np.zeros_like(decoded[0]))
    grid = np.concatenate(
        [np.concatenate(decoded[i : i + 3], axis=1) for i in range(0, len(decoded), 3)],
        axis=0,
    )
    cv2.imwrite(
        str(output / "decoded_review.jpg"), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR)
    )
    dyn = None
    if dynamics is not None:
        dyn = read_bound_json(dynamics / "REPORT.json")
        check(dyn["started"])
        check(dyn["implementation"])
        started = read_bound_json(Path(dyn["started"]["path"]))
        assert started["report"] == _file_binding(episode / "REPORT.json")
    qualified = bool(
        r["task_passed"] and a["task_passed"] and dyn is not None and dyn["passed"]
    )
    if qualified:
        assert all(
            s["safe"]
            and not s["forbidden_contacts"]
            and not np.any(s["xfrc_applied"])
            and not np.any(s["qfrc_applied"])
            for s in rows
        )
        assert (
            dyn["physics_steps"] == len(rows)
            and max(dyn["maximum_absolute_error"].values()) == 0
        )
        fields = {
            "time_s": "time_after_s",
            "qpos_before": "full_qpos_before",
            "qpos_after": "full_qpos_after",
            "qvel_before": "full_qvel_before",
            "qvel_after": "full_qvel_after",
            "qacc_warmstart_before": "qacc_warmstart_before",
            "qacc_warmstart_after": "qacc_warmstart_after",
            "ctrl": "all_ctrl",
            "body_target_rad": "body_position_target_rad",
            "hand_target_rad": "hand_target_rad",
            "body_feedforward_nm": "body_feedforward_nm",
            "stage": "stage",
            "object_position_m": "object_m",
        }
        arrays = {
            name: np.asarray([s[key] for s in rows]) for name, key in fields.items()
        }
        np.savez_compressed(output / "episode.npz", **arrays)
        with np.load(output / "episode.npz", allow_pickle=False) as exported:
            assert all(np.array_equal(exported[k], v) for k, v in arrays.items())
    summary = {
        "schema": "native-mug-task-delivery/v1",
        "mechanically_qualified": qualified,
        "manual_video_review_pending": True,
        "task_passed": r["task_passed"],
        "audit_passed": a["task_passed"],
        "continuous_dynamics_passed": False if dyn is None else dyn["passed"],
        "report": _file_binding(episode / "REPORT.json"),
        "audit": _file_binding(episode / "AUDIT.json"),
        "dynamics": (
            None if dynamics is None else _file_binding(dynamics / "REPORT.json")
        ),
        "video": _file_binding(video / "MANIFEST.json"),
        "video_mp4": _file_binding(video / "motion.mp4"),
        "all_decoded_frames": len(times),
        "actual_seconds": len(rows) * 0.005,
        "carry_distance_m": r["carry_distance_m"],
        "object_displacement_xy_m": r["object_displacement_xy_m"],
        "goal_error_m": r["goal_error_m"],
        "max_held_slip_m": r["max_held_slip_m"],
        "carry_foot_cycles": r["carry_foot_cycles"],
        "maximum_penetration_m": max(s["penetration_m"] for s in rows),
        "maximum_contact_force_n": max(s["maximum_contact_force_n"] for s in rows),
        "maximum_root_acceleration_m_s2": max(
            float(np.linalg.norm(s["root_acceleration_m_s2"])) for s in rows
        ),
        "maximum_joint_speed_rad_s": max(s["maximum_joint_speed_rad_s"] for s in rows),
        "maximum_joint_acceleration_rad_s2": max(
            s["maximum_joint_acceleration_rad_s2"] for s in rows
        ),
        "target_projection_count": r["projected_ticks"],
        "maximum_target_projection_rad": r["maximum_target_projection_rad"],
        "new_physics_cost": cost,
        "native_cumulative_physics_cost": p["prior_native_steps"] + cost,
        "cost_items": costs,
        "positive_episode_count": int(qualified),
        "no_layout_or_native_collision_changes": True,
        "added_task_object": "existing mug_white_001, all39999 mesh triangles, free physical body, explicit150g task assumption",
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "scope": "one task-level native-room development demo, no training/heldout/generalization/production qualification",
        "export_schema": {
            "nq": 57,
            "nv": 55,
            "nu": 43,
            "state_order": "original frozen native MuJoCo model, named29 body +14hand joints + free mug; no slicing all body joints fromqpos[7:]",
            "units": "seconds/meters/radians/Newton-meters",
            "contacts_and_exact_policy_io": "retained in bound original TRACE and POLICY_IO archives",
        },
        "failures_preserved": [
            _file_binding(path)
            for path in sorted(root.glob("version_*/full/REPORT.json"))
            if not read_bound_json(path)["task_passed"]
        ],
        "implementation": _file_binding(Path(__file__)),
        "files": {
            f.name: _file_binding(f) for f in sorted(output.iterdir()) if f.is_file()
        },
    }
    safe_save(output / "REVIEW.json", summary)
    print(
        {
            "mechanically_qualified": qualified,
            "actual_seconds": summary["actual_seconds"],
            "new_steps": cost,
            "delivery": str(output),
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--episode", type=Path, required=True)
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--dynamics", type=Path)
    a = ap.parse_args()
    run(a.root, a.episode, a.video, a.dynamics)
