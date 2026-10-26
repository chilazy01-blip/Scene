"""Standard numeric development episode export, with explicit availability tags."""

from pathlib import Path
import numpy as np
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
    sha256_file,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def export(root, output):
    report = read_bound_json(root / "REPORT.json")
    audit = read_bound_json(root / "AUDIT.json")
    if not audit["task_passed"] or not report["controlled_stop_acceptance"]["passed"]:
        raise ValueError("unaccepted episode")
    if audit["report"]["sha256"] != sha256_file(root / "REPORT.json"):
        raise ValueError("audit/report mismatch")
    trace = read_bound_json(Path(report["trace"]["path"]))
    rows = [r for r in trace["records"] if r["sonic_candidate_consumed_by_physics"]]
    output.mkdir(exist_ok=False)
    arrays = {
        "episode_time_s": np.array([r["reference_tick"] * 0.02 for r in rows]),
        "observation_joint_position_rad": np.array([r["actual_qpos"] for r in rows]),
        "observation_joint_velocity_rad_s": np.array([r["actual_qvel"] for r in rows]),
        "observation_base_quaternion_wxyz": np.array(
            [r["actual_quaternion"] for r in rows]
        ),
        "observation_base_gyro_rad_s": np.array([r["actual_gyro"] for r in rows]),
        "action_raw_isaaclab": np.array([r["raw_action_isaaclab"] for r in rows]),
        "action_joint_target_rad": np.array([r["candidate_rad"] for r in rows]),
        "action_torque_tick_start_nm": np.array(
            [r["substeps"][0]["body_torque_nm"] for r in rows]
        ),
        "privileged_qpos_before": np.array(
            [r["substeps"][0]["full_qpos_before"] for r in rows]
        ),
        "privileged_qpos_after": np.array(
            [r["substeps"][-1]["full_qpos_after"] for r in rows]
        ),
        "quality_sole_clearance_m": np.array(
            [
                [
                    r["substeps"][-1]["feet"][s]["sole_clearance_m"]
                    for s in ("left", "right")
                ]
                for r in rows
            ]
        ),
        "quality_ground_force_n": np.array(
            [
                [
                    r["substeps"][-1]["feet"][s]["ground_contact_force_max_n"]
                    for s in ("left", "right")
                ]
                for r in rows
            ]
        ),
    }
    np.savez_compressed(output / "episode.npz", **arrays)
    with np.load(output / "episode.npz", allow_pickle=False) as loaded:
        for name, value in arrays.items():
            if not np.array_equal(loaded[name], value):
                raise ValueError("round-trip mismatch")
    result = {
        "schema": "g1-locomotion-development-episode/v1",
        "report": _file_binding(root / "REPORT.json"),
        "audit": _file_binding(root / "AUDIT.json"),
        "trace": report["trace"],
        "case": report["case"],
        "arrays": _file_binding(output / "episode.npz"),
        "array_shapes": {k: list(v.shape) for k, v in arrays.items()},
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "held_out_evaluation": False,
        "observation_availability": {
            "joint_position_velocity_imu": "physical proprioceptive interface; simulation measurements here",
            "world_root_and_goal": "privileged simulator state / requires localization in deployment",
            "foot_contact_quality": "privileged quality labels, not controller inputs",
            "rgb": "not sampled in every episode; separate representative replay only",
        },
        "metrics": audit["metrics"],
        "production_accepted": False,
        "implementation": _file_binding(Path(__file__)),
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output / "EPISODE.json", result)
    return result
