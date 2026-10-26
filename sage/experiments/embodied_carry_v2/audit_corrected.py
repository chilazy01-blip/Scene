"""Independent simulator-state reconstruction and ordered-stage acceptance."""

import argparse
from pathlib import Path
import numpy as np
from .protocol import authorize
from sage.experiments.embodied_carry_v1.grasp import group
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
    ACTION_SCALES,
    ISAACLAB_TO_MUJOCO,
)
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
from sage.experiments.embodied_locomotion_v1.metrics import accept as locomotion_accept


def audit(root):
    import mujoco

    output = root / "CARRY_AUDIT.json"
    if output.exists():
        raise FileExistsError(output)
    report = read_bound_json(root / "REPORT.json")
    case = read_bound_json(Path(report["case"]["path"]))
    authorize(Path(case["protocol_root"]))
    scene = read_bound_json(Path(case["scene_manifest_path"]))
    for b in [
        report["case"],
        report["trace"],
        case["scene_manifest"],
        scene["model"],
        scene["implementation"],
        *scene["assets"],
        *report["inputs"].values(),
        *report["source_bindings"].values(),
    ]:
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("binding changed: " + b["path"])
    trace = read_bound_json(Path(report["trace"]["path"]))
    rows = trace["records"]
    active = [r for r in rows if r["sonic_candidate_consumed_by_physics"]]
    active_ids = {id(s) for r in active for s in r["substeps"]}
    samples = trace["warmup_substeps"] + [s for r in rows for s in r["substeps"]]
    model = mujoco.MjModel.from_xml_path(case["model_path"])
    model.opt.timestep = (
        native.SIMULATION_DT_S
    )  # restore the execution timebase before finite differences
    data = mujoco.MjData(model)
    ids = native._model_ids(mujoco, model)
    controls = {k: np.asarray(v) for k, v in native.official_control_arrays().items()}
    hand_names = [
        model.joint(i).name
        for i in range(model.njnt)
        if "_hand_" in model.joint(i).name
    ]
    hq = np.array([model.joint(n).qposadr[0] for n in hand_names], dtype=int)
    ha = np.array([model.actuator(n).id for n in hand_names], dtype=int)
    payload = model.body("payload").id
    wrist = model.body("right_wrist_yaw_link").id
    pelvis = model.body("pelvis").id
    payload_geom = model.geom("payload_geom").id
    initial = np.asarray(case["payload_local_xyz_m"])
    previous = initial.copy()
    anchor = anchor_rotation = None
    consecutive = 0
    counters = []
    reconstructed = {}
    max_local = max_contact = max_force = max_angle = max_hand = max_pd = max_raw = 0.0
    matches = native_hand = physical = no_env = finite = True
    for step, s in enumerate(samples, 1):
        data.qpos[:] = s["full_qpos_after"]
        data.qvel[:] = s["full_qvel_after"]
        data.ctrl[:] = s["all_ctrl"]
        data.xfrc_applied[:] = s["xfrc_applied"]
        data.qfrc_applied[:] = s["qfrc_applied"]
        data.qacc_warmstart[:] = s["qacc_warmstart_after"]
        mujoco.mj_forward(model, data)
        finite &= all(
            np.isfinite(data_array).all()
            for data_array in (
                data.qpos,
                data.qvel,
                data.ctrl,
                data.xfrc_applied,
                data.qfrc_applied,
            )
        )
        local = data.xmat[wrist].reshape(3, 3).T @ (
            data.xpos[payload] - data.xpos[wrist]
        )
        rotation = data.xmat[wrist].reshape(3, 3).T @ data.xmat[payload].reshape(3, 3)
        speed = float(np.linalg.norm(local - previous) / model.opt.timestep)
        previous = local.copy()
        if step == case["grip_protocol"]["anchor_physics_step"]:
            anchor, anchor_rotation = local.copy(), rotation.copy()
        acquired = (
            anchor is not None and step > case["grip_protocol"]["anchor_physics_step"]
        )
        slip = float(np.linalg.norm(local - anchor)) if anchor is not None else 0.0
        angle = (
            float(
                np.arccos(
                    np.clip((np.trace(anchor_rotation.T @ rotation) - 1) / 2, -1, 1)
                )
            )
            if anchor is not None
            else 0.0
        )
        labels = set()
        contacts = []
        bad = False
        penetration = force_peak = 0.0
        feet = {}
        for side in ("left", "right"):
            bid = model.body(side + "_ankle_roll_link").id
            geom = next(g for g in range(model.ngeom) if model.geom_bodyid[g] == bid)
            feet[side] = {
                "geom": geom,
                "sole_clearance_m": float(
                    data.geom_xpos[geom, 2]
                    - np.abs(data.geom_xmat[geom].reshape(3, 3)[2])
                    @ model.geom_size[geom]
                ),
                "ground_contact_force_max_n": 0.0,
            }
        for index, c in enumerate(data.contact):
            a, b = int(c.geom1), int(c.geom2)
            f = np.zeros(6)
            mujoco.mj_contactForce(model, data, index, f)
            force_peak = max(force_peak, float(np.linalg.norm(f[:3])))
            penetration = max(penetration, -float(c.dist))
            no_env &= not any(
                model.geom(g).name.startswith(("scene_proxy_", "room_wall_"))
                for g in (a, b)
            )
            for side in feet:
                g = feet[side]["geom"]
                if (g == a and model.geom_bodyid[b] == 0) or (
                    g == b and model.geom_bodyid[a] == 0
                ):
                    feet[side]["ground_contact_force_max_n"] = max(
                        feet[side]["ground_contact_force_max_n"],
                        float(np.linalg.norm(f[:3])),
                    )
            if payload_geom in (a, b):
                other = b if a == payload_geom else a
                name = model.body(int(model.geom_bodyid[other])).name
                label = group(name)
                bad |= label == "other"
                if f[0] > 0.01:
                    labels.add(label)
                contacts.append((name, float(c.dist), float(f[0])))
        opposing = "thumb" in labels and bool({"index", "middle"} & labels)
        held = (
            acquired
            and opposing
            and not bad
            and slip <= 0.03
            and angle <= np.pi / 6
            and data.xpos[payload, 2] >= 0.25
        )
        stable = (
            held
            and speed <= case["grip_protocol"]["qualification_max_relative_speed_m_s"]
        )
        consecutive = consecutive + 1 if stable else 0
        counters.append(consecutive)
        p = s["payload"]
        matches &= (
            bool(held) == p["held"] and consecutive == s["grip_consecutive_steps"]
        )
        matches &= p["anchor_local_xyz_m"] == (
            anchor.tolist() if anchor is not None else None
        )
        max_local = max(
            max_local,
            float(np.max(np.abs(local - p["local_position_m"]))),
            abs(slip - p["relative_position_error_m"]),
            abs(speed - p["relative_speed_m_s"]),
        )
        max_angle = max(max_angle, abs(angle - p["relative_rotation_error_rad"]))
        matches &= len(contacts) == len(p["contacts"])
        for c, logged in zip(contacts, p["contacts"]):
            matches &= c[0] == logged["body"]
            max_contact = max(max_contact, abs(c[1] - logged["distance_m"]))
            max_force = max(max_force, abs(c[2] - logged["normal_force_n"]))
        h = s["hand_pd"]
        kp = np.array([2.0 if "thumb_0" in n else 1.5 for n in hand_names])
        target = np.array([case["right_hand_targets"].get(n, 0) for n in hand_names])
        effort = model.actuator_ctrlrange[ha, 1]
        hand_torque = np.clip(
            kp * (target - h["positions_before_rad"])
            - 0.1 * np.asarray(h["velocities_before_rad_s"]),
            -effort,
            effort,
        )
        native_hand &= (
            h["joint_names"] == hand_names
            and h["kp"] == kp.tolist()
            and h["kd"] == 0.1
            and h["target_rad"] == target.tolist()
            and h["effort_limit_nm"] == effort.tolist()
        )
        max_hand = max(
            max_hand,
            float(np.max(np.abs(hand_torque - data.ctrl[ha]))),
            float(np.max(np.abs(hand_torque - h["torque_nm"]))),
        )
        physical &= (
            data.xpos[pelvis, 2] >= 0.65
            and data.xmat[pelvis].reshape(3, 3)[2, 2] >= 0.5
            and penetration <= 0.01
            and force_peak <= 600
            and np.linalg.norm(local - initial) <= 0.08
            and not bad
            and data.xpos[payload, 2] >= 0.25
        )
        if acquired:
            physical &= slip <= 0.03 and angle <= np.pi / 6
        reconstructed[id(s)] = {
            "held": held,
            "slip": slip,
            "angle": angle,
            "up": float(data.xmat[pelvis].reshape(3, 3)[2, 2]),
            "height": float(data.xpos[pelvis, 2]),
            "bad": bad,
            "object_height": float(data.xpos[payload, 2]),
            "feet": {
                side: {key: value for key, value in foot.items() if key != "geom"}
                for side, foot in feet.items()
            },
        }
    raw_safe = slew_safe = True
    previous_command = np.asarray(DEFAULT_ANGLES)
    lower, upper = model.jnt_range[ids["joint_ids"]].T
    for r in rows:
        target = (
            np.asarray(DEFAULT_ANGLES)
            + np.asarray(r["raw_action_isaaclab"])[list(ISAACLAB_TO_MUJOCO)]
            * ACTION_SCALES
        )
        max_raw = max(max_raw, float(np.max(np.abs(target - r["candidate_rad"]))))
        raw_safe &= bool(
            np.isfinite(target).all() and np.all((target >= lower) & (target <= upper))
        )
        if r["substeps"]:
            slew_safe &= bool(
                np.max(np.abs(target - previous_command))
                <= native.MAX_CANDIDATE_STEP_RAD
            )
        previous_command = target
        if not r["sonic_candidate_consumed_by_physics"]:
            continue
        for s in r["substeps"]:
            torque = np.clip(
                controls["kp"] * (target - s["body_position_before_rad"])
                - controls["kd"] * s["body_velocity_before_rad_s"],
                -controls["effort_limit"],
                controls["effort_limit"],
            )
            max_pd = max(
                max_pd,
                float(np.max(np.abs(torque - s["body_torque_nm"]))),
                float(
                    np.max(
                        np.abs(torque - np.asarray(s["all_ctrl"])[ids["actuator_ids"]])
                    )
                ),
            )
            matches &= s["position_target_rad"] == r["candidate_rad"]
    active_samples = [s for s in samples if id(s) in active_ids]
    qualification = len(counters) >= 240 and counters[239] >= 100
    prefix = True
    if report["admission"]:
        b = report["admission"]
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("admission changed")
        admission = read_bound_json(Path(b["path"]))
        prior = read_bound_json(Path(admission["trace"]["path"]))
        prefix = len(rows) >= 50 and all(
            a[k] == b[k]
            for a, b in zip(rows[:50], prior["records"][:50])
            for k in (
                "encoder_input_sha256",
                "decoder_input_sha256",
                "candidate_rad",
                "actual_qpos",
                "actual_qvel",
            )
        )
        prefix &= all(
            a["full_qpos_after"] == b["full_qpos_after"]
            and a["full_qvel_after"] == b["full_qvel_after"]
            for ra, rb in zip(rows[:50], prior["records"][:50])
            for a, b in zip(ra["substeps"], rb["substeps"])
        )
    short_prefix = report["active_budget_ticks"] == 100
    if report["short_smoke_report"]:
        b = report["short_smoke_report"]
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("short changed")
        short = read_bound_json(Path(b["path"]))
        prior = read_bound_json(Path(short["trace"]["path"]))
        old_active = [
            r for r in prior["records"] if r["sonic_candidate_consumed_by_physics"]
        ]
        short_prefix = (
            short["active_smoke_passed"]
            and len(old_active) == 100
            and len(active) >= 100
            and all(
                a["full_qpos_after"] == b["full_qpos_after"]
                for ra, rb in zip(active[:100], old_active)
                for a, b in zip(ra["substeps"], rb["substeps"])
            )
        )
    budget = report["active_budget_ticks"]
    is_active = report["admission"] is not None
    complete = (
        (len(active) == budget and len(active_samples) == budget * 4)
        if is_active
        else (len(rows) == 100 and len(samples) == 440)
    )
    gates = {
        "free_payload": model.jnt_type[model.joint("payload_free").id]
        == mujoco.mjtJoint.mjJNT_FREE
        and model.body_parentid[payload] == 0
        and model.neq == 0
        and model.nmocap == 0,
        "complete_bounded_run": complete
        and report["stop_reason"] is None
        and budget in (100, 300),
        "independent_physics_and_finiteness": physical and finite and no_env,
        "raw_body_limits_slew_pd": raw_safe
        and slew_safe
        and max_raw == 0
        and max_pd == 0,
        "native_hand_pd": native_hand and max_hand == 0,
        "independent_grip_anchor_geometry": matches
        and max_local <= 1e-12
        and max_angle <= 1e-8
        and max_contact <= 1e-12
        and max_force <= 1e-6,
        "continuous_state_including_object": all(
            a["full_qpos_after"] == b["full_qpos_before"]
            for a, b in zip(samples, samples[1:])
        ),
        "admission_prefix_exact": prefix,
        "short_prefix_exact": short_prefix if is_active else True,
        "no_active_external_force_or_bias": all(
            not np.any(s["xfrc_applied"])
            and not any(s["qfrc_applied"])
            and not s["bias_feedforward_used"]
            and not s["support_enabled"]
            for s in active_samples
        ),
        "no_source_a_body": not report["source_a_body_reference_used"]
        and not report["source_a_body_command_used"],
    }
    control = bool(all(gates.values()))
    metrics = {
        "max_body_pd_error": max_pd,
        "max_hand_pd_error": max_hand,
        "max_raw_transform_error": max_raw,
        "max_geometry_error": max_local,
        "max_contact_distance_error": max_contact,
        "max_contact_force_error": max_force,
        "grip_qualification_consecutive_at_step240": (
            counters[239] if len(counters) >= 240 else 0
        ),
    }
    task_gates = {}
    if active_samples:
        rs = [reconstructed[id(s)] for s in active_samples]
        task_gates = {
            "contact_retention": sum(bool(s["held"]) for s in rs) / len(rs) >= 0.9,
            "slip": max(s["slip"] for s in rs) <= 0.03,
            "rotation": max(s["angle"] for s in rs) <= np.pi / 6,
            "upright_quality": min(s["up"] for s in rs) >= 0.97
            and min(s["height"] for s in rs) >= 0.7,
        }
        metrics.update(
            held_contact_fraction=sum(bool(s["held"]) for s in rs) / len(rs),
            max_relative_slip_m=max(s["slip"] for s in rs),
            max_relative_rotation_rad=max(s["angle"] for s in rs),
        )
        if case["carry_mode"] == "standing":
            tail = active_samples[-200:]
            origin = np.asarray(tail[0]["full_qpos_before"][:2])
            drift = max(
                float(np.linalg.norm(np.asarray(s["full_qpos_after"][:2]) - origin))
                for s in tail
            )
            speed = max(
                float(np.linalg.norm(np.asarray(s["full_qvel_after"][:3])[:2]))
                for s in tail
            )
            rms = max(
                float(np.sqrt(np.mean(np.square(s["body_velocity_after_rad_s"]))))
                for s in tail
            )
            both = sum(
                all(
                    reconstructed[id(s)]["feet"][side]["ground_contact_force_max_n"] > 2
                    for side in ("left", "right")
                )
                for s in tail
            ) / len(tail)
            task_gates["standing_hold_quality"] = (
                drift <= 0.02 and speed <= 0.08 and rms <= 0.6 and both >= 0.9
            )
            metrics.update(
                last_second_drift_m=drift,
                last_second_speed_m_s=speed,
                last_second_joint_rms=rms,
                last_second_double_support_fraction=both,
            )
        elif budget > 100:
            checked = [
                dict(
                    r,
                    substeps=[
                        dict(s, feet=reconstructed[id(s)]["feet"])
                        for s in r["substeps"]
                    ],
                )
                for r in rows
            ]
            task = locomotion_accept(checked, budget, case)
            task_gates["locomotion_and_stop"] = task["passed"]
            metrics["locomotion"] = task
    passed = (
        control
        and qualification
        and (
            all(task_gates.values()) if is_active and active_samples else not is_active
        )
    )
    result = {
        "schema": "ordered-carry-independent-audit/v2.1",
        "passed": bool(passed),
        "control_passed": control,
        "grip_qualification_passed": bool(qualification and control),
        "task_gates": {k: bool(v) for k, v in task_gates.items()},
        "gates": {k: bool(v) for k, v in gates.items()},
        "metrics": metrics,
        "report": _file_binding(root / "REPORT.json"),
        "trace": report["trace"],
        "implementation": _file_binding(Path(__file__)),
        "physics_steps": 0,
        "preloaded_grasp_not_pickup": True,
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output, result)
    print(
        {
            "stage": str(root),
            "passed": result["passed"],
            "control": control,
            "grip_qualification": result["grip_qualification_passed"],
            "gates": result["gates"],
            "task": result["task_gates"],
            "metrics": metrics,
        },
        flush=True,
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    audit(p.parse_args().root)
