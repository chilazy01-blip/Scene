"""Numeric carrying development samples with separated privileged channels."""

import argparse
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
from sage.experiments.embodied_data_stability_v1.sonic_shadow import (
    SONIC_BODY_JOINT_ORDER,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    ISAACLAB_TO_MUJOCO,
)


def export(directory, output):
    import mujoco

    report = read_bound_json(directory / "REPORT.json")
    audit = read_bound_json(directory / "CARRY_AUDIT.json")
    reference = read_bound_json(directory / "REFERENCE_AUDIT.json")
    if (
        not audit["passed"]
        or not reference["passed"]
        or report["active_control_ticks"] != 300
    ):
        raise ValueError(
            "only fully accepted six-second active episodes may be exported"
        )
    for b in (audit["report"], report["trace"]):
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("source changed")
    trace = read_bound_json(Path(report["trace"]["path"]))
    rows = [r for r in trace["records"] if r["sonic_candidate_consumed_by_physics"]]
    model = mujoco.MjModel.from_xml_path(report["case_config"]["model_path"])
    payload_adr = int(model.joint("payload_free").qposadr[0])
    full_before = np.array([r["substeps"][0]["full_qpos_before"] for r in rows])
    arrays = {
        "episode_time_s": np.arange(len(rows)) * 0.02,
        "observation_body_position_rad": np.array([r["actual_qpos"] for r in rows]),
        "observation_body_velocity_rad_s": np.array([r["actual_qvel"] for r in rows]),
        "observation_base_quaternion_wxyz": np.array(
            [r["actual_quaternion"] for r in rows]
        ),
        "observation_base_gyro_rad_s": np.array([r["actual_gyro"] for r in rows]),
        "observation_finger_position_rad": np.array(
            [r["substeps"][0]["hand_pd"]["positions_before_rad"] for r in rows]
        ),
        "observation_finger_velocity_rad_s": np.array(
            [r["substeps"][0]["hand_pd"]["velocities_before_rad_s"] for r in rows]
        ),
        "action_body_raw_isaaclab": np.array([r["raw_action_isaaclab"] for r in rows]),
        "action_body_target_rad": np.array([r["candidate_rad"] for r in rows]),
        "action_body_torque_first_substep_nm": np.array(
            [r["substeps"][0]["body_torque_nm"] for r in rows]
        ),
        "action_finger_target_rad": np.array(
            [r["substeps"][0]["hand_pd"]["target_rad"] for r in rows]
        ),
        "action_finger_torque_first_substep_nm": np.array(
            [r["substeps"][0]["hand_pd"]["torque_nm"] for r in rows]
        ),
        "privileged_full_qpos_before": full_before,
        "privileged_full_qpos_after": np.array(
            [r["substeps"][-1]["full_qpos_after"] for r in rows]
        ),
        "privileged_object_world_pose_before": full_before[
            :, payload_adr : payload_adr + 7
        ],
        "quality_held_fraction_in_tick": np.array(
            [sum(s["payload"]["held"] for s in r["substeps"]) / 4 for r in rows]
        ),
        "quality_max_slip_in_tick_m": np.array(
            [
                max(s["payload"]["relative_position_error_m"] for s in r["substeps"])
                for r in rows
            ]
        ),
        "quality_rotation_error_rad": np.array(
            [r["substeps"][-1]["payload"]["relative_rotation_error_rad"] for r in rows]
        ),
        "quality_external_support_enabled": np.array(
            [any(s["support_enabled"] for s in r["substeps"]) for r in rows]
        ),
    }
    if not all(np.isfinite(v).all() for v in arrays.values()):
        raise ValueError("nonfinite sample")
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output / "episode.npz", **arrays)
    with np.load(output / "episode.npz", allow_pickle=False) as loaded:
        if set(loaded.files) != set(arrays) or any(
            not np.array_equal(v, loaded[k]) for k, v in arrays.items()
        ):
            raise ValueError("numeric round trip failed")
    raw_order = [None] * 29
    for model_index, raw_index in enumerate(ISAACLAB_TO_MUJOCO):
        raw_order[raw_index] = SONIC_BODY_JOINT_ORDER[model_index]
    result = {
        "schema": "g1-contact-carry-development-episode/v2",
        "mode": report["carry_mode"],
        "report": _file_binding(directory / "REPORT.json"),
        "audit": _file_binding(directory / "CARRY_AUDIT.json"),
        "reference_audit": _file_binding(directory / "REFERENCE_AUDIT.json"),
        "arrays": _file_binding(output / "episode.npz"),
        "array_shapes": {k: list(v.shape) for k, v in arrays.items()},
        "control_hz": 50,
        "physics_hz": 200,
        "body_joint_order": list(SONIC_BODY_JOINT_ORDER),
        "raw_action_order": raw_order,
        "finger_joint_order": rows[0]["substeps"][0]["hand_pd"]["joint_names"],
        "quaternion_order": "wxyz",
        "proprioception": "measured joints/velocities and base IMU interface; simulated here",
        "privileged_channels": [
            "world root/object pose",
            "contact quality and retention labels",
        ],
        "rgb": "representative replay only, not per-step RGB observations",
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "held_out_evaluation": False,
        "preloaded_grasp_not_pickup": True,
        "production_accepted": False,
        "implementation": _file_binding(Path(__file__)),
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output / "EPISODE.json", result)
    print(report["carry_mode"], "exported", len(rows), "samples", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    for mode in ("standing", "walking"):
        export(
            a.root / "continuation_01" / (mode + "_full"), a.root / "episodes" / mode
        )
