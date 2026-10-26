"""Independent body/finger command, free-object and contact retention audit.

Reconstructs full simulator states with mj_forward only; never advances time.
"""

import argparse
from pathlib import Path
import numpy as np

from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    sha256_file,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
    ACTION_SCALES,
    ISAACLAB_TO_MUJOCO,
)
from .model import authorize
from .grasp import group
from .control import acceptance


def audit(root):
    import mujoco

    report = read_bound_json(root / "REPORT.json")
    case = read_bound_json(Path(report["case"]["path"]))
    authorize(Path(case["main_root"]))
    scene = read_bound_json(Path(case["scene_manifest_path"]))
    bindings = [
        report["case"],
        report["trace"],
        case["scene_manifest"],
        scene["model"],
        scene["implementation"],
        *scene["assets"],
        *report["inputs"].values(),
        *report["source_bindings"].values(),
    ]
    for b in bindings:
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("binding changed: " + b["path"])
    trace = read_bound_json(Path(report["trace"]["path"]))
    rows = trace["records"]
    active = [r for r in rows if r["sonic_candidate_consumed_by_physics"]]
    samples = [s for r in active for s in r["substeps"]]
    all_samples = [s for r in rows for s in r["substeps"]]
    model = mujoco.MjModel.from_xml_path(case["model_path"])
    data = mujoco.MjData(model)
    ids = native._model_ids(mujoco, model)
    official = {k: np.asarray(v) for k, v in native.official_control_arrays().items()}
    lower, upper = model.jnt_range[ids["joint_ids"]].T
    payload = model.body("payload").id
    geom = model.geom("payload_geom").id
    wrist = model.body("right_wrist_yaw_link").id
    joint = model.joint("payload_free").id
    local_initial = np.asarray(case["payload_local_xyz_m"])
    max_pd = max_hand = max_raw = max_local = max_contact = max_force = 0.0
    geometry_matches = commands_safe = fingers_native = True
    independent_held = []
    independently_unsafe_contact = False
    no_env_contacts = True
    for r in active:
        target = (
            np.asarray(DEFAULT_ANGLES)
            + np.asarray(r["raw_action_isaaclab"])[list(ISAACLAB_TO_MUJOCO)]
            * ACTION_SCALES
        )
        max_raw = max(max_raw, float(np.max(np.abs(target - r["candidate_rad"]))))
        commands_safe &= bool(
            np.isfinite(target).all() and np.all((target >= lower) & (target <= upper))
        )
        for s in r["substeps"]:
            pd = np.clip(
                official["kp"] * (target - s["body_position_before_rad"])
                - official["kd"] * s["body_velocity_before_rad_s"],
                -official["effort_limit"],
                official["effort_limit"],
            )
            max_pd = max(max_pd, float(np.max(np.abs(pd - s["body_torque_nm"]))))
            commands_safe &= s["position_target_rad"] == r["candidate_rad"]
    for s in all_samples:
        h = s["hand_pd"]
        expected_kp = np.array(
            [2.0 if "thumb_0" in n else 1.5 for n in h["joint_names"]]
        )
        expected_target = np.array(
            [case["right_hand_targets"].get(n, 0) for n in h["joint_names"]]
        )
        effort = np.array([model.actuator(n).ctrlrange[1] for n in h["joint_names"]])
        fingers_native &= (
            h["kp"] == expected_kp.tolist()
            and h["kd"] == 0.1
            and h["effort_limit_nm"] == effort.tolist()
            and h["target_rad"] == expected_target.tolist()
        )
        torque = np.clip(
            expected_kp * (expected_target - h["positions_before_rad"])
            - 0.1 * np.asarray(h["velocities_before_rad_s"]),
            -effort,
            effort,
        )
        max_hand = max(max_hand, float(np.max(np.abs(torque - h["torque_nm"]))))
        data.qpos[:] = s["full_qpos_after"]
        data.qvel[:] = s["full_qvel_after"]
        data.ctrl[:] = s["all_ctrl"]
        data.xfrc_applied[:] = s["xfrc_applied"]
        data.qfrc_applied[:] = s["qfrc_applied"]
        data.qacc_warmstart[:] = s["qacc_warmstart_after"]
        mujoco.mj_forward(model, data)
        local = data.xmat[wrist].reshape(3, 3).T @ (
            data.xpos[payload] - data.xpos[wrist]
        )
        max_local = max(
            max_local, float(np.max(np.abs(local - s["payload"]["local_position_m"])))
        )
        contacts = []
        labels = set()
        bad = False
        for index, c in enumerate(data.contact):
            a, b = int(c.geom1), int(c.geom2)
            for g in (a, b):
                no_env_contacts &= not model.geom(g).name.startswith(
                    ("scene_proxy_", "room_wall_")
                )
            if geom not in (a, b):
                continue
            other = b if a == geom else a
            name = model.body(int(model.geom_bodyid[other])).name
            label = group(name)
            bad |= label == "other"
            f = np.zeros(6)
            mujoco.mj_contactForce(model, data, index, f)
            if f[0] > 0.01:
                labels.add(label)
            contacts.append((name, float(c.dist), float(f[0])))
        logged = s["payload"]["contacts"]
        geometry_matches &= len(contacts) == len(logged)
        for current, prior in zip(contacts, logged):
            geometry_matches &= current[0] == prior["body"]
            max_contact = max(max_contact, abs(current[1] - prior["distance_m"]))
            max_force = max(max_force, abs(current[2] - prior["normal_force_n"]))
        held = (
            "thumb" in labels
            and bool({"index", "middle"} & labels)
            and not bad
            and np.linalg.norm(local - local_initial) <= 0.03
            and data.xpos[payload, 2] >= 0.25
        )
        independently_unsafe_contact |= bad
        independent_held.append(bool(held))
        geometry_matches &= bool(held) == s["payload"]["held"]
    prefix_keys = (
        "candidate_rad",
        "encoder_input_sha256",
        "decoder_input_sha256",
        "actual_qpos",
        "actual_qvel",
    )
    qualification = False
    if report["admission"]:
        b = report["admission"]
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("admission changed")
        admission = read_bound_json(Path(b["path"]))
        prior = read_bound_json(Path(admission["trace"]["path"]))
        qualification = len(rows) >= 50 and all(
            a[k] == b[k]
            for a, b in zip(rows[:50], prior["records"][:50])
            for k in prefix_keys
        )
        qualification &= (
            len(rows[49]["substeps"]) == 4
            and rows[49]["substeps"][-1]["grip_consecutive_steps"] >= 100
        )
        qualification &= all(
            a["full_qpos_after"] == b["full_qpos_after"]
            for ra, rb in zip(rows[:50], prior["records"][:50])
            for a, b in zip(ra["substeps"], rb["substeps"])
        )
    short_ok = report["active_budget_ticks"] == 100
    if report["short_smoke_report"]:
        b = report["short_smoke_report"]
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("short changed")
        short = read_bound_json(Path(b["path"]))
        prior = read_bound_json(Path(short["trace"]["path"]))
        old_active = [
            r for r in prior["records"] if r["sonic_candidate_consumed_by_physics"]
        ]
        short_ok = (
            short["active_smoke_passed"]
            and len(active) >= 100
            and all(
                a["full_qpos_after"] == b["full_qpos_after"]
                for ra, rb in zip(active[:100], old_active)
                for a, b in zip(ra["substeps"], rb["substeps"])
            )
        )
    previous = np.asarray(DEFAULT_ANGLES)
    slew = True
    for r in rows:
        candidate = np.asarray(r["candidate_rad"])
        if r["substeps"]:
            slew &= bool(
                np.max(np.abs(candidate - previous)) <= native.MAX_CANDIDATE_STEP_RAD
            )
        previous = candidate
    physical = all(
        s["pelvis_height_m"] >= 0.65
        and s["up_component"] >= 0.5
        and s["penetration_m"] <= 0.01
        and s["contact_force_n"] <= 600
        and s["only_declared_support_wrench"]
        for s in all_samples + trace["warmup_substeps"]
    )
    gates = {
        "free_unattached_payload": model.jnt_type[joint] == mujoco.mjtJoint.mjJNT_FREE
        and model.body_parentid[payload] == 0
        and model.neq == 0
        and model.nmocap == 0,
        "exact_qualification_including_object": qualification,
        "complete_bounded_budget": len(active) == report["active_budget_ticks"]
        and len(samples) == report["active_budget_ticks"] * 4
        and report["active_budget_ticks"] in (100, 300)
        and report["stop_reason"] is None,
        "raw_body_commands_and_pd": commands_safe and max_raw == 0 and max_pd == 0,
        "native_finger_pd": fingers_native and max_hand == 0,
        "original_physical_and_slew_gates": physical and slew,
        "independent_object_geometry": max_local <= 1e-12
        and max_contact <= 1e-12
        and geometry_matches,
        "independent_contact_forces": max_force <= 1e-6,
        "no_external_object_or_active_body_support": all(
            not any(s["qfrc_applied"])
            and not any(np.asarray(s["xfrc_applied"]).ravel())
            and not s["bias_feedforward_used"]
            for s in samples
        ),
        "state_chain_including_object": all(
            a["full_qpos_after"] == b["full_qpos_before"]
            for a, b in zip(all_samples, all_samples[1:])
        ),
        "no_environment_contacts": no_env_contacts and not independently_unsafe_contact,
        "independent_short_prefix": short_ok,
        "contact_carry_task": acceptance(rows, report["active_budget_ticks"], case)[
            "passed"
        ],
        "no_source_a_body": not report["source_a_body_reference_used"]
        and not report["source_a_body_command_used"],
    }
    result = {
        "schema": "conditional-contact-carry-audit/v1",
        "passed": bool(all(gates.values())),
        "gates": {k: bool(v) for k, v in gates.items()},
        "metrics": {
            "max_body_pd_error": max_pd,
            "max_hand_pd_error": max_hand,
            "max_raw_transform_error": max_raw,
            "max_object_local_error": max_local,
            "max_contact_distance_error": max_contact,
            "max_contact_force_error": max_force,
        },
        "report": _file_binding(root / "REPORT.json"),
        "trace": report["trace"],
        "implementation": _file_binding(Path(__file__)),
        "physics_steps": 0,
        "preloaded_grasp_not_pickup": True,
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(root / "CARRY_AUDIT.json", result)
    print(result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    audit(parser.parse_args().root)
